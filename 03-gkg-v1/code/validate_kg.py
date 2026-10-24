#################################################################
#
#    Purpose: Validate the Contra Costa Knowledge Graph
#    
#    Checks for:
#    - Ontology compliance
#    - Data quality issues
#    - Relationship consistency
#    - Coverage statistics
#    - New entity types and relationships
#
#    Synapse Partners, LLC 
#################################################################

import rdflib
from rdflib.namespace import RDF, RDFS, OWL, XSD
from rdflib import Namespace, URIRef, Literal
import os
import argparse
import time
import json
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

# Namespaces
UKO = Namespace("urn:urban-kg:")
UKO_ENTITY = Namespace("urn:urban-kg:entity/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class KGValidator:
    """Validates the Urban Knowledge Graph."""
    
    def __init__(self, kg_path: str):
        self.kg_path = kg_path
        self.graph = None
        self.issues = []
        self.warnings = []
        self.stats = {}
        
    def load_graph(self) -> bool:
        """Load the knowledge graph."""
        if not os.path.exists(self.kg_path):
            print(f"ERROR: File not found: {self.kg_path}")
            return False
        
        print(f"Loading knowledge graph from: {self.kg_path}")
        start = time.time()
        
        self.graph = rdflib.Graph()
        
        # Detect format
        fmt = 'nt' if self.kg_path.endswith('.nt') else 'turtle'
        
        try:
            self.graph.parse(self.kg_path, format=fmt)
            print(f"✓ Loaded {len(self.graph):,} triples in {time.time()-start:.1f}s")
            return True
        except Exception as e:
            print(f"ERROR: Failed to load graph: {e}")
            return False
    
    def validate_all(self) -> Dict:
        """Run all validation checks."""
        print("\n" + "="*60)
        print("KNOWLEDGE GRAPH VALIDATION")
        print("="*60)
        
        if not self.load_graph():
            return {'success': False, 'error': 'Failed to load graph'}
        
        # Run checks
        self._check_basic_stats()
        self._check_entity_types()
        self._check_relationships()
        self._check_coordinates()
        self._check_neighborhoods_districts()
        self._check_vulnerable_populations()
        self._check_safety_infrastructure()
        self._check_city_containment()
        self._check_data_quality()
        
        # Summary
        self._print_summary()
        
        return {
            'success': len(self.issues) == 0,
            'stats': self.stats,
            'issues': self.issues,
            'warnings': self.warnings
        }
    
    def _check_basic_stats(self):
        """Basic graph statistics."""
        print("\n--- Basic Statistics ---")
        
        self.stats['total_triples'] = len(self.graph)
        print(f"Total triples: {self.stats['total_triples']:,}")
        
        # Count unique subjects, predicates, objects
        subjects = set(s for s, _, _ in self.graph)
        predicates = set(p for _, p, _ in self.graph)
        objects = set(o for _, _, o in self.graph)
        
        self.stats['unique_subjects'] = len(subjects)
        self.stats['unique_predicates'] = len(predicates)
        self.stats['unique_objects'] = len(objects)
        
        print(f"Unique subjects: {len(subjects):,}")
        print(f"Unique predicates: {len(predicates):,}")
        print(f"Unique objects: {len(objects):,}")
    
    def _check_entity_types(self):
        """Check entity type distribution."""
        print("\n--- Entity Types ---")
        
        type_counts = defaultdict(int)
        
        for s, p, o in self.graph.triples((None, RDF.type, None)):
            if isinstance(o, URIRef):
                type_name = str(o).split('/')[-1].split(':')[-1]
                type_counts[type_name] += 1
        
        self.stats['entity_types'] = dict(type_counts)
        self.stats['num_entity_types'] = len(type_counts)
        
        print(f"Found {len(type_counts)} entity types")
        
        # Top types
        print("\nTop 20 entity types:")
        for type_name, count in sorted(type_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"  {type_name}: {count:,}")
        
        # Check for key types
        key_types = ['City', 'Road', 'School', 'Hospital', 'Park', 
                     'BusStop', 'Neighborhood', 'District', 'NursingHome']
        
        missing_types = [t for t in key_types if type_counts.get(t, 0) == 0]
        if missing_types:
            self.warnings.append(f"Missing key entity types: {missing_types}")
    
    def _check_relationships(self):
        """Check relationship distribution."""
        print("\n--- Relationships ---")
        
        rel_counts = defaultdict(int)
        
        for s, p, o in self.graph:
            if isinstance(o, URIRef) and p != RDF.type:
                rel_name = str(p).split('/')[-1].split(':')[-1]
                rel_counts[rel_name] += 1
        
        self.stats['relationships'] = dict(rel_counts)
        self.stats['num_relationship_types'] = len(rel_counts)
        
        print(f"Found {len(rel_counts)} relationship types")
        
        # Categorize relationships
        spatial_rels = ['adjacentTo', 'near', 'withinWalkingDistanceOf', 
                       'withinCyclingDistanceOf', 'nearVulnerablePopulation']
        infra_rels = ['hasSidewalk', 'hasBikeLane', 'hasCrossing', 
                     'hasTrafficCalming', 'hasTrafficSignal']
        containment_rels = ['partOf', 'contains', 'inNeighborhood', 'inDistrict']
        
        print("\nSpatial relationships:")
        spatial_total = 0
        for rel in spatial_rels:
            count = rel_counts.get(rel, 0)
            spatial_total += count
            if count > 0:
                print(f"  {rel}: {count:,}")
        
        print(f"\nInfrastructure relationships:")
        infra_total = 0
        for rel in infra_rels:
            count = rel_counts.get(rel, 0)
            infra_total += count
            if count > 0:
                print(f"  {rel}: {count:,}")
        
        print(f"\nContainment relationships:")
        contain_total = 0
        for rel in containment_rels:
            count = rel_counts.get(rel, 0)
            contain_total += count
            if count > 0:
                print(f"  {rel}: {count:,}")
        
        self.stats['spatial_relationship_count'] = spatial_total
        self.stats['infrastructure_relationship_count'] = infra_total
        self.stats['containment_relationship_count'] = contain_total
        
        # Check for missing key relationships
        if spatial_total == 0:
            self.warnings.append("No spatial relationships found")
        if rel_counts.get('partOf', 0) == 0:
            self.warnings.append("No partOf relationships (city containment) found")
    
    def _check_coordinates(self):
        """Check coordinate coverage."""
        print("\n--- Coordinate Coverage ---")
        
        query = """
            PREFIX uko: <urn:urban-kg:>
            SELECT (COUNT(DISTINCT ?entity) as ?count)
            WHERE {
                ?entity uko:latitude ?lat ;
                        uko:longitude ?lon .
            }
        """
        
        results = list(self.graph.query(query))
        num_with_coords = int(results[0][0]) if results else 0
        
        self.stats['entities_with_coordinates'] = num_with_coords
        
        # Get total entities
        total_entities = len(set(s for s, _, _ in self.graph.triples((None, RDF.type, None))))
        
        coverage = 100 * num_with_coords / total_entities if total_entities > 0 else 0
        self.stats['coordinate_coverage_pct'] = round(coverage, 1)
        
        print(f"Entities with coordinates: {num_with_coords:,} / {total_entities:,} ({coverage:.1f}%)")
        
        # Check coordinate ranges (should be in California)
        lat_query = """
            PREFIX uko: <urn:urban-kg:>
            SELECT (MIN(?lat) as ?min_lat) (MAX(?lat) as ?max_lat)
                   (MIN(?lon) as ?min_lon) (MAX(?lon) as ?max_lon)
            WHERE {
                ?entity uko:latitude ?lat ;
                        uko:longitude ?lon .
            }
        """
        
        results = list(self.graph.query(lat_query))
        if results and results[0][0]:
            min_lat, max_lat = float(results[0][0]), float(results[0][1])
            min_lon, max_lon = float(results[0][2]), float(results[0][3])
            
            print(f"Latitude range: {min_lat:.4f} to {max_lat:.4f}")
            print(f"Longitude range: {min_lon:.4f} to {max_lon:.4f}")
            
            # California bounds check
            if not (32 <= min_lat <= 42 and 32 <= max_lat <= 42):
                self.warnings.append(f"Latitude range {min_lat}-{max_lat} outside California")
            if not (-125 <= min_lon <= -114 and -125 <= max_lon <= -114):
                self.warnings.append(f"Longitude range {min_lon}-{max_lon} outside California")
    
    def _check_neighborhoods_districts(self):
        """Check neighborhood and district data."""
        print("\n--- Neighborhoods & Districts ---")
        
        neighborhood_types = [
            'Neighborhood', 'OfficialNeighborhood', 'InformalNeighborhood', 
            'HistoricNeighborhood', 'Suburb', 'Quarter'
        ]
        
        district_types = [
            'District', 'FunctionalDistrict', 'AutoRow', 'RestaurantRow',
            'ArtDistrict', 'EntertainmentDistrict', 'MedicalDistrict',
            'EthnicEnclave', 'Chinatown', 'LittleItaly'
        ]
        
        neighborhood_count = 0
        district_count = 0
        
        for type_name in neighborhood_types:
            count = len(list(self.graph.triples((None, RDF.type, UKO[type_name]))))
            neighborhood_count += count
            if count > 0:
                print(f"  {type_name}: {count}")
        
        for type_name in district_types:
            count = len(list(self.graph.triples((None, RDF.type, UKO[type_name]))))
            district_count += count
            if count > 0:
                print(f"  {type_name}: {count}")
        
        self.stats['neighborhood_count'] = neighborhood_count
        self.stats['district_count'] = district_count
        
        print(f"\nTotal neighborhoods: {neighborhood_count}")
        print(f"Total districts: {district_count}")
        
        # Check for LLM-discovered areas (have confidence levels)
        confidence_query = """
            PREFIX uko: <urn:urban-kg:>
            SELECT (COUNT(?entity) as ?count)
            WHERE {
                ?entity uko:hasConfidenceLevel ?conf .
            }
        """
        
        results = list(self.graph.query(confidence_query))
        llm_discovered = int(results[0][0]) if results else 0
        
        if llm_discovered > 0:
            print(f"LLM-discovered areas (with confidence): {llm_discovered}")
            self.stats['llm_discovered_areas'] = llm_discovered
    
    def _check_vulnerable_populations(self):
        """Check vulnerable population facility data."""
        print("\n--- Vulnerable Population Facilities ---")
        
        vulnerable_types = [
            'NursingHome', 'AssistedLivingFacility', 'SeniorCenter',
            'GroupHome', 'Hospice', 'AdultDayCare', 'HomelessShelter'
        ]
        
        total_vulnerable = 0
        for type_name in vulnerable_types:
            count = len(list(self.graph.triples((None, RDF.type, UKO[type_name]))))
            if count > 0:
                print(f"  {type_name}: {count}")
                total_vulnerable += count
        
        self.stats['vulnerable_population_facilities'] = total_vulnerable
        
        # Check nearVulnerablePopulation relationships
        near_vuln_count = len(list(self.graph.triples((None, UKO.nearVulnerablePopulation, None))))
        serves_vuln_count = len(list(self.graph.triples((None, UKO.servesVulnerablePopulation, None))))
        
        print(f"\nnearVulnerablePopulation relationships: {near_vuln_count:,}")
        print(f"servesVulnerablePopulation relationships: {serves_vuln_count:,}")
        
        self.stats['near_vulnerable_relationships'] = near_vuln_count
        self.stats['serves_vulnerable_relationships'] = serves_vuln_count
    
    def _check_safety_infrastructure(self):
        """Check safety infrastructure data."""
        print("\n--- Safety Infrastructure ---")
        
        safety_types = [
            'PedestrianCrossing', 'SignalizedCrossing', 'ZebraCrossing',
            'SpeedBump', 'SpeedHump', 'SpeedTable', 'TrafficCalming',
            'TrafficSignal', 'Chicane', 'TrafficIsland'
        ]
        
        total_safety = 0
        for type_name in safety_types:
            count = len(list(self.graph.triples((None, RDF.type, UKO[type_name]))))
            if count > 0:
                print(f"  {type_name}: {count}")
                total_safety += count
        
        self.stats['safety_infrastructure_count'] = total_safety
        
        # Check safety relationships
        crossing_count = len(list(self.graph.triples((None, UKO.hasCrossing, None))))
        calming_count = len(list(self.graph.triples((None, UKO.hasTrafficCalming, None))))
        signal_count = len(list(self.graph.triples((None, UKO.hasTrafficSignal, None))))
        
        print(f"\nhasCrossing relationships: {crossing_count:,}")
        print(f"hasTrafficCalming relationships: {calming_count:,}")
        print(f"hasTrafficSignal relationships: {signal_count:,}")
        
        self.stats['has_crossing_relationships'] = crossing_count
        self.stats['has_traffic_calming_relationships'] = calming_count
        self.stats['has_traffic_signal_relationships'] = signal_count
    
    def _check_city_containment(self):
        """Check city containment relationships."""
        print("\n--- City Containment ---")
        
        # Find cities
        cities = list(self.graph.triples((None, RDF.type, UKO.City)))
        print(f"Cities found: {len(cities)}")
        
        for city_uri, _, _ in cities:
            city_label = self.graph.value(city_uri, RDFS.label)
            
            # Count entities in this city
            entities_in_city = len(list(self.graph.triples((None, UKO.partOf, city_uri))))
            print(f"  {city_label}: {entities_in_city:,} entities")
        
        self.stats['num_cities'] = len(cities)
        
        # Check for orphan entities (no city)
        total_entities = len(set(s for s, _, _ in self.graph.triples((None, RDF.type, None))))
        entities_with_city = len(set(s for s, _, _ in self.graph.triples((None, UKO.partOf, None))))
        orphans = total_entities - entities_with_city
        
        if orphans > total_entities * 0.5:  # More than 50% orphans
            self.warnings.append(f"{orphans:,} entities have no city containment")
    
    def _check_data_quality(self):
        """Check for data quality issues."""
        print("\n--- Data Quality Checks ---")
        
        # Check for entities without labels
        entities_without_label = 0
        for s, _, _ in self.graph.triples((None, RDF.type, None)):
            if not self.graph.value(s, RDFS.label):
                entities_without_label += 1
        
        if entities_without_label > 0:
            print(f"Entities without labels: {entities_without_label:,}")
            if entities_without_label > 1000:
                self.warnings.append(f"{entities_without_label:,} entities missing labels")
        
        # Check for duplicate triples (shouldn't exist in RDF, but check anyway)
        print("✓ No duplicate triple check (RDF graphs are sets)")
        
        # Check for self-referential relationships
        self_refs = 0
        for s, p, o in self.graph:
            if s == o and p != RDF.type:
                self_refs += 1
        
        if self_refs > 0:
            print(f"Self-referential triples: {self_refs}")
            self.warnings.append(f"{self_refs} self-referential triples found")
        
        self.stats['data_quality_issues'] = len(self.warnings)
    
    def _print_summary(self):
        """Print validation summary."""
        print("\n" + "="*60)
        print("VALIDATION SUMMARY")
        print("="*60)
        
        print(f"\nTotal triples: {self.stats.get('total_triples', 0):,}")
        print(f"Entity types: {self.stats.get('num_entity_types', 0)}")
        print(f"Relationship types: {self.stats.get('num_relationship_types', 0)}")
        print(f"Coordinate coverage: {self.stats.get('coordinate_coverage_pct', 0)}%")
        
        print(f"\nNeighborhoods: {self.stats.get('neighborhood_count', 0)}")
        print(f"Districts: {self.stats.get('district_count', 0)}")
        print(f"Vulnerable facilities: {self.stats.get('vulnerable_population_facilities', 0)}")
        print(f"Safety infrastructure: {self.stats.get('safety_infrastructure_count', 0)}")
        
        if self.issues:
            print(f"\n❌ ISSUES ({len(self.issues)}):")
            for issue in self.issues:
                print(f"  - {issue}")
        
        if self.warnings:
            print(f"\n⚠ WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  - {warning}")
        
        if not self.issues and not self.warnings:
            print("\n✓ All validation checks passed!")
        elif not self.issues:
            print("\n✓ Validation passed with warnings")
        else:
            print("\n❌ Validation failed")


def main():
    parser = argparse.ArgumentParser(
        description="Validate the Contra Costa Urban Knowledge Graph"
    )
    parser.add_argument(
        "--kg_file",
        default="contracosta_kg_enhanced.ttl",
        help="Path to knowledge graph file (.ttl or .nt)"
    )
    parser.add_argument(
        "--output",
        help="Output JSON file for validation results"
    )
    
    args = parser.parse_args()
    
    validator = KGValidator(args.kg_file)
    results = validator.validate_all()
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n✓ Results saved to {args.output}")
    
    return 0 if results['success'] else 1


if __name__ == "__main__":
    exit(main())
