"""
POI Resolver Module
Resolves GPS coordinates to actual POIs using Knowledge Graph + Embeddings
Handles imprecise mobile GPS data with probabilistic matching
"""

import numpy as np
import pandas as pd
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, RDFS
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from math import radians, sin, cos, sqrt, atan2
import logging
import os

# Namespaces
UKO = Namespace("urn:urban-kg:")
UKO_ENTITY = Namespace("urn:urban-kg:entity/osm/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


@dataclass
class POICandidate:
    """A candidate POI for a location"""
    uri: str
    name: str
    poi_type: str
    coordinates: Tuple[float, float]  # (lat, lon)
    distance_meters: float
    confidence: float
    resolution_method: str
    embedding_similarity: Optional[float] = None
    attributes: Dict = None
    
    def to_dict(self) -> Dict:
        return {
            'uri': self.uri,
            'name': self.name,
            'type': self.poi_type,
            'coordinates': {
                'latitude': self.coordinates[0],
                'longitude': self.coordinates[1]
            },
            'distance_meters': round(self.distance_meters, 2),
            'confidence': round(self.confidence, 3),
            'resolution_method': self.resolution_method,
            'embedding_similarity': round(self.embedding_similarity, 3) if self.embedding_similarity else None,
            'attributes': self.attributes or {}
        }


class POIResolver:
    """
    Resolves GPS coordinates to POIs using multiple strategies:
    1. Spatial proximity (KG query for nearby POIs)
    2. Embedding similarity (semantic matching)
    3. Contextual factors (time of day, trip patterns)
    4. POI importance (major landmarks vs minor POIs)
    """
    
    # Search radii for different POI types (meters)
    SEARCH_RADII = {
        'default': 200,  # Increased from 100m for mobile GPS accuracy
        'major_landmark': 500,  # Increased from 200m
        'transit_stop': 100,  # Increased from 50m
        'building': 50,  # Increased from 30m
        'parking': 100  # Increased from 50m
    }
    
    # POI type importance weights (higher = more important/relevant)
    POI_IMPORTANCE = {
        # Transit and transportation
        'TransitStation': 1.0,
        'BusStop': 0.9,
        'TrainStation': 1.0,
        'SubwayStation': 1.0,
        'LightRailStation': 1.0,
        'BusStation': 1.0,
        'Parking': 0.6,
        'ParkingFacility': 0.6,
        
        # Major landmarks and institutions
        'Hospital': 1.0,
        'School': 0.95,
        'University': 0.95,
        'Library': 0.8,
        'CityHall': 0.9,
        'TownHall': 0.9,
        'PostOffice': 0.85,
        
        # Commercial and retail
        'ShoppingCenter': 0.9,
        'ShoppingMall': 0.9,
        'Supermarket': 0.85,
        'ConvenienceStore': 0.7,
        'Store': 0.6,
        'Restaurant': 0.7,
        'FastFoodRestaurant': 0.65,
        'Cafe': 0.65,
        'Bar': 0.6,
        
        # Residential and buildings
        'ApartmentBuilding': 0.75,
        'ResidentialBuilding': 0.75,
        'SingleFamilyHome': 0.5,
        'OfficeBuilding': 0.8,
        
        # Recreation and entertainment
        'Park': 0.85,
        'Gym': 0.7,
        'SportsCenter': 0.75,
        'Theater': 0.75,
        'Cinema': 0.75,
        'Museum': 0.8,
        
        # Services
        'Bank': 0.8,
        'ATM': 0.6,
        'Pharmacy': 0.85,
        'GasStation': 0.75,
        'FuelStation': 0.75,
        'CarRepair': 0.7,
        
        # Default for unknown types
        'default': 0.5
    }
    
    def __init__(self, kg_file: str, embeddings_file: Optional[str] = None):
        """
        Initialize POI Resolver
        
        Args:
            kg_file: Path to knowledge graph TTL file
            embeddings_file: Path to entity embeddings CSV (optional)
        """
        self.logger = logging.getLogger(__name__)
        
        # Load knowledge graph
        print(f"Loading knowledge graph from {kg_file}...")
        self.graph = Graph()
        self.graph.parse(kg_file, format="turtle")
        print(f"✓ Loaded {len(self.graph):,} triples")
        
        # Build spatial index
        print("Building spatial index...")
        self.spatial_index = self._build_spatial_index()
        print(f"✓ Indexed {len(self.spatial_index)} POIs")
        
        # Load embeddings if provided
        self.embeddings = None
        self.embedding_index = None
        self.embedding_dim = None
        if embeddings_file:
            print(f"Loading embeddings from {embeddings_file}...")
            self._load_embeddings(embeddings_file)
    
    def _load_embeddings(self, embeddings_file: str):
        """Load embeddings and create efficient lookup structures"""
        try:
            # Load CSV with embeddings
            df = pd.read_csv(embeddings_file)
            
            # Expected columns: uri, id, dim_0, dim_1, ..., dim_N
            if 'uri' not in df.columns:
                print("⚠   Warning: embeddings file missing 'uri' column")
                return
            
            # Extract embedding columns (all columns starting with 'dim_')
            embedding_cols = [col for col in df.columns if col.startswith('dim_')]
            if not embedding_cols:
                print("⚠   Warning: no embedding dimension columns found")
                return
            
            self.embedding_dim = len(embedding_cols)
            
            # Create URI to embedding mapping
            self.embedding_index = {}
            self.embeddings = {}
            
            for idx, row in df.iterrows():
                uri = str(row['uri'])
                embedding = row[embedding_cols].values.astype(float)
                self.embeddings[uri] = embedding
                self.embedding_index[uri] = idx
            
            print(f"✓ Loaded embeddings for {len(self.embeddings)} entities ({self.embedding_dim} dimensions)")
            
        except Exception as e:
            print(f"⚠   Warning: Failed to load embeddings: {e}")
            self.embeddings = None
            self.embedding_index = None
    
    def resolve_location(self, 
                        lat: float, 
                        lon: float,
                        context: Optional[Dict] = None,
                        max_candidates: int = 5,
                        min_confidence: float = 0.10,  # Lowered from 0.15 for areas with sparse POI coverage
                        debug: bool = False) -> List[POICandidate]:
        """
        Resolve GPS coordinates to ranked POI candidates
        
        Args:
            lat: Latitude
            lon: Longitude
            context: Optional context (time_of_day, trip_purpose, etc.)
            max_candidates: Maximum candidates to return
            min_confidence: Minimum confidence threshold
            debug: If True, print debug information about filtering
            
        Returns:
            List of POICandidate objects, ranked by confidence
        """
        context = context or {}
        
        # Strategy 1: Spatial proximity search
        nearby_pois = self._spatial_search(lat, lon, radius=self.SEARCH_RADII['default'])
        
        if not nearby_pois:
            # Expand search if nothing found
            nearby_pois = self._spatial_search(lat, lon, radius=self.SEARCH_RADII['major_landmark'])
        
        if not nearby_pois:
            self.logger.warning(f"No POIs found near ({lat}, {lon})")
            return []
        
        if debug:
            print(f"\n  Debug: Found {len(nearby_pois)} POIs within search radius")
        
        # Calculate initial confidence scores
        candidates = []
        filtered_count = 0
        
        for poi in nearby_pois:
            # Base confidence from distance
            distance_confidence = self._distance_confidence(poi['distance'])
            
            # Adjust by POI importance
            poi_type_short = poi['type'].split(':')[-1]
            importance = self.POI_IMPORTANCE.get(poi_type_short, self.POI_IMPORTANCE['default'])
            
            # Combine factors - use additive boost for high-importance POIs
            # This prevents high-importance POIs from being filtered too aggressively
            if importance >= 0.9:
                # For very important POIs (transit, hospitals, etc.), add a base confidence boost
                # Scale the boost based on whether we're within reasonable distance
                if poi['distance'] <= 250:
                    confidence = distance_confidence * importance + 0.15
                else:
                    confidence = distance_confidence * importance + 0.10
            else:
                confidence = distance_confidence * importance
            
            # Strategy 2: Embedding similarity (if available)
            embedding_sim = None
            if self.embeddings is not None and context.get('reference_embedding'):
                embedding_sim = self._embedding_similarity(poi['uri'], context['reference_embedding'])
                if embedding_sim:
                    confidence = 0.7 * confidence + 0.3 * embedding_sim
            
            # Strategy 3: Contextual matching
            if context:
                context_boost = self._contextual_matching(poi, context)
                confidence *= context_boost
            
            # Filter by confidence
            if confidence < min_confidence:
                filtered_count += 1
                if debug and filtered_count <= 5:
                    print(f"  Debug: Filtered '{poi['name']}' ({poi_type_short}, {poi['distance']:.1f}m, "
                          f"dist_conf={distance_confidence:.3f}, importance={importance:.2f}, final_conf={confidence:.3f})")
                continue
            
            candidate = POICandidate(
                uri=poi['uri'],
                name=poi['name'],
                poi_type=poi['type'],
                coordinates=(poi['lat'], poi['lon']),
                distance_meters=poi['distance'],
                confidence=confidence,
                resolution_method='spatial_proximity_with_context',
                embedding_similarity=embedding_sim,
                attributes=poi.get('attributes', {})
            )
            
            candidates.append(candidate)
        
        if debug and filtered_count > 0:
            print(f"  Debug: Filtered {filtered_count} POIs due to low confidence (<{min_confidence})")
        
        # Sort by confidence and filter
        candidates.sort(key=lambda x: x.confidence, reverse=True)
        
        return candidates[:max_candidates]
    
    def resolve_trip_endpoints(self,
                               origin_lat: float,
                               origin_lon: float,
                               dest_lat: float,
                               dest_lon: float,
                               context: Optional[Dict] = None) -> Tuple[List[POICandidate], List[POICandidate]]:
        """
        Resolve both origin and destination POIs for a trip
        
        Returns:
            (origin_candidates, destination_candidates)
        """
        print(f"  Resolving origin POI ({origin_lat:.6f}, {origin_lon:.6f})...")
        origin_candidates = self.resolve_location(origin_lat, origin_lon, context)
        
        print(f"  Resolving destination POI ({dest_lat:.6f}, {dest_lon:.6f})...")
        dest_candidates = self.resolve_location(dest_lat, dest_lon, context)
        
        if origin_candidates:
            print(f"    ✓ Found {len(origin_candidates)} origin candidates (best: {origin_candidates[0].name}, conf={origin_candidates[0].confidence:.2f})")
        else:
            print(f"    ⚠   No origin candidates found")
        
        if dest_candidates:
            print(f"    ✓ Found {len(dest_candidates)} destination candidates (best: {dest_candidates[0].name}, conf={dest_candidates[0].confidence:.2f})")
        else:
            print(f"    ⚠   No destination candidates found")
        
        return origin_candidates, dest_candidates
    
    def _build_spatial_index(self) -> List[Dict]:
        """Build spatial index from knowledge graph - optimized for actual UKO structure"""
        pois = []
        seen_locations = set()  # Track (name, lat, lon) to eliminate duplicates
        
        # SPARQL query to get POIs with coordinates
        # Optimized for the actual way entities are stored in your KG
        query = """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?poi ?name ?type ?lat ?lon
        WHERE {
            ?poi a ?type ;
                 uko:latitude ?lat ;
                 uko:longitude ?lon .
            OPTIONAL { ?poi rdfs:label ?name }
            
            # Only include meaningful POI types that users care about
            FILTER (
                STRSTARTS(STR(?type), "urn:urban-kg:") &&
                (
                    # Transit and transportation
                    CONTAINS(STR(?type), "TransitStation") ||
                    CONTAINS(STR(?type), "BusStation") ||
                    CONTAINS(STR(?type), "BusStop") ||
                    CONTAINS(STR(?type), "TrainStation") ||
                    CONTAINS(STR(?type), "SubwayStation") ||
                    CONTAINS(STR(?type), "LightRailStation") ||
                    CONTAINS(STR(?type), "Platform") ||
                    
                    # Major landmarks and institutions
                    CONTAINS(STR(?type), "Hospital") ||
                    CONTAINS(STR(?type), "Clinic") ||
                    CONTAINS(STR(?type), "School") ||
                    CONTAINS(STR(?type), "University") ||
                    CONTAINS(STR(?type), "College") ||
                    CONTAINS(STR(?type), "Library") ||
                    CONTAINS(STR(?type), "CityHall") ||
                    CONTAINS(STR(?type), "TownHall") ||
                    CONTAINS(STR(?type), "PostOffice") ||
                    CONTAINS(STR(?type), "PoliceStation") ||
                    CONTAINS(STR(?type), "FireStation") ||
                    
                    # Commercial and retail
                    CONTAINS(STR(?type), "ShoppingCenter") ||
                    CONTAINS(STR(?type), "ShoppingMall") ||
                    CONTAINS(STR(?type), "Supermarket") ||
                    CONTAINS(STR(?type), "ConvenienceStore") ||
                    CONTAINS(STR(?type), "Restaurant") ||
                    CONTAINS(STR(?type), "FastFoodRestaurant") ||
                    CONTAINS(STR(?type), "Cafe") ||
                    CONTAINS(STR(?type), "Bank") ||
                    CONTAINS(STR(?type), "Pharmacy") ||
                    CONTAINS(STR(?type), "GasStation") ||
                    CONTAINS(STR(?type), "FuelStation") ||
                    
                    # Residential
                    CONTAINS(STR(?type), "ApartmentBuilding") ||
                    CONTAINS(STR(?type), "ResidentialBuilding") ||
                    CONTAINS(STR(?type), "House") ||
                    CONTAINS(STR(?type), "OfficeBuilding") ||
                    
                    # Recreation
                    CONTAINS(STR(?type), "Park") ||
                    CONTAINS(STR(?type), "Gym") ||
                    CONTAINS(STR(?type), "SportsCenter") ||
                    CONTAINS(STR(?type), "Theater") ||
                    CONTAINS(STR(?type), "Cinema") ||
                    CONTAINS(STR(?type), "Museum") ||
                    
                    # Services
                    CONTAINS(STR(?type), "Hotel") ||
                    CONTAINS(STR(?type), "Motel") ||
                    CONTAINS(STR(?type), "ParkingFacility") ||
                    CONTAINS(STR(?type), "ParkingGarage")
                ) &&
                # Explicitly exclude infrastructure that's not useful for POI resolution
                !CONTAINS(STR(?type), "PedestrianCrossing") &&
                !CONTAINS(STR(?type), "TrafficSignal") &&
                !CONTAINS(STR(?type), "StreetLight") &&
                !CONTAINS(STR(?type), "StreetLamp") &&
                !CONTAINS(STR(?type), "BenchStreetFurniture") &&
                !CONTAINS(STR(?type), "Hydrant") &&
                !CONTAINS(STR(?type), "BicycleRack") &&
                !CONTAINS(STR(?type), "Sidewalk") &&
                !CONTAINS(STR(?type), "BicycleLane") &&
                !CONTAINS(STR(?type), "Footpath") &&
                !CONTAINS(STR(?type), "Path") &&
                !CONTAINS(STR(?type), "Footway") &&
                !CONTAINS(STR(?type), "Cycleway") &&
                !CONTAINS(STR(?type), "Steps") &&
                !CONTAINS(STR(?type), "Road") &&
                !CONTAINS(STR(?type), "Street") &&
                !CONTAINS(STR(?type), "Motorway") &&
                !CONTAINS(STR(?type), "Highway")
            )
        }
        """
        
        results = self.graph.query(query)
        
        duplicate_count = 0
        
        for row in results:
            # Extract readable name - handle the pattern from osm_handler.py
            if row.name:
                name = str(row.name)
            else:
                name = self._extract_name_from_uri(str(row.poi))
            
            # Skip entities with generic generated names (they lack real OSM names)
            # These are entities created by osm_handler when no name tag exists
            if self._is_generated_name(name):
                continue
            
            # Get coordinates with full precision first
            lat = float(row.lat)
            lon = float(row.lon)
            
            # Round to 5 decimal places (~1m precision) for deduplication
            lat_rounded = round(lat, 5)
            lon_rounded = round(lon, 5)
            
            # Create composite key: name + rounded location
            location_key = (name, lat_rounded, lon_rounded)
            
            # Skip if we've already seen this exact POI
            if location_key in seen_locations:
                duplicate_count += 1
                continue
            
            seen_locations.add(location_key)
            
            # Store with ROUNDED coordinates to ensure consistency
            pois.append({
                'uri': str(row.poi),
                'name': name,
                'type': str(row.type),
                'lat': lat_rounded,  # Use rounded value
                'lon': lon_rounded   # Use rounded value
            })
        
        # Report duplicate statistics
        if duplicate_count > 0:
            print(f"  Removed {duplicate_count} duplicate POIs (OSM way/area pairs)")
        
        return pois
    
    def _is_generated_name(self, name: str) -> bool:
        """Check if name is auto-generated (no real OSM name tag)"""
        # Pattern from osm_handler: f"{str(uko_class).split('/')[-1]} {osm_object.id}"
        # Examples: "Hospital 12345", "School 67890", "Restaurant 111"
        
        # Split into parts
        parts = name.split()
        if len(parts) < 2:
            return False
        
        # Check if last part is a number (the OSM ID)
        try:
            int(parts[-1])
            # If we can convert last part to int, it's likely generated
            # But allow some exceptions
            entity_type = parts[0]
            
            # These types commonly don't have names in OSM, so keep them
            keep_types = {'BusStop', 'Platform', 'ParkingFacility', 'ParkingGarage'}
            if entity_type in keep_types:
                return False
            
            # Everything else with pattern "Type 12345" is generated, skip it
            return True
        except ValueError:
            # Last part is not a number, so it's a real name
            return False
    
    def _extract_name_from_uri(self, uri: str) -> str:
        """Extract a readable name from a URI"""
        # Remove namespace prefix
        name = uri.split('/')[-1]
        
        # Handle different URI patterns
        if ' ' in name:
            # Format: "EntityType 123456"
            parts = name.split()
            if len(parts) > 1:
                # Return entity type + ID
                return f"{parts[0]} #{parts[1]}"
        
        # Default: just return the last part
        return name
    
    def _spatial_search(self, lat: float, lon: float, radius: float) -> List[Dict]:
        """
        Find POIs within radius of coordinates
        
        Args:
            lat: Latitude
            lon: Longitude
            radius: Search radius in meters
            
        Returns:
            List of POIs with distance calculated
        """
        nearby = []
        
        for poi in self.spatial_index:
            distance = self._haversine_distance(lat, lon, poi['lat'], poi['lon'])
            
            if distance <= radius:
                poi_with_distance = poi.copy()
                poi_with_distance['distance'] = distance
                nearby.append(poi_with_distance)
        
        # Sort by distance
        nearby.sort(key=lambda x: x['distance'])
        
        return nearby
    
    def _distance_confidence(self, distance_meters: float) -> float:
        """
        Calculate confidence score based on distance
        Uses exponential decay: conf = e^(-distance/scale)
        
        Scale adjusted for mobile GPS accuracy (typically 10-50m error)
        """
        # Scale parameter: distance at which confidence = 0.37
        # Increased from 50m to 100m to account for GPS inaccuracy
        scale = 100.0  # meters
        
        confidence = np.exp(-distance_meters / scale)
        return min(1.0, confidence)
    
    def _create_location_context_embedding(self, lat: float, lon: float, 
                                          radius: float = 150.0) -> Optional[np.ndarray]:
        """
        Create a semantic embedding for a location by averaging embeddings
        of nearby POIs. This creates a 'semantic fingerprint' of the area.
        
        Args:
            lat: Latitude
            lon: Longitude  
            radius: Radius to search for context POIs (meters)
            
        Returns:
            Average embedding representing the location context, or None
        """
        if self.embeddings is None:
            return None
        
        # Find POIs within radius
        nearby_pois = self._spatial_search(lat, lon, radius)
        
        if not nearby_pois:
            return None
        
        # Collect embeddings for POIs that have them
        context_embeddings = []
        for poi in nearby_pois:
            if poi['uri'] in self.embeddings:
                context_embeddings.append(self.embeddings[poi['uri']])
        
        if not context_embeddings:
            return None
        
        # Average the embeddings to create location context
        context_embedding = np.mean(context_embeddings, axis=0)
        
        # Normalize to unit vector
        norm = np.linalg.norm(context_embedding)
        if norm > 0:
            context_embedding = context_embedding / norm
        
        return context_embedding
    
    def _embedding_similarity(self, poi_uri: str, reference_embedding: np.ndarray) -> Optional[float]:
        """Calculate cosine similarity between POI and reference embedding"""
        if self.embeddings is None or poi_uri not in self.embeddings:
            return None
        
        poi_embedding = self.embeddings[poi_uri]
        
        # Cosine similarity
        dot_product = np.dot(poi_embedding, reference_embedding)
        norm_poi = np.linalg.norm(poi_embedding)
        norm_ref = np.linalg.norm(reference_embedding)
        
        if norm_poi == 0 or norm_ref == 0:
            return None
        
        similarity = dot_product / (norm_poi * norm_ref)
        
        # Normalize to [0, 1]
        return (similarity + 1) / 2
    
    def _contextual_matching(self, poi: Dict, context: Dict) -> float:
        """
        Boost confidence based on contextual factors
        
        Context keys:
        - time_of_day: 'morning', 'afternoon', 'evening', 'night'
        - day_of_week: 'weekday', 'weekend'
        - trip_purpose: 'commute', 'shopping', 'dining', etc.
        - modality: 'walking', 'driving', 'transit'
        """
        boost = 1.0
        poi_type = poi['type'].split(':')[-1]
        
        # Time of day matching
        time_of_day = context.get('time_of_day')
        if time_of_day:
            if time_of_day == 'morning' and poi_type in ['Cafe', 'Bakery', 'School']:
                boost *= 1.2
            elif time_of_day == 'afternoon' and poi_type in ['Restaurant', 'Park', 'ShoppingCenter']:
                boost *= 1.2
            elif time_of_day == 'evening' and poi_type in ['Restaurant', 'Bar', 'Theater', 'Cinema']:
                boost *= 1.2
        
        # Day of week matching
        day_of_week = context.get('day_of_week')
        if day_of_week:
            if day_of_week == 'weekday' and poi_type in ['School', 'University', 'OfficeBuilding']:
                boost *= 1.3
            elif day_of_week == 'weekend' and poi_type in ['Park', 'ShoppingMall', 'Theater']:
                boost *= 1.2
        
        # Trip purpose matching
        trip_purpose = context.get('trip_purpose')
        if trip_purpose:
            purpose_poi_match = {
                'commute': ['OfficeBuilding', 'School', 'University', 'TransitStation'],
                'shopping': ['ShoppingCenter', 'Supermarket', 'Store'],
                'dining': ['Restaurant', 'Cafe', 'FastFoodRestaurant'],
                'healthcare': ['Hospital', 'Clinic', 'DoctorsOffice', 'Pharmacy'],
                'recreation': ['Park', 'Gym', 'SportsCenter', 'Theater']
            }
            
            if poi_type in purpose_poi_match.get(trip_purpose, []):
                boost *= 1.5
        
        # Modality matching
        modality = context.get('modality')
        if modality:
            if modality == 'walking' and poi_type in ['Cafe', 'Park', 'Store']:
                boost *= 1.1
            elif modality == 'transit' and poi_type in ['TransitStation', 'BusStop']:
                boost *= 1.5
            elif modality == 'driving' and poi_type in ['ShoppingCenter', 'Parking']:
                boost *= 1.2
        
        return min(boost, 2.0)  # Cap boost at 2x
    
    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in meters between two coordinates"""
        R = 6371000  # Earth radius in meters
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c
    
    def get_poi_details(self, poi_uri: str) -> Optional[Dict]:
        """Get detailed information about a POI from the knowledge graph"""
        query = f"""
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?prop ?value
        WHERE {{
            <{poi_uri}> ?prop ?value .
        }}
        """
        
        results = self.graph.query(query)
        
        details = {'uri': poi_uri}
        for row in results:
            prop = str(row.prop).split('#')[-1].split('/')[-1]
            value = str(row.value)
            details[prop] = value
        
        return details if len(details) > 1 else None
    
    def find_intermediate_stops(self,
                           segments: List[Dict],
                           min_dwell_time: float = 60.0) -> List[Tuple[float, float, float, List[POICandidate]]]:
        """
        Detect intermediate stops based on dwell time
    
        Args:  
        segments: List of trip segments with timestamps
        min_dwell_time: Minimum dwell time in seconds to consider as stop
        
        Returns:
        List of (lat, lon, dwell_time, poi_candidates) for each stop
        """
        stops = []
    
        for i in range(len(segments) - 1):
            curr_seg = segments[i]
            next_seg = segments[i + 1]
        
            # Handle both naming conventions
            curr_end_lat = curr_seg.get('end_lat') or curr_seg.get('destination_lat')
            curr_end_lon = curr_seg.get('end_lon') or curr_seg.get('destination_long')
            next_start_lat = next_seg.get('start_lat') or next_seg.get('origin_lat')
            next_start_lon = next_seg.get('start_lon') or next_seg.get('origin_long')
        
            if not all([curr_end_lat, curr_end_lon, next_start_lat, next_start_lon]):
                continue
        
            # Check if end of current segment and start of next are same location
            lat_diff = abs(curr_end_lat - next_start_lat)
            lon_diff = abs(curr_end_lon - next_start_lon)
        
            if lat_diff < 0.0001 and lon_diff < 0.0001:  # ~10m threshold
                # Calculate dwell time
                curr_end_time = curr_seg.get('end_time')
                next_start_time = next_seg.get('start_time')
            
                # Handle both datetime objects and timestamp strings
                if isinstance(curr_end_time, str):
                    from datetime import datetime
                    curr_end_time = datetime.fromisoformat(curr_end_time)
                if isinstance(next_start_time, str):
                    from datetime import datetime
                    next_start_time = datetime.fromisoformat(next_start_time)
            
                if curr_end_time and next_start_time:
                    dwell = (next_start_time - curr_end_time).total_seconds()
                
                    if dwell >= min_dwell_time:
                        # Resolve POI for this stop
                        candidates = self.resolve_location(
                            curr_end_lat,
                            curr_end_lon,
                            max_candidates=3
                        )
                    
                        stops.append((
                            curr_end_lat,
                            curr_end_lon,
                            dwell,
                            candidates
                        ))
        return stops
    
    def batch_resolve(self, locations: List[Tuple[float, float]], 
                     context: Optional[Dict] = None) -> List[List[POICandidate]]:
        """
        Batch resolve multiple locations
        More efficient than calling resolve_location repeatedly
        """
        results = []
        
        for lat, lon in locations:
            candidates = self.resolve_location(lat, lon, context)
            results.append(candidates)
        
        return results
    
    def get_poi_type_statistics(self) -> Dict[str, int]:
        """Get statistics about POI types in the spatial index"""
        type_counts = {}
        
        for poi in self.spatial_index:
            poi_type = poi['type'].split(':')[-1]
            type_counts[poi_type] = type_counts.get(poi_type, 0) + 1
        
        # Sort by count descending
        return dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True))
    
    def get_area_coverage(self, lat: float, lon: float, radius: float = 1000) -> Dict:
        """Get statistics about POIs in an area"""
        nearby = self._spatial_search(lat, lon, radius)
        
        type_counts = {}
        for poi in nearby:
            poi_type = poi['type'].split(':')[-1]
            type_counts[poi_type] = type_counts.get(poi_type, 0) + 1
        
        return {
            'total_pois': len(nearby),
            'type_distribution': dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True)),
            'search_radius_m': radius,
            'center': (lat, lon)
        }


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python POI_resolver.py <kg_file> [embeddings_file]")
        sys.exit(1)
    
    kg_file = sys.argv[1]
    embeddings_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    # For testing, use the actual embeddings path if not provided
    if embeddings_file is None:
        # Try default location
        default_path = "../contra-costa-kg-project/embedding_training_data/entity_embeddings.csv"
        if os.path.exists(default_path):
            embeddings_file = default_path
            print(f"Using default embeddings: {embeddings_file}")
    
    # Initialize resolver
    resolver = POIResolver(kg_file, embeddings_file)
    
    # Show POI type statistics
    print("\n" + "="*60)
    print("POI TYPE STATISTICS")
    print("="*60)
    type_stats = resolver.get_poi_type_statistics()
    print(f"Total POI types: {len(type_stats)}")
    print(f"\nTop 20 most common POI types:")
    for poi_type, count in list(type_stats.items())[:20]:
        print(f"  {poi_type}: {count:,}")
    
    # Test with example coordinates (Walnut Creek area)
    test_locations = [
        (37.9101, -122.0652, "Downtown Walnut Creek"),
        (37.9298, -122.0574, "Pleasant Hill BART"),
        (38.0185, -121.8058, "Downtown Antioch")
    ]
    
    print("\n" + "="*60)
    print("TESTING POI RESOLUTION")
    print("="*60)
    
    for lat, lon, description in test_locations:
        print(f"\n--- Testing: {description} ---")
        print(f"Coordinates: ({lat}, {lon})")
        
        # Show area coverage
        coverage = resolver.get_area_coverage(lat, lon, radius=500)
        print(f"\nArea coverage (500m radius):")
        print(f"  Total POIs: {coverage['total_pois']}")
        if coverage['type_distribution']:
            print(f"  Top types:")
            for poi_type, count in list(coverage['type_distribution'].items())[:5]:
                print(f"    - {poi_type}: {count}")
        
        # Resolve location
        candidates = resolver.resolve_location(
            lat, lon,
            context={
                'time_of_day': 'morning',
                'day_of_week': 'weekday'
            },
            max_candidates=5,
            min_confidence=0.10,  # Adjusted for mobile GPS accuracy and sparse areas
            debug=True  # Enable debug output
        )
        
        if candidates:
            print(f"\nFound {len(candidates)} candidates:")
            for i, candidate in enumerate(candidates, 1):
                print(f"\n{i}. {candidate.name}")
                print(f"   Type: {candidate.poi_type.split(':')[-1]}")
                print(f"   Distance: {candidate.distance_meters:.1f}m")
                print(f"   Confidence: {candidate.confidence:.3f}")
        else:
            print("\nNo candidates found")
    
    print("\n" + "="*60)