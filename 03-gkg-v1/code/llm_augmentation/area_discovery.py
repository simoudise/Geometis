"""
Area Discovery Module for LLM-Augmented Knowledge Graphs

Discovers and validates:
- Informal neighborhoods
- Functional districts (design districts, auto rows, etc.)
- Ethnic enclaves
- Entertainment/nightlife areas

Uses a hybrid approach combining:
- LLM knowledge (top-down)
- POI clustering analysis (bottom-up)
- Web search verification

Copyright (c) 2025 Synapse Partners, LLC
"""

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set, Any
from enum import Enum
from datetime import datetime
import math
from collections import defaultdict

from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, XSD

# Import from core module
from .core import (
    LLMProvider, 
    AnthropicProvider,
    GeocodingService,
    NominatimGeocoder,
    DataSource,
    ConfidenceLevel,
    SourceEvidence,
    CandidateTriple
)

# Namespaces
UKO = Namespace("urn:urban-kg:")
UKO_ENTITY = Namespace("urn:urban-kg:entity/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class AreaType(Enum):
    """Types of discoverable areas."""
    NEIGHBORHOOD_OFFICIAL = "official_neighborhood"
    NEIGHBORHOOD_INFORMAL = "informal_neighborhood"
    NEIGHBORHOOD_HISTORIC = "historic_neighborhood"
    DISTRICT_FUNCTIONAL = "functional_district"
    DISTRICT_ETHNIC = "ethnic_enclave"
    DISTRICT_ENTERTAINMENT = "entertainment_district"
    DISTRICT_COMMERCIAL = "commercial_district"
    DOWNTOWN = "downtown"


@dataclass
class CandidateArea:
    """Represents a discovered neighborhood or district."""
    name: str
    area_type: AreaType
    city: str
    state: str
    
    # Classification
    uko_class: str = ""
    subtype: str = ""  # e.g., "design_district", "chinatown"
    
    # Boundaries
    boundary_description: str = ""
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    boundary_wkt: Optional[str] = None
    boundary_confidence: float = 0.5
    
    # Characteristics
    dominant_function: Optional[str] = None
    character_description: str = ""
    characteristic_poi_types: List[str] = field(default_factory=list)
    
    # Official status
    is_official: bool = False
    recognized_by: Optional[str] = None
    designation_date: Optional[str] = None
    
    # Provenance
    discovery_method: str = ""  # "llm_query", "poi_clustering", "osm", "web_search"
    confidence: float = 0.5
    evidence: List[SourceEvidence] = field(default_factory=list)
    verification_status: str = "unverified"  # "verified", "unverified", "disputed"
    
    # Alternative names
    informal_names: List[str] = field(default_factory=list)
    historic_names: List[str] = field(default_factory=list)
    
    def to_uri(self) -> str:
        """Generate URI for this area."""
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', self.name.lower())
        safe_city = re.sub(r'[^a-zA-Z0-9_]', '_', self.city.lower())
        area_type = self.area_type.value.split('_')[0]
        return f"urn:urban-kg:entity/{area_type}/{safe_city}_{safe_name}"


@dataclass
class POICluster:
    """Represents a cluster of similar POIs that may indicate a functional district."""
    poi_type: str
    poi_count: int
    centroid_lat: float
    centroid_lon: float
    radius_meters: float
    member_uris: List[str]
    density_score: float  # POIs per square km
    cluster_strength: float  # Statistical significance


# ============================================================================
# FUNCTIONAL DISTRICT TYPE MAPPINGS
# ============================================================================

FUNCTIONAL_DISTRICT_TYPES = {
    # POI types that characterize each district type
    "design_district": {
        "uko_class": "DesignDistrict",
        "poi_types": ["architect", "interior_design", "furniture", "kitchen", "lighting", 
                      "flooring", "tile", "bathroom", "home_improvement"],
        "min_pois": 5,
        "radius_m": 500
    },
    "auto_row": {
        "uko_class": "AutoRow",
        "poi_types": ["car_dealer", "car_dealership", "car_repair", "auto_parts", 
                      "car_wash", "motorcycle"],
        "min_pois": 4,
        "radius_m": 1000
    },
    "restaurant_row": {
        "uko_class": "RestaurantRow",
        "poi_types": ["restaurant", "cafe", "bar", "fast_food"],
        "min_pois": 8,
        "radius_m": 300
    },
    "art_district": {
        "uko_class": "ArtDistrict",
        "poi_types": ["gallery", "art", "museum", "studio", "theater", "performing_arts"],
        "min_pois": 5,
        "radius_m": 500
    },
    "entertainment_district": {
        "uko_class": "EntertainmentDistrict",
        "poi_types": ["nightclub", "bar", "theater", "cinema", "concert_hall", 
                      "music_venue", "comedy_club"],
        "min_pois": 6,
        "radius_m": 500
    },
    "medical_district": {
        "uko_class": "MedicalDistrict",
        "poi_types": ["hospital", "clinic", "doctor", "medical", "pharmacy", 
                      "laboratory", "urgent_care"],
        "min_pois": 5,
        "radius_m": 800
    },
    "tech_corridor": {
        "uko_class": "TechCorridor",
        "poi_types": ["office", "coworking", "startup", "tech", "software", "research"],
        "min_pois": 10,
        "radius_m": 1000
    },
    "shopping_district": {
        "uko_class": "ShoppingDistrict",
        "poi_types": ["shop", "retail", "boutique", "department_store", "mall"],
        "min_pois": 10,
        "radius_m": 400
    },
    "financial_district": {
        "uko_class": "FinancialDistrict",
        "poi_types": ["bank", "financial", "investment", "insurance", "accounting"],
        "min_pois": 6,
        "radius_m": 500
    },
}

ETHNIC_ENCLAVE_TYPES = {
    "chinatown": {"uko_class": "Chinatown", "indicators": ["chinese", "asian", "dim_sum", "noodle"]},
    "little_italy": {"uko_class": "LittleItaly", "indicators": ["italian", "pizza", "pasta", "trattoria"]},
    "koreatown": {"uko_class": "Koreatown", "indicators": ["korean", "bbq", "karaoke"]},
    "little_tokyo": {"uko_class": "LittleTokyo", "indicators": ["japanese", "sushi", "ramen"]},
    "latin_quarter": {"uko_class": "LatinQuarter", "indicators": ["mexican", "latino", "taqueria"]},
}


# ============================================================================
# NEIGHBORHOOD DISCOVERER
# ============================================================================

class NeighborhoodDiscoverer:
    """
    Discovers neighborhoods using LLM knowledge and verification.
    
    Workflow:
    1. Query LLM for known neighborhoods in a city
    2. Parse responses for names, boundaries, characteristics
    3. Geocode approximate boundaries
    4. Verify via web search
    5. Generate candidate areas with confidence scores
    """
    
    def __init__(self, llm: LLMProvider, geocoder: GeocodingService):
        self.llm = llm
        self.geocoder = geocoder
    
    async def discover_neighborhoods(
        self, 
        city: str, 
        state: str,
        include_informal: bool = True
    ) -> List[CandidateArea]:
        """
        Query LLM for neighborhood knowledge.
        
        Args:
            city: City name
            state: State code (e.g., "CA")
            include_informal: Whether to include informal neighborhoods
            
        Returns:
            List of candidate neighborhoods
        """
        prompt = self._build_neighborhood_prompt(city, state, include_informal)
        
        try:
            response = await self.llm.complete(prompt)
            neighborhoods = self._parse_neighborhood_response(response, city, state)
            
            # Geocode each neighborhood
            for neighborhood in neighborhoods:
                await self._geocode_neighborhood(neighborhood)
            
            return neighborhoods
            
        except Exception as e:
            print(f"Error discovering neighborhoods: {e}")
            return []
    
    def _build_neighborhood_prompt(self, city: str, state: str, include_informal: bool) -> str:
        """Build the LLM prompt for neighborhood discovery."""
        informal_instruction = """
Also include informal neighborhoods that locals recognize but may not be 
officially designated. These are areas with distinct identities that residents 
commonly refer to by name.
""" if include_informal else ""
        
        return f"""List all the neighborhoods in {city}, {state}.

For each neighborhood, provide:
1. Name (official name)
2. Type: "official" (government-designated), "informal" (community-recognized), or "historic"
3. Approximate boundaries (use street names, landmarks, or compass directions)
4. Character: residential, commercial, mixed-use, industrial, etc.
5. Any informal or alternative names locals use
6. Notable characteristics or what it's known for

{informal_instruction}

Format your response as a JSON array:
```json
[
  {{
    "name": "Neighborhood Name",
    "type": "official|informal|historic",
    "boundaries": "Description of boundaries using streets and landmarks",
    "character": "residential|commercial|mixed-use|industrial",
    "informal_names": ["nickname1", "nickname2"],
    "characteristics": "What this neighborhood is known for",
    "recognized_by": "City Planning Department" // only for official neighborhoods
  }}
]
```

Be comprehensive but accurate. Only include neighborhoods you're confident exist.
"""
    
    def _parse_neighborhood_response(
        self, 
        response: str, 
        city: str, 
        state: str
    ) -> List[CandidateArea]:
        """Parse LLM response into CandidateArea objects."""
        neighborhoods = []
        
        # Extract JSON from response
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find JSON array directly
            json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', response)
            if json_match:
                json_str = json_match.group(0)
            else:
                return neighborhoods
        
        try:
            data = json.loads(json_str)
            
            for item in data:
                area_type = self._map_neighborhood_type(item.get('type', 'informal'))
                
                neighborhood = CandidateArea(
                    name=item.get('name', ''),
                    area_type=area_type,
                    city=city,
                    state=state,
                    uko_class=self._get_uko_class_for_type(area_type),
                    boundary_description=item.get('boundaries', ''),
                    character_description=item.get('characteristics', ''),
                    is_official=(item.get('type') == 'official'),
                    recognized_by=item.get('recognized_by'),
                    discovery_method='llm_query',
                    confidence=0.7 if item.get('type') == 'official' else 0.6,
                    informal_names=item.get('informal_names', []),
                    evidence=[SourceEvidence(
                        source=DataSource.LLM_INFERENCE,
                        timestamp=datetime.now(),
                        extraction_method='neighborhood_discovery'
                    )]
                )
                
                # Set character
                character = item.get('character', '')
                if character:
                    neighborhood.dominant_function = character
                
                neighborhoods.append(neighborhood)
                
        except json.JSONDecodeError as e:
            print(f"Error parsing neighborhood JSON: {e}")
        
        return neighborhoods
    
    def _map_neighborhood_type(self, type_str: str) -> AreaType:
        """Map string type to AreaType enum."""
        type_map = {
            'official': AreaType.NEIGHBORHOOD_OFFICIAL,
            'informal': AreaType.NEIGHBORHOOD_INFORMAL,
            'historic': AreaType.NEIGHBORHOOD_HISTORIC,
        }
        return type_map.get(type_str.lower(), AreaType.NEIGHBORHOOD_INFORMAL)
    
    def _get_uko_class_for_type(self, area_type: AreaType) -> str:
        """Get UKO class name for area type."""
        class_map = {
            AreaType.NEIGHBORHOOD_OFFICIAL: 'OfficialNeighborhood',
            AreaType.NEIGHBORHOOD_INFORMAL: 'InformalNeighborhood',
            AreaType.NEIGHBORHOOD_HISTORIC: 'HistoricNeighborhood',
        }
        return class_map.get(area_type, 'Neighborhood')
    
    async def _geocode_neighborhood(self, neighborhood: CandidateArea):
        """Geocode the neighborhood to get centroid coordinates."""
        query = f"{neighborhood.name}, {neighborhood.city}, {neighborhood.state}"
        
        try:
            result = await self.geocoder.geocode(query)
            if result:
                neighborhood.centroid_lat = result.get('lat')
                neighborhood.centroid_lon = result.get('lon')
                neighborhood.boundary_confidence = 0.6
                
                # If we got a bounding box, create approximate WKT
                if 'boundingbox' in result:
                    bbox = result['boundingbox']
                    neighborhood.boundary_wkt = self._bbox_to_wkt(bbox)
                    neighborhood.boundary_confidence = 0.7
                    
        except Exception as e:
            print(f"Error geocoding {neighborhood.name}: {e}")
    
    def _bbox_to_wkt(self, bbox: List[str]) -> str:
        """Convert bounding box to WKT polygon."""
        lat_min, lat_max, lon_min, lon_max = [float(x) for x in bbox]
        return f"POLYGON(({lon_min} {lat_min}, {lon_max} {lat_min}, {lon_max} {lat_max}, {lon_min} {lat_max}, {lon_min} {lat_min}))"
    
    async def verify_neighborhood(
        self, 
        neighborhood: CandidateArea,
        web_search_func: Optional[callable] = None
    ) -> float:
        """
        Verify neighborhood existence via web search.
        
        Returns updated confidence score.
        """
        if not web_search_func:
            return neighborhood.confidence
        
        # Search for neighborhood mentions
        queries = [
            f"{neighborhood.name} neighborhood {neighborhood.city}",
            f"{neighborhood.name} {neighborhood.city} real estate",
        ]
        
        mention_count = 0
        sources = []
        
        for query in queries:
            try:
                results = await web_search_func(query)
                if results:
                    mention_count += len(results)
                    sources.extend([r.get('url', '') for r in results[:3]])
            except:
                continue
        
        # Update confidence based on mentions
        if mention_count >= 5:
            neighborhood.confidence = min(0.9, neighborhood.confidence + 0.2)
            neighborhood.verification_status = "verified"
        elif mention_count >= 2:
            neighborhood.confidence = min(0.8, neighborhood.confidence + 0.1)
            neighborhood.verification_status = "verified"
        
        # Add evidence
        for url in sources[:3]:
            if url:
                neighborhood.evidence.append(SourceEvidence(
                    source=DataSource.LLM_WEB_SEARCH,
                    url=url,
                    timestamp=datetime.now(),
                    extraction_method='web_verification'
                ))
        
        return neighborhood.confidence


# ============================================================================
# FUNCTIONAL DISTRICT DISCOVERER
# ============================================================================

class FunctionalDistrictDiscoverer:
    """
    Discovers functional districts using both:
    - Top-down: LLM knowledge of known districts
    - Bottom-up: POI clustering analysis
    """
    
    def __init__(self, llm: LLMProvider, geocoder: GeocodingService):
        self.llm = llm
        self.geocoder = geocoder
    
    async def discover_from_llm(
        self, 
        city: str, 
        state: str
    ) -> List[CandidateArea]:
        """Query LLM for known functional districts."""
        prompt = self._build_district_prompt(city, state)
        
        try:
            response = await self.llm.complete(prompt)
            return self._parse_district_response(response, city, state)
        except Exception as e:
            print(f"Error discovering districts: {e}")
            return []
    
    def _build_district_prompt(self, city: str, state: str) -> str:
        """Build prompt for functional district discovery."""
        return f"""List any informal or functional districts in {city}, {state}.

These are areas known for concentrations of specific types of businesses or activities, such as:
- Design districts (architects, interior designers, furniture showrooms)
- Auto rows (car dealerships)
- Restaurant rows or food districts
- Art districts (galleries, studios)
- Entertainment/nightlife districts
- Medical districts
- Tech corridors
- Fashion districts
- Ethnic enclaves (Chinatown, Little Italy, Koreatown, etc.)

For each district, provide:
1. Name (what locals call it)
2. Type of district
3. Location/boundaries (streets, landmarks)
4. What makes it distinctive

Format as JSON:
```json
[
  {{
    "name": "District Name",
    "type": "design_district|auto_row|restaurant_row|art_district|entertainment_district|medical_district|tech_corridor|shopping_district|ethnic_enclave",
    "ethnic_type": "chinatown|little_italy|koreatown|etc",  // only for ethnic enclaves
    "location": "Description of location",
    "distinctive_features": "What it's known for",
    "approximate_streets": ["Main St", "Oak Ave"]
  }}
]
```

Only include districts you're confident actually exist. If {city} doesn't have notable functional districts, return an empty array.
"""
    
    def _parse_district_response(
        self, 
        response: str, 
        city: str, 
        state: str
    ) -> List[CandidateArea]:
        """Parse LLM response into candidate districts."""
        districts = []
        
        # Extract JSON
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', response)
            if json_match:
                json_str = json_match.group(0)
            else:
                return districts
        
        try:
            data = json.loads(json_str)
            
            for item in data:
                district_type = item.get('type', 'functional_district')
                
                # Determine area type and UKO class
                if district_type == 'ethnic_enclave':
                    area_type = AreaType.DISTRICT_ETHNIC
                    ethnic_type = item.get('ethnic_type', '')
                    uko_class = ETHNIC_ENCLAVE_TYPES.get(ethnic_type, {}).get('uko_class', 'EthnicEnclave')
                    subtype = ethnic_type
                elif district_type == 'entertainment_district':
                    area_type = AreaType.DISTRICT_ENTERTAINMENT
                    uko_class = 'EntertainmentDistrict'
                    subtype = district_type
                else:
                    area_type = AreaType.DISTRICT_FUNCTIONAL
                    uko_class = FUNCTIONAL_DISTRICT_TYPES.get(district_type, {}).get('uko_class', 'FunctionalDistrict')
                    subtype = district_type
                
                district = CandidateArea(
                    name=item.get('name', ''),
                    area_type=area_type,
                    city=city,
                    state=state,
                    uko_class=uko_class,
                    subtype=subtype,
                    boundary_description=item.get('location', ''),
                    character_description=item.get('distinctive_features', ''),
                    dominant_function=district_type,
                    discovery_method='llm_query',
                    confidence=0.65,
                    evidence=[SourceEvidence(
                        source=DataSource.LLM_INFERENCE,
                        timestamp=datetime.now(),
                        extraction_method='district_discovery'
                    )]
                )
                
                districts.append(district)
                
        except json.JSONDecodeError as e:
            print(f"Error parsing district JSON: {e}")
        
        return districts
    
    def detect_clusters_from_kg(
        self, 
        graph: Graph,
        city_uri: str,
        min_cluster_size: int = 4,
        search_radius_m: float = 500
    ) -> List[POICluster]:
        """
        Detect POI clusters from the knowledge graph that may indicate functional districts.
        
        This is the bottom-up approach using actual KG data.
        """
        clusters = []
        
        # Query POIs in the city with their types and coordinates
        query = f"""
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?poi ?type ?lat ?lon ?label
        WHERE {{
            ?poi uko:partOf <{city_uri}> .
            ?poi rdf:type ?type .
            ?poi uko:latitude ?lat .
            ?poi uko:longitude ?lon .
            OPTIONAL {{ ?poi rdfs:label ?label }}
        }}
        """
        
        # Group POIs by type
        pois_by_type = defaultdict(list)
        
        try:
            results = graph.query(query)
            for row in results:
                poi_type = str(row.type).split('/')[-1].split(':')[-1]
                pois_by_type[poi_type].append({
                    'uri': str(row.poi),
                    'lat': float(row.lat),
                    'lon': float(row.lon),
                    'label': str(row.label) if row.label else ''
                })
        except Exception as e:
            print(f"Error querying POIs: {e}")
            return clusters
        
        # For each district type, check if there's a qualifying cluster
        for district_type, config in FUNCTIONAL_DISTRICT_TYPES.items():
            relevant_pois = []
            
            for poi_type in config['poi_types']:
                # Fuzzy match POI types
                for kg_type, pois in pois_by_type.items():
                    if poi_type.lower() in kg_type.lower():
                        relevant_pois.extend(pois)
            
            if len(relevant_pois) < config['min_pois']:
                continue
            
            # Simple clustering: find dense regions
            cluster = self._find_densest_cluster(
                relevant_pois, 
                config['radius_m'],
                config['min_pois']
            )
            
            if cluster:
                cluster.poi_type = district_type
                clusters.append(cluster)
        
        return clusters
    
    def _find_densest_cluster(
        self, 
        pois: List[Dict],
        radius_m: float,
        min_count: int
    ) -> Optional[POICluster]:
        """Find the densest cluster of POIs within the given radius."""
        if len(pois) < min_count:
            return None
        
        best_cluster = None
        best_density = 0
        
        # For each POI, count neighbors within radius
        for poi in pois:
            neighbors = [poi]
            
            for other in pois:
                if other['uri'] == poi['uri']:
                    continue
                
                dist = self._haversine(
                    poi['lat'], poi['lon'],
                    other['lat'], other['lon']
                )
                
                if dist <= radius_m:
                    neighbors.append(other)
            
            if len(neighbors) >= min_count:
                # Calculate density (POIs per sq km)
                area_km2 = math.pi * (radius_m / 1000) ** 2
                density = len(neighbors) / area_km2
                
                if density > best_density:
                    best_density = density
                    
                    # Calculate centroid
                    avg_lat = sum(p['lat'] for p in neighbors) / len(neighbors)
                    avg_lon = sum(p['lon'] for p in neighbors) / len(neighbors)
                    
                    best_cluster = POICluster(
                        poi_type='',
                        poi_count=len(neighbors),
                        centroid_lat=avg_lat,
                        centroid_lon=avg_lon,
                        radius_meters=radius_m,
                        member_uris=[p['uri'] for p in neighbors],
                        density_score=density,
                        cluster_strength=len(neighbors) / min_count
                    )
        
        return best_cluster
    
    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in meters."""
        R = 6371000
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2)**2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2)
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c
    
    def reconcile_discoveries(
        self,
        llm_districts: List[CandidateArea],
        kg_clusters: List[POICluster]
    ) -> List[CandidateArea]:
        """
        Reconcile LLM-discovered districts with KG cluster analysis.
        
        - If LLM district matches a cluster: boost confidence
        - If cluster has no LLM match: create new candidate with lower confidence
        - If LLM district has no cluster: keep but note unverified
        """
        reconciled = []
        matched_clusters = set()
        
        for district in llm_districts:
            # Try to match with a cluster
            best_match = None
            best_distance = float('inf')
            
            for i, cluster in enumerate(kg_clusters):
                if district.subtype == cluster.poi_type:
                    if district.centroid_lat and district.centroid_lon:
                        dist = self._haversine(
                            district.centroid_lat, district.centroid_lon,
                            cluster.centroid_lat, cluster.centroid_lon
                        )
                        if dist < best_distance and dist < 1000:  # Within 1km
                            best_distance = dist
                            best_match = (i, cluster)
            
            if best_match:
                idx, cluster = best_match
                matched_clusters.add(idx)
                
                # Boost confidence and add cluster data
                district.confidence = min(0.9, district.confidence + 0.2)
                district.verification_status = "verified"
                district.centroid_lat = cluster.centroid_lat
                district.centroid_lon = cluster.centroid_lon
                
                # Add evidence
                district.evidence.append(SourceEvidence(
                    source=DataSource.COMPUTED,
                    timestamp=datetime.now(),
                    extraction_method=f'poi_cluster_match (n={cluster.poi_count}, density={cluster.density_score:.1f})'
                ))
            
            reconciled.append(district)
        
        # Create candidates for unmatched clusters
        for i, cluster in enumerate(kg_clusters):
            if i not in matched_clusters and cluster.cluster_strength > 1.5:
                # Strong cluster with no LLM match
                config = FUNCTIONAL_DISTRICT_TYPES.get(cluster.poi_type, {})
                
                candidate = CandidateArea(
                    name=f"Potential {cluster.poi_type.replace('_', ' ').title()}",
                    area_type=AreaType.DISTRICT_FUNCTIONAL,
                    city="",  # Will need to be filled in
                    state="",
                    uko_class=config.get('uko_class', 'FunctionalDistrict'),
                    subtype=cluster.poi_type,
                    centroid_lat=cluster.centroid_lat,
                    centroid_lon=cluster.centroid_lon,
                    dominant_function=cluster.poi_type,
                    discovery_method='poi_clustering',
                    confidence=0.5 * cluster.cluster_strength,  # Lower confidence
                    evidence=[SourceEvidence(
                        source=DataSource.COMPUTED,
                        timestamp=datetime.now(),
                        extraction_method=f'poi_clustering (n={cluster.poi_count}, density={cluster.density_score:.1f})'
                    )]
                )
                
                reconciled.append(candidate)
        
        return reconciled


# ============================================================================
# AREA DISCOVERY PIPELINE
# ============================================================================

class AreaDiscoveryPipeline:
    """
    Main pipeline for discovering neighborhoods and functional districts.
    
    Orchestrates:
    1. LLM-based neighborhood discovery
    2. LLM-based functional district discovery
    3. Bottom-up POI cluster analysis
    4. Reconciliation and verification
    5. Triple generation for KG integration
    """
    
    def __init__(
        self,
        llm: LLMProvider,
        geocoder: GeocodingService,
        graph: Optional[Graph] = None
    ):
        self.neighborhood_discoverer = NeighborhoodDiscoverer(llm, geocoder)
        self.district_discoverer = FunctionalDistrictDiscoverer(llm, geocoder)
        self.graph = graph
        self.geocoder = geocoder
    
    async def discover_areas(
        self,
        city: str,
        state: str,
        city_uri: Optional[str] = None,
        include_neighborhoods: bool = True,
        include_districts: bool = True,
        use_kg_clustering: bool = True
    ) -> Dict[str, List[CandidateArea]]:
        """
        Run full area discovery pipeline.
        
        Args:
            city: City name
            state: State code
            city_uri: URI of city in KG (for clustering)
            include_neighborhoods: Discover neighborhoods
            include_districts: Discover functional districts
            use_kg_clustering: Use bottom-up POI clustering
            
        Returns:
            Dictionary with 'neighborhoods' and 'districts' lists
        """
        results = {
            'neighborhoods': [],
            'districts': []
        }
        
        # Discover neighborhoods
        if include_neighborhoods:
            print(f"Discovering neighborhoods in {city}, {state}...")
            neighborhoods = await self.neighborhood_discoverer.discover_neighborhoods(
                city, state, include_informal=True
            )
            results['neighborhoods'] = neighborhoods
            print(f"  Found {len(neighborhoods)} neighborhoods")
        
        # Discover functional districts from LLM
        if include_districts:
            print(f"Discovering functional districts in {city}, {state}...")
            llm_districts = await self.district_discoverer.discover_from_llm(city, state)
            print(f"  LLM found {len(llm_districts)} districts")
            
            # Geocode districts
            for district in llm_districts:
                if not district.centroid_lat:
                    query = f"{district.name}, {city}, {state}"
                    try:
                        result = await self.geocoder.geocode(query)
                        if result:
                            district.centroid_lat = result.get('lat')
                            district.centroid_lon = result.get('lon')
                    except:
                        pass
            
            # Bottom-up clustering from KG
            kg_clusters = []
            if use_kg_clustering and self.graph and city_uri:
                print(f"  Analyzing POI clusters in knowledge graph...")
                kg_clusters = self.district_discoverer.detect_clusters_from_kg(
                    self.graph, city_uri
                )
                print(f"  Found {len(kg_clusters)} significant POI clusters")
            
            # Reconcile LLM and clustering results
            if kg_clusters:
                districts = self.district_discoverer.reconcile_discoveries(
                    llm_districts, kg_clusters
                )
            else:
                districts = llm_districts
            
            # Fill in city/state for cluster-only discoveries
            for d in districts:
                if not d.city:
                    d.city = city
                    d.state = state
            
            results['districts'] = districts
            print(f"  Final: {len(districts)} districts after reconciliation")
        
        return results
    
    def generate_triples(
        self,
        areas: Dict[str, List[CandidateArea]],
        city_uri: str
    ) -> List[CandidateTriple]:
        """
        Generate RDF triples for discovered areas.
        
        Returns CandidateTriple objects ready for verification pipeline.
        """
        triples = []
        
        all_areas = areas.get('neighborhoods', []) + areas.get('districts', [])
        
        for area in all_areas:
            area_uri = area.to_uri()
            
            # Type triple
            triples.append(CandidateTriple(
                subject=area_uri,
                predicate=str(RDF.type),
                object=f"urn:urban-kg:{area.uko_class}",
                confidence=area.confidence,
                evidence=area.evidence,
                verification_status=area.verification_status
            ))
            
            # Label
            triples.append(CandidateTriple(
                subject=area_uri,
                predicate=str(RDFS.label),
                object=area.name,
                confidence=area.confidence,
                evidence=area.evidence
            ))
            
            # Part of city
            triples.append(CandidateTriple(
                subject=area_uri,
                predicate="urn:urban-kg:partOf",
                object=city_uri,
                confidence=area.confidence,
                evidence=area.evidence
            ))
            
            # Coordinates
            if area.centroid_lat and area.centroid_lon:
                triples.append(CandidateTriple(
                    subject=area_uri,
                    predicate="urn:urban-kg:latitude",
                    object=str(area.centroid_lat),
                    confidence=area.boundary_confidence,
                    evidence=area.evidence
                ))
                triples.append(CandidateTriple(
                    subject=area_uri,
                    predicate="urn:urban-kg:longitude",
                    object=str(area.centroid_lon),
                    confidence=area.boundary_confidence,
                    evidence=area.evidence
                ))
            
            # Boundary WKT
            if area.boundary_wkt:
                triples.append(CandidateTriple(
                    subject=area_uri,
                    predicate="http://www.opengis.net/ont/geosparql#asWKT",
                    object=area.boundary_wkt,
                    confidence=area.boundary_confidence,
                    evidence=area.evidence
                ))
            
            # Official status (for neighborhoods)
            if area.area_type in [AreaType.NEIGHBORHOOD_OFFICIAL, AreaType.NEIGHBORHOOD_INFORMAL]:
                triples.append(CandidateTriple(
                    subject=area_uri,
                    predicate="urn:urban-kg:hasOfficialStatus",
                    object=str(area.is_official).lower(),
                    confidence=area.confidence,
                    evidence=area.evidence
                ))
            
            # Boundary source
            triples.append(CandidateTriple(
                subject=area_uri,
                predicate="urn:urban-kg:hasBoundarySource",
                object=area.discovery_method,
                confidence=1.0,
                evidence=area.evidence
            ))
            
            # Dominant function (for districts)
            if area.dominant_function:
                triples.append(CandidateTriple(
                    subject=area_uri,
                    predicate="urn:urban-kg:dominantFunction",
                    object=area.dominant_function,
                    confidence=area.confidence,
                    evidence=area.evidence
                ))
            
            # Boundary description
            if area.boundary_description:
                triples.append(CandidateTriple(
                    subject=area_uri,
                    predicate="urn:urban-kg:approximateBoundary",
                    object=area.boundary_description,
                    confidence=area.confidence,
                    evidence=area.evidence
                ))
            
            # Informal names
            for informal_name in area.informal_names:
                triples.append(CandidateTriple(
                    subject=area_uri,
                    predicate="urn:urban-kg:informalName",
                    object=informal_name,
                    confidence=area.confidence * 0.9,
                    evidence=area.evidence
                ))
            
            # Discovery method
            triples.append(CandidateTriple(
                subject=area_uri,
                predicate="urn:urban-kg:discoveryMethod",
                object=area.discovery_method,
                confidence=1.0,
                evidence=area.evidence
            ))
        
        return triples
    
    def save_results(
        self,
        areas: Dict[str, List[CandidateArea]],
        output_path: str
    ):
        """Save discovered areas to JSON file."""
        output = {
            'neighborhoods': [
                {
                    'name': a.name,
                    'type': a.area_type.value,
                    'uko_class': a.uko_class,
                    'city': a.city,
                    'state': a.state,
                    'centroid': [a.centroid_lat, a.centroid_lon] if a.centroid_lat else None,
                    'boundary_description': a.boundary_description,
                    'is_official': a.is_official,
                    'confidence': a.confidence,
                    'discovery_method': a.discovery_method,
                    'verification_status': a.verification_status,
                    'informal_names': a.informal_names
                }
                for a in areas.get('neighborhoods', [])
            ],
            'districts': [
                {
                    'name': a.name,
                    'type': a.area_type.value,
                    'uko_class': a.uko_class,
                    'subtype': a.subtype,
                    'city': a.city,
                    'state': a.state,
                    'centroid': [a.centroid_lat, a.centroid_lon] if a.centroid_lat else None,
                    'boundary_description': a.boundary_description,
                    'dominant_function': a.dominant_function,
                    'confidence': a.confidence,
                    'discovery_method': a.discovery_method,
                    'verification_status': a.verification_status
                }
                for a in areas.get('districts', [])
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"Results saved to {output_path}")


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

async def run_area_discovery(
    city: str,
    state: str,
    anthropic_api_key: Optional[str] = None,
    kg_path: Optional[str] = None,
    output_path: Optional[str] = None
) -> Dict[str, List[CandidateArea]]:
    """
    Convenience function to run area discovery.
    
    Args:
        city: City name
        state: State code (e.g., "CA")
        anthropic_api_key: API key for Claude (optional, uses env var if not provided)
        kg_path: Path to knowledge graph TTL file (optional, for clustering)
        output_path: Path to save JSON results (optional)
        
    Returns:
        Dictionary with 'neighborhoods' and 'districts' lists
    """
    # Initialize providers
    llm = AnthropicProvider(api_key=anthropic_api_key)
    geocoder = NominatimGeocoder()
    
    # Load KG if provided
    graph = None
    city_uri = None
    if kg_path:
        graph = Graph()
        graph.parse(kg_path, format='turtle')
        city_uri = f"urn:urban-kg:entity/osm/city/{city.replace(' ', '_')}"
    
    # Create pipeline
    pipeline = AreaDiscoveryPipeline(llm, geocoder, graph)
    
    # Run discovery
    results = await pipeline.discover_areas(
        city=city,
        state=state,
        city_uri=city_uri,
        include_neighborhoods=True,
        include_districts=True,
        use_kg_clustering=(graph is not None)
    )
    
    # Save results if output path provided
    if output_path:
        pipeline.save_results(results, output_path)
    
    return results


# ============================================================================
# CLI INTERFACE
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Discover neighborhoods and districts")
    parser.add_argument("--city", required=True, help="City name")
    parser.add_argument("--state", required=True, help="State code (e.g., CA)")
    parser.add_argument("--kg_path", help="Path to knowledge graph TTL file")
    parser.add_argument("--output", default="area_discovery_results.json", help="Output JSON path")
    parser.add_argument("--api_key", help="Anthropic API key")
    
    args = parser.parse_args()
    
    results = asyncio.run(run_area_discovery(
        city=args.city,
        state=args.state,
        anthropic_api_key=args.api_key,
        kg_path=args.kg_path,
        output_path=args.output
    ))
    
    print(f"\nDiscovered {len(results['neighborhoods'])} neighborhoods")
    print(f"Discovered {len(results['districts'])} functional districts")
