#!/usr/bin/env python3
"""
Cross-Domain Relationship Materializer

This script computes and adds cross-domain relationships to the KG that
connect entities across different data domains (OSM, Census, Safety, POI).

These materialized relationships enable:
1. Multi-hop reasoning in embeddings
2. Direct SPARQL queries across domains
3. Link prediction for missing connections

The script uses spatial operations to compute relationships like:
- POI near HIN (within 200m)
- Collision in Census Tract
- Transit stop serves low-income area
- School requires HIN crossing

Usage:
    python materialize_relationships.py --input kg.nt --output kg_with_relations.nt

Prerequisites:
    pip install pandas geopandas shapely scipy rtree

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import re
import argparse
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass
from collections import defaultdict

import pandas as pd
import numpy as np
from shapely.geometry import Point, LineString, Polygon, box
from shapely.ops import nearest_points
from scipy.spatial import cKDTree

# Constants
UKO = "urn:urban-kg:"
UKO_ENTITY = "urn:urban-kg:entity/"

# Distance thresholds (in degrees, ~111m per 0.001 degree at this latitude)
NEAR_THRESHOLD = 0.002      # ~220m - "near" relationship
VERY_NEAR_THRESHOLD = 0.001  # ~110m - "very near" / adjacent
WALKABLE_THRESHOLD = 0.004   # ~440m - walkable distance
TRANSIT_ACCESS_THRESHOLD = 0.004  # ~440m - transit accessibility


@dataclass
class Entity:
    """Represents a KG entity with location."""
    uri: str
    entity_type: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    label: Optional[str] = None
    properties: Dict = None
    
    def __post_init__(self):
        if self.properties is None:
            self.properties = {}
    
    @property
    def has_location(self) -> bool:
        return self.lat is not None and self.lon is not None
    
    @property
    def point(self) -> Optional[Point]:
        if self.has_location:
            return Point(self.lon, self.lat)
        return None


class KGEntityExtractor:
    """Extracts entities from N-Triples KG file."""
    
    def __init__(self, kg_path: str):
        self.kg_path = kg_path
        self.entities: Dict[str, Entity] = {}
        
    def extract_entities(self) -> Dict[str, Entity]:
        """Extract all entities with their types and locations."""
        print(f"Extracting entities from {self.kg_path}...")
        
        # First pass: collect types and properties
        entity_data = defaultdict(lambda: {'types': set(), 'props': {}})
        
        line_count = 0
        with open(self.kg_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_count += 1
                if line_count % 1000000 == 0:
                    print(f"  Processed {line_count:,} lines...")
                
                # Parse N-Triple
                match = re.match(r'<([^>]+)>\s+<([^>]+)>\s+(.+)\s+\.', line.strip())
                if not match:
                    continue
                
                subject, predicate, obj = match.groups()
                
                # Extract type
                if predicate == 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type':
                    type_match = re.match(r'<([^>]+)>', obj)
                    if type_match:
                        entity_data[subject]['types'].add(type_match.group(1))
                
                # Extract coordinates
                elif predicate == f'{UKO}latitude':
                    val_match = re.match(r'"([^"]+)"', obj)
                    if val_match:
                        try:
                            entity_data[subject]['props']['lat'] = float(val_match.group(1))
                        except:
                            pass
                
                elif predicate == f'{UKO}longitude':
                    val_match = re.match(r'"([^"]+)"', obj)
                    if val_match:
                        try:
                            entity_data[subject]['props']['lon'] = float(val_match.group(1))
                        except:
                            pass
                
                # Extract label
                elif predicate == 'http://www.w3.org/2000/01/rdf-schema#label':
                    val_match = re.match(r'"([^"]*)"', obj)
                    if val_match:
                        entity_data[subject]['props']['label'] = val_match.group(1)
        
        # Convert to Entity objects
        for uri, data in entity_data.items():
            if data['types']:
                # Get primary type (prefer specific types)
                primary_type = self._get_primary_type(data['types'])
                
                self.entities[uri] = Entity(
                    uri=uri,
                    entity_type=primary_type,
                    lat=data['props'].get('lat'),
                    lon=data['props'].get('lon'),
                    label=data['props'].get('label'),
                    properties=data['props']
                )
        
        print(f"  Extracted {len(self.entities):,} entities")
        return self.entities
    
    def _get_primary_type(self, types: Set[str]) -> str:
        """Get the most specific type from a set of types."""
        # Priority order for type selection
        priority_prefixes = [
            f'{UKO}HighInjuryNetwork',
            f'{UKO}Collision',
            f'{UKO}CensusTract',
            f'{UKO}School',
            f'{UKO}Hospital',
            f'{UKO}TransitStop',
            f'{UKO}VulnerablePopulation',
            f'{UKO}Neighborhood',
            f'{UKO}District',
            f'{UKO}Road',
            f'{UKO}Sidewalk',
            f'{UKO}Crossing',
        ]
        
        for prefix in priority_prefixes:
            for t in types:
                if t.startswith(prefix):
                    return t
        
        # Return first UKO type found
        for t in types:
            if t.startswith(UKO):
                return t
        
        return list(types)[0] if types else 'Unknown'


class SpatialIndex:
    """Spatial index for efficient proximity queries."""
    
    def __init__(self, entities: Dict[str, Entity]):
        self.entities = entities
        self.located_entities = {
            uri: e for uri, e in entities.items() if e.has_location
        }
        
        # Build KD-tree for fast spatial queries
        if self.located_entities:
            self.uris = list(self.located_entities.keys())
            coords = np.array([
                [e.lon, e.lat] for e in self.located_entities.values()
            ])
            self.tree = cKDTree(coords)
        else:
            self.tree = None
            self.uris = []
    
    def find_within_distance(self, point: Point, distance: float) -> List[str]:
        """Find all entity URIs within distance of point."""
        if self.tree is None:
            return []
        
        indices = self.tree.query_ball_point([point.x, point.y], distance)
        return [self.uris[i] for i in indices]
    
    def find_nearest(self, point: Point, k: int = 5) -> List[Tuple[str, float]]:
        """Find k nearest entities and their distances."""
        if self.tree is None:
            return []
        
        distances, indices = self.tree.query([point.x, point.y], k=min(k, len(self.uris)))
        
        if isinstance(indices, np.integer):
            indices = [indices]
            distances = [distances]
        
        return [(self.uris[i], d) for i, d in zip(indices, distances)]


class RelationshipMaterializer:
    """Computes and materializes cross-domain relationships."""
    
    def __init__(self, entities: Dict[str, Entity]):
        self.entities = entities
        self.spatial_index = SpatialIndex(entities)
        
        # Group entities by type for efficient querying
        self.by_type: Dict[str, List[Entity]] = defaultdict(list)
        for e in entities.values():
            # Add to primary type group
            self.by_type[e.entity_type].append(e)
            # Also add to broader category groups
            if 'School' in e.entity_type:
                self.by_type['School'].append(e)
            if 'Hospital' in e.entity_type or 'Healthcare' in e.entity_type:
                self.by_type['Healthcare'].append(e)
            if 'TransitStop' in e.entity_type or 'BusStop' in e.entity_type:
                self.by_type['TransitStop'].append(e)
            if 'HighInjuryNetwork' in e.entity_type:
                self.by_type['HIN'].append(e)
            if 'Collision' in e.entity_type:
                self.by_type['Collision'].append(e)
            if 'CensusTract' in e.entity_type:
                self.by_type['CensusTract'].append(e)
            if 'VulnerablePopulation' in e.entity_type or 'SeniorCenter' in e.entity_type or 'NursingHome' in e.entity_type:
                self.by_type['VulnerableFacility'].append(e)
            if 'Neighborhood' in e.entity_type:
                self.by_type['Neighborhood'].append(e)
        
        print(f"Entity type distribution:")
        for etype, elist in sorted(self.by_type.items(), key=lambda x: -len(x[1]))[:15]:
            print(f"  {etype}: {len(elist):,}")
    
    def compute_poi_hin_relationships(self) -> List[str]:
        """Compute POI near/on HIN relationships."""
        triples = []
        hin_entities = self.by_type.get('HIN', [])
        
        if not hin_entities:
            print("  No HIN entities found")
            return triples
        
        print(f"  Computing POI-HIN relationships for {len(hin_entities)} HIN segments...")
        
        # For each HIN segment, find nearby POIs
        poi_types = ['School', 'Healthcare', 'TransitStop', 'VulnerableFacility']
        
        for hin in hin_entities:
            if not hin.has_location:
                continue
            
            nearby_uris = self.spatial_index.find_within_distance(hin.point, NEAR_THRESHOLD)
            
            for uri in nearby_uris:
                entity = self.entities.get(uri)
                if not entity or entity.uri == hin.uri:
                    continue
                
                # Check if it's a POI type we care about
                for poi_type in poi_types:
                    if poi_type in entity.entity_type:
                        # Determine relationship type
                        if poi_type == 'School':
                            rel = f'{UKO}schoolNearHIN'
                        elif poi_type == 'VulnerableFacility':
                            rel = f'{UKO}seniorFacilityNearHIN'
                        elif poi_type == 'TransitStop':
                            rel = f'{UKO}transitStopInHIN'
                        else:
                            rel = f'{UKO}nearHighInjuryNetwork'
                        
                        triples.append(f'<{entity.uri}> <{rel}> <{hin.uri}> .')
                        break
        
        print(f"    Generated {len(triples):,} POI-HIN relationships")
        return triples
    
    def compute_poi_census_relationships(self) -> List[str]:
        """Compute POI in census tract relationships."""
        triples = []
        tracts = self.by_type.get('CensusTract', [])
        
        if not tracts:
            print("  No census tracts found")
            return triples
        
        print(f"  Computing POI-Census relationships for {len(tracts)} tracts...")
        
        # For each tract with location, find POIs within
        # Note: This is approximate using centroid; proper implementation would use tract boundaries
        for tract in tracts:
            if not tract.has_location:
                continue
            
            # Use a larger radius for tract coverage (~1km)
            nearby_uris = self.spatial_index.find_within_distance(tract.point, 0.01)
            
            for uri in nearby_uris:
                entity = self.entities.get(uri)
                if not entity or entity.uri == tract.uri:
                    continue
                
                # Skip non-POI types
                if 'CensusTract' in entity.entity_type or 'Road' in entity.entity_type:
                    continue
                
                triples.append(f'<{entity.uri}> <{UKO}inCensusTract> <{tract.uri}> .')
        
        print(f"    Generated {len(triples):,} POI-Census relationships")
        return triples
    
    def compute_collision_tract_relationships(self) -> List[str]:
        """Compute collision in census tract relationships."""
        triples = []
        collisions = self.by_type.get('Collision', [])
        tracts = self.by_type.get('CensusTract', [])
        
        if not collisions or not tracts:
            print("  No collisions or tracts found")
            return triples
        
        print(f"  Computing Collision-Census relationships...")
        
        # Build tract spatial index
        tract_coords = []
        tract_list = []
        for t in tracts:
            if t.has_location:
                tract_coords.append([t.lon, t.lat])
                tract_list.append(t)
        
        if not tract_coords:
            return triples
        
        tract_tree = cKDTree(np.array(tract_coords))
        
        # For each collision, find nearest tract
        for collision in collisions:
            if not collision.has_location:
                continue
            
            # Find nearest tract (assign collision to closest tract centroid)
            dist, idx = tract_tree.query([collision.lon, collision.lat], k=1)
            
            if dist < 0.02:  # Within ~2km of tract centroid
                tract = tract_list[idx]
                triples.append(f'<{collision.uri}> <{UKO}collisionInTract> <{tract.uri}> .')
        
        print(f"    Generated {len(triples):,} Collision-Census relationships")
        return triples
    
    def compute_transit_poi_relationships(self) -> List[str]:
        """Compute transit stop near POI relationships."""
        triples = []
        transit_stops = self.by_type.get('TransitStop', [])
        
        if not transit_stops:
            print("  No transit stops found")
            return triples
        
        print(f"  Computing Transit-POI relationships for {len(transit_stops)} stops...")
        
        for stop in transit_stops:
            if not stop.has_location:
                continue
            
            nearby_uris = self.spatial_index.find_within_distance(stop.point, TRANSIT_ACCESS_THRESHOLD)
            
            for uri in nearby_uris:
                entity = self.entities.get(uri)
                if not entity or entity.uri == stop.uri:
                    continue
                
                # Create specific relationships based on POI type
                if 'School' in entity.entity_type:
                    triples.append(f'<{stop.uri}> <{UKO}transitStopNearSchool> <{entity.uri}> .')
                elif 'Hospital' in entity.entity_type or 'Healthcare' in entity.entity_type:
                    triples.append(f'<{stop.uri}> <{UKO}transitStopNearHealthcare> <{entity.uri}> .')
                elif 'VulnerablePopulation' in entity.entity_type or 'SeniorCenter' in entity.entity_type:
                    triples.append(f'<{stop.uri}> <{UKO}transitStopNearSeniorFacility> <{entity.uri}> .')
        
        print(f"    Generated {len(triples):,} Transit-POI relationships")
        return triples
    
    def compute_hin_tract_relationships(self) -> List[str]:
        """Compute HIN in census tract relationships."""
        triples = []
        hin_segments = self.by_type.get('HIN', [])
        tracts = self.by_type.get('CensusTract', [])
        
        if not hin_segments or not tracts:
            return triples
        
        print(f"  Computing HIN-Census relationships...")
        
        # Build tract spatial index
        tract_coords = []
        tract_list = []
        for t in tracts:
            if t.has_location:
                tract_coords.append([t.lon, t.lat])
                tract_list.append(t)
        
        if not tract_coords:
            return triples
        
        tract_tree = cKDTree(np.array(tract_coords))
        tracts_with_hin = set()
        
        for hin in hin_segments:
            if not hin.has_location:
                continue
            
            dist, idx = tract_tree.query([hin.lon, hin.lat], k=1)
            
            if dist < 0.02:
                tract = tract_list[idx]
                triples.append(f'<{hin.uri}> <{UKO}hinInTract> <{tract.uri}> .')
                tracts_with_hin.add(tract.uri)
        
        # Mark tracts that have HIN
        for tract_uri in tracts_with_hin:
            triples.append(f'<{tract_uri}> <{UKO}tractHasHIN> "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .')
        
        print(f"    Generated {len(triples):,} HIN-Census relationships")
        return triples
    
    def materialize_all(self) -> List[str]:
        """Compute all cross-domain relationships."""
        print("\nMaterializing cross-domain relationships...")
        
        all_triples = []
        
        # POI ↔ Safety
        all_triples.extend(self.compute_poi_hin_relationships())
        
        # POI ↔ Census
        all_triples.extend(self.compute_poi_census_relationships())
        
        # Collision ↔ Census
        all_triples.extend(self.compute_collision_tract_relationships())
        
        # Transit ↔ POI
        all_triples.extend(self.compute_transit_poi_relationships())
        
        # HIN ↔ Census
        all_triples.extend(self.compute_hin_tract_relationships())
        
        print(f"\nTotal new relationships: {len(all_triples):,}")
        return all_triples


def main(input_file: str, output_file: Optional[str] = None):
    """Main function to materialize relationships."""
    
    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_with_relations{ext}"
    
    print("=" * 60)
    print("CROSS-DOMAIN RELATIONSHIP MATERIALIZER")
    print("=" * 60)
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print()
    
    # Extract entities
    extractor = KGEntityExtractor(input_file)
    entities = extractor.extract_entities()
    
    # Materialize relationships
    materializer = RelationshipMaterializer(entities)
    new_triples = materializer.materialize_all()
    
    # Write to temp file
    temp_file = output_file + ".relations.tmp"
    with open(temp_file, 'w', encoding='utf-8') as f:
        for triple in new_triples:
            f.write(triple + '\n')
    
    # Concatenate with original KG
    print(f"\nConcatenating with original KG...")
    with open(output_file, 'w', encoding='utf-8') as out:
        with open(input_file, 'r', encoding='utf-8') as inp:
            for line in inp:
                out.write(line)
        with open(temp_file, 'r', encoding='utf-8') as tmp:
            for line in tmp:
                out.write(line)
    
    # Clean up
    os.remove(temp_file)
    
    print()
    print("=" * 60)
    print("MATERIALIZATION COMPLETE")
    print("=" * 60)
    print(f"New relationships added: {len(new_triples):,}")
    print(f"Output: {output_file}")
    
    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Materialize cross-domain relationships in the KG"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input KG (.nt file)"
    )
    parser.add_argument(
        "--output",
        help="Path for output KG (default: adds _with_relations suffix)"
    )
    
    args = parser.parse_args()
    
    main(input_file=args.input, output_file=args.output)
