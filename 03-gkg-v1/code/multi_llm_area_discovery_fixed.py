"""
Multi-LLM Area Discovery Module

Queries multiple LLMs (Claude and Gemini) for neighborhood and district
knowledge, reconciles their responses, and integrates results into the
knowledge graph.

Benefits of multi-LLM approach:
- Better coverage (different training data)
- Built-in validation (agreement = higher confidence)
- Conflict detection (flags uncertain areas)

Prerequisites:
   pip install anthropic google-genai python-dotenv rdflib

Setup:
    Create a .env file with:
        ANTHROPIC_API_KEY=sk-ant-...
        GOOGLE_API_KEY=...

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from enum import Enum
from collections import defaultdict
import time

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# LLM clients
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("Warning: anthropic package not installed. Run: pip install anthropic")

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("Warning: google-genai package not installed. Run: pip install google-genai")

# RDF
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, XSD


# Namespaces
UKO = Namespace("urn:urban-kg:")
UKO_ENTITY = Namespace("urn:urban-kg:entity/")


class LLMSource(Enum):
    """Identifies which LLM provided the data."""
    CLAUDE = "claude"
    GEMINI = "gemini"
    BOTH = "both"  # Agreement between LLMs


class ConfidenceLevel(Enum):
    """Confidence based on LLM agreement."""
    HIGH = 0.9      # Both LLMs agree
    MEDIUM = 0.7    # Single LLM
    LOW = 0.5       # Conflict or uncertain
    CONFLICT = 0.3  # LLMs disagree


@dataclass
class DiscoveredArea:
    """Represents a neighborhood or district discovered by LLMs."""
    name: str
    area_type: str  # "neighborhood", "district", "ethnic_enclave", etc.
    city: str
    state: str
    
    # Classification
    subtype: Optional[str] = None  # e.g., "official", "informal", "auto_row"
    uko_class: str = "Neighborhood"
    
    # Details
    boundaries: Optional[str] = None
    characteristics: Optional[str] = None
    informal_names: List[str] = field(default_factory=list)
    
    # Provenance
    sources: Set[LLMSource] = field(default_factory=set)
    confidence: float = 0.7
    raw_responses: Dict[str, str] = field(default_factory=dict)
    
    # Geocoding (to be filled later)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    def __hash__(self):
        """Hash by normalized name and city for deduplication."""
        return hash((self._normalize(self.name), self._normalize(self.city)))
    
    def __eq__(self, other):
        """Equal if normalized names and cities match."""
        if not isinstance(other, DiscoveredArea):
            return False
        return (self._normalize(self.name) == self._normalize(other.name) and
                self._normalize(self.city) == self._normalize(other.city))
    
    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison."""
        return re.sub(r'[^a-z0-9]', '', text.lower())
    
    def to_uri(self) -> str:
        """Generate URI for this area."""
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', self.name.lower())
        safe_city = re.sub(r'[^a-zA-Z0-9_]', '_', self.city.lower())
        return f"urn:urban-kg:entity/{self.area_type}/{safe_city}_{safe_name}"


# =============================================================================
# LLM PROVIDERS
# =============================================================================

class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def query(self, prompt: str) -> str:
        """Send a prompt and get a response."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass
    
    @property
    @abstractmethod
    def source(self) -> LLMSource:
        """LLM source identifier."""
        pass


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider - Updated for 2025 models."""
    
    # UPDATED: Use claude-sonnet-4-5-20250929 (the current Sonnet 4.5 model)
    # Alternative: "claude-sonnet-4-5" (alias that points to latest)
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-5-20250929"):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic package not installed")
        
        self.api_key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
    
    def query(self, prompt: str) -> str:
        """Query Claude."""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except anthropic.NotFoundError as e:
            # If the specific model version isn't found, try the alias
            print(f"  Warning: Model {self.model} not found, trying alias...")
            self.model = "claude-sonnet-4-5"  # Try alias
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
    
    @property
    def name(self) -> str:
        return "Claude"
    
    @property
    def source(self) -> LLMSource:
        return LLMSource.CLAUDE


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider (Updated for google-genai SDK)."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash-exp"):
        try:
            from google import genai
        except ImportError:
            raise ImportError("google-genai package not installed. Run: pip install google-genai")
        
        self.api_key = (api_key or os.getenv("GOOGLE_API_KEY", "")).strip()
        
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model
    
    def query(self, prompt: str) -> str:
        """Query Gemini using the new SDK."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )
        return response.text

    @property
    def name(self) -> str:
        return "Gemini"
    
    @property
    def source(self) -> LLMSource:
        return LLMSource.GEMINI


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

NEIGHBORHOOD_PROMPT = """List all the neighborhoods in {city}, {state}.

For each neighborhood, provide:
1. Name (official name)
2. Type: "official" (government-designated), "informal" (community-recognized), or "historic"
3. Approximate boundaries (use street names, landmarks, or compass directions)
4. Character: residential, commercial, mixed-use, industrial, etc.
5. Any informal or alternative names locals use
6. Notable characteristics or what it's known for

Include both official neighborhoods and informal ones that locals recognize.

Format your response as a JSON array:
```json
[
  {{
    "name": "Neighborhood Name",
    "type": "official|informal|historic",
    "boundaries": "Description of boundaries",
    "character": "residential|commercial|mixed-use|industrial",
    "informal_names": ["nickname1", "nickname2"],
    "characteristics": "What this neighborhood is known for"
  }}
]
```

Be comprehensive but accurate. Only include neighborhoods you're confident exist.
If you're not sure about a neighborhood, don't include it.
"""

DISTRICT_PROMPT = """List any informal or functional districts in {city}, {state}.

These are areas known for concentrations of specific types of businesses or activities:
- Design districts (architects, interior designers, furniture showrooms)
- Auto rows (car dealerships along a street)
- Restaurant rows or food districts
- Art districts (galleries, studios)
- Entertainment/nightlife districts
- Medical districts (around hospitals)
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
    "type": "design_district|auto_row|restaurant_row|art_district|entertainment_district|medical_district|tech_corridor|ethnic_enclave|other",
    "ethnic_type": "chinatown|little_italy|koreatown|etc",
    "location": "Description of location",
    "distinctive_features": "What it's known for"
  }}
]
```

Only include districts you're confident actually exist.
If {city} doesn't have notable functional districts, return an empty array [].
"""


# =============================================================================
# RESPONSE PARSER
# =============================================================================

class ResponseParser:
    """Parses LLM responses into structured data."""
    
    @staticmethod
    def extract_json(response: str) -> Optional[List[Dict]]:
        """Extract JSON array from response text."""
        # Try to find JSON in code blocks
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON array
            json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', response)
            if json_match:
                json_str = json_match.group(0)
            else:
                # Try to find any JSON array, even empty
                json_match = re.search(r'\[\s*\]', response)
                if json_match:
                    return []
                return None
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"    Warning: JSON parse error: {e}")
            return None
    
    @staticmethod
    def parse_neighborhoods(response: str, city: str, state: str, 
                           source: LLMSource) -> List[DiscoveredArea]:
        """Parse neighborhood response into DiscoveredArea objects."""
        areas = []
        data = ResponseParser.extract_json(response)
        
        if not data:
            return areas
        
        for item in data:
            area_subtype = item.get('type', 'informal')
            
            # Map to UKO class
            uko_class_map = {
                'official': 'OfficialNeighborhood',
                'informal': 'InformalNeighborhood',
                'historic': 'HistoricNeighborhood'
            }
            
            area = DiscoveredArea(
                name=item.get('name', ''),
                area_type='neighborhood',
                city=city,
                state=state,
                subtype=area_subtype,
                uko_class=uko_class_map.get(area_subtype, 'Neighborhood'),
                boundaries=item.get('boundaries'),
                characteristics=item.get('characteristics'),
                informal_names=item.get('informal_names', []),
                sources={source},
                confidence=0.7,
                raw_responses={source.value: json.dumps(item)}
            )
            
            if area.name:  # Only add if name exists
                areas.append(area)
        
        return areas
    
    @staticmethod
    def parse_districts(response: str, city: str, state: str,
                       source: LLMSource) -> List[DiscoveredArea]:
        """Parse district response into DiscoveredArea objects."""
        areas = []
        data = ResponseParser.extract_json(response)
        
        if not data:
            return areas
        
        # Map district types to UKO classes
        uko_class_map = {
            'design_district': 'DesignDistrict',
            'auto_row': 'AutoRow',
            'restaurant_row': 'RestaurantRow',
            'art_district': 'ArtDistrict',
            'entertainment_district': 'EntertainmentDistrict',
            'medical_district': 'MedicalDistrict',
            'tech_corridor': 'TechCorridor',
            'ethnic_enclave': 'EthnicEnclave',
            'shopping_district': 'ShoppingDistrict',
            'financial_district': 'FinancialDistrict',
        }
        
        ethnic_class_map = {
            'chinatown': 'Chinatown',
            'little_italy': 'LittleItaly',
            'koreatown': 'Koreatown',
            'little_tokyo': 'LittleTokyo',
            'latin_quarter': 'LatinQuarter',
        }
        
        for item in data:
            district_type = item.get('type', 'other')
            ethnic_type = item.get('ethnic_type')
            
            # Determine UKO class
            if district_type == 'ethnic_enclave' and ethnic_type:
                uko_class = ethnic_class_map.get(ethnic_type, 'EthnicEnclave')
            else:
                uko_class = uko_class_map.get(district_type, 'FunctionalDistrict')
            
            area = DiscoveredArea(
                name=item.get('name', ''),
                area_type='district',
                city=city,
                state=state,
                subtype=district_type,
                uko_class=uko_class,
                boundaries=item.get('location'),
                characteristics=item.get('distinctive_features'),
                sources={source},
                confidence=0.7,
                raw_responses={source.value: json.dumps(item)}
            )
            
            if area.name:
                areas.append(area)
        
        return areas


# =============================================================================
# RECONCILER
# =============================================================================

class LLMReconciler:
    """Reconciles responses from multiple LLMs."""
    
    @staticmethod
    def reconcile(areas_by_source: Dict[LLMSource, List[DiscoveredArea]]) -> List[DiscoveredArea]:
        """
        Reconcile areas from multiple LLM sources.
        
        - Areas found by both LLMs: HIGH confidence
        - Areas found by one LLM: MEDIUM confidence
        - Conflicting information: flagged for review
        """
        # Index areas by normalized name+city
        all_areas: Dict[Tuple[str, str], List[DiscoveredArea]] = defaultdict(list)
        
        for source, areas in areas_by_source.items():
            for area in areas:
                key = (area._normalize(area.name), area._normalize(area.city))
                all_areas[key].append(area)
        
        # Reconcile
        reconciled = []
        
        for key, area_list in all_areas.items():
            if len(area_list) == 1:
                # Single source
                area = area_list[0]
                area.confidence = ConfidenceLevel.MEDIUM.value
                reconciled.append(area)
            else:
                # Multiple sources - merge
                merged = LLMReconciler._merge_areas(area_list)
                merged.confidence = ConfidenceLevel.HIGH.value
                merged.sources = {LLMSource.BOTH}
                reconciled.append(merged)
        
        return reconciled
    
    @staticmethod
    def _merge_areas(areas: List[DiscoveredArea]) -> DiscoveredArea:
        """Merge multiple area records into one."""
        # Use first area as base
        merged = DiscoveredArea(
            name=areas[0].name,
            area_type=areas[0].area_type,
            city=areas[0].city,
            state=areas[0].state,
            subtype=areas[0].subtype,
            uko_class=areas[0].uko_class,
        )
        
        # Collect all data
        all_boundaries = []
        all_characteristics = []
        all_informal_names = set()
        all_sources = set()
        all_raw = {}
        
        for area in areas:
            if area.boundaries:
                all_boundaries.append(area.boundaries)
            if area.characteristics:
                all_characteristics.append(area.characteristics)
            all_informal_names.update(area.informal_names)
            all_sources.update(area.sources)
            all_raw.update(area.raw_responses)
        
        # Merge
        merged.boundaries = " | ".join(all_boundaries) if all_boundaries else None
        merged.characteristics = " | ".join(all_characteristics) if all_characteristics else None
        merged.informal_names = list(all_informal_names)
        merged.sources = all_sources
        merged.raw_responses = all_raw
        
        return merged
    
    @staticmethod
    def find_conflicts(areas_by_source: Dict[LLMSource, List[DiscoveredArea]]) -> List[Dict]:
        """
        Identify conflicts between LLM responses.
        """
        conflicts = []
        
        by_name: Dict[str, Dict[LLMSource, DiscoveredArea]] = defaultdict(dict)
        
        for source, areas in areas_by_source.items():
            for area in areas:
                key = (area._normalize(area.name), area._normalize(area.city))
                by_name[key][source] = area
        
        for key, source_areas in by_name.items():
            if len(source_areas) < 2:
                continue
            
            sources = list(source_areas.keys())
            area1 = source_areas[sources[0]]
            area2 = source_areas[sources[1]]
            
            if area1.subtype != area2.subtype:
                conflicts.append({
                    'area': area1.name,
                    'city': area1.city,
                    'conflict_type': 'subtype',
                    'values': {
                        sources[0].value: area1.subtype,
                        sources[1].value: area2.subtype
                    }
                })
        
        return conflicts


# =============================================================================
# MAIN DISCOVERY PIPELINE
# =============================================================================

class MultiLLMAreaDiscovery:
    """Main pipeline for discovering areas using multiple LLMs."""
    
    def __init__(
        self,
        claude_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        use_claude: bool = True,
        use_gemini: bool = True
    ):
        self.providers: List[BaseLLMProvider] = []
        
        if use_claude and ANTHROPIC_AVAILABLE:
            try:
                self.providers.append(ClaudeProvider(api_key=claude_api_key))
                print("✓ Claude provider initialized")
            except Exception as e:
                print(f"⚠ Could not initialize Claude: {e}")
        
        if use_gemini and GEMINI_AVAILABLE:
            try:
                self.providers.append(GeminiProvider(api_key=gemini_api_key))
                print("✓ Gemini provider initialized")
            except Exception as e:
                print(f"⚠ Could not initialize Gemini: {e}")
        
        if not self.providers:
            raise ValueError("No LLM providers available. Check API keys and installations.")
        
        self.parser = ResponseParser()
        self.reconciler = LLMReconciler()
    
    def discover_neighborhoods(self, city: str, state: str) -> List[DiscoveredArea]:
        """Discover neighborhoods in a city using all available LLMs."""
        print(f"\nDiscovering neighborhoods in {city}, {state}...")
        
        prompt = NEIGHBORHOOD_PROMPT.format(city=city, state=state)
        areas_by_source: Dict[LLMSource, List[DiscoveredArea]] = {}
        
        for provider in self.providers:
            print(f"  Querying {provider.name}...")
            try:
                response = provider.query(prompt)
                areas = self.parser.parse_neighborhoods(
                    response, city, state, provider.source
                )
                areas_by_source[provider.source] = areas
                print(f"    Found {len(areas)} neighborhoods")
                time.sleep(1)  # Rate limiting
            except Exception as e:
                print(f"    Error: {e}")
                areas_by_source[provider.source] = []
        
        # Reconcile
        reconciled = self.reconciler.reconcile(areas_by_source)
        
        # Check for conflicts
        conflicts = self.reconciler.find_conflicts(areas_by_source)
        if conflicts:
            print(f"  ⚠ Found {len(conflicts)} conflicts:")
            for c in conflicts:
                print(f"    - {c['area']}: {c['conflict_type']} mismatch")
        
        # Summary
        both = sum(1 for a in reconciled if LLMSource.BOTH in a.sources)
        print(f"  ✓ Reconciled: {len(reconciled)} neighborhoods ({both} confirmed by both LLMs)")
        
        return reconciled
    
    def discover_districts(self, city: str, state: str) -> List[DiscoveredArea]:
        """Discover functional districts in a city using all available LLMs."""
        print(f"\nDiscovering districts in {city}, {state}...")
        
        prompt = DISTRICT_PROMPT.format(city=city, state=state)
        areas_by_source: Dict[LLMSource, List[DiscoveredArea]] = {}
        
        for provider in self.providers:
            print(f"  Querying {provider.name}...")
            try:
                response = provider.query(prompt)
                areas = self.parser.parse_districts(
                    response, city, state, provider.source
                )
                areas_by_source[provider.source] = areas
                print(f"    Found {len(areas)} districts")
                time.sleep(1)  # Rate limiting
            except Exception as e:
                print(f"    Error: {e}")
                areas_by_source[provider.source] = []
        
        # Reconcile
        reconciled = self.reconciler.reconcile(areas_by_source)
        
        # Summary
        both = sum(1 for a in reconciled if LLMSource.BOTH in a.sources)
        print(f"  ✓ Reconciled: {len(reconciled)} districts ({both} confirmed by both LLMs)")
        
        return reconciled
    
    def discover_all(self, cities: List[Tuple[str, str]]) -> Dict[str, List[DiscoveredArea]]:
        """Discover neighborhoods and districts for multiple cities."""
        all_neighborhoods = []
        all_districts = []
        
        for city, state in cities:
            print(f"\n{'='*60}")
            print(f"Processing: {city}, {state}")
            print('='*60)
            
            neighborhoods = self.discover_neighborhoods(city, state)
            all_neighborhoods.extend(neighborhoods)
            
            districts = self.discover_districts(city, state)
            all_districts.extend(districts)
        
        return {
            'neighborhoods': all_neighborhoods,
            'districts': all_districts
        }


# =============================================================================
# KNOWLEDGE GRAPH INTEGRATION
# =============================================================================

class KGIntegrator:
    """Integrates discovered areas into the knowledge graph."""
    
    def __init__(self, kg_path: str):
        self.kg_path = kg_path
        self.graph = Graph()
        
        print(f"Loading knowledge graph from {kg_path}...")
        self.graph.parse(kg_path, format='turtle')
        print(f"✓ Loaded {len(self.graph):,} triples")
    
    def add_areas(self, areas: List[DiscoveredArea]) -> int:
        """Add discovered areas to the knowledge graph."""
        added = 0
        
        for area in areas:
            uri = URIRef(area.to_uri())
            
            # Check if already exists
            if (uri, RDF.type, None) in self.graph:
                print(f"  Skipping {area.name} (already exists)")
                continue
            
            # Add type
            self.graph.add((uri, RDF.type, UKO[area.uko_class]))
            
            # Add label
            self.graph.add((uri, RDFS.label, Literal(area.name)))
            
            # Add city relationship
            city_uri = self._find_city_uri(area.city)
            if city_uri:
                self.graph.add((uri, UKO.partOf, city_uri))
            
            # Add properties
            if area.boundaries:
                self.graph.add((uri, UKO.approximateBoundary, Literal(area.boundaries)))
            
            if area.characteristics:
                self.graph.add((uri, UKO.neighborhoodCharacter, Literal(area.characteristics)))
            
            for informal_name in area.informal_names:
                self.graph.add((uri, UKO.informalName, Literal(informal_name)))
            
            # Add provenance
            self.graph.add((uri, UKO.hasConfidenceLevel, Literal(area.confidence, datatype=XSD.decimal)))
            
            source_str = ",".join(s.value for s in area.sources)
            self.graph.add((uri, UKO.discoveryMethod, Literal(f"llm_consensus:{source_str}")))
            
            # Add coordinates if available
            if area.latitude and area.longitude:
                self.graph.add((uri, UKO.latitude, Literal(area.latitude, datatype=XSD.decimal)))
                self.graph.add((uri, UKO.longitude, Literal(area.longitude, datatype=XSD.decimal)))
            
            added += 1
        
        print(f"✓ Added {added} areas to knowledge graph")
        return added
    
    def _find_city_uri(self, city_name: str) -> Optional[URIRef]:
        """Find the URI for a city in the KG."""
        patterns = [
            f"urn:urban-kg:entity/osm/city/{city_name.replace(' ', '_')}",
            f"urn:urban-kg:entity/city/{city_name.replace(' ', '_').lower()}",
        ]
        
        for pattern in patterns:
            uri = URIRef(pattern)
            if (uri, RDF.type, None) in self.graph:
                return uri
        
        # Query for city by label
        query = f"""
        SELECT ?city WHERE {{
            ?city a <urn:urban-kg:City> .
            ?city <http://www.w3.org/2000/01/rdf-schema#label> ?label .
            FILTER(CONTAINS(LCASE(?label), "{city_name.lower()}"))
        }} LIMIT 1
        """
        
        results = list(self.graph.query(query))
        if results:
            return results[0][0]
        
        return None
    
    def save(self, output_path: Optional[str] = None, format: str = 'nt'):
        """
        Save the enhanced knowledge graph.
        
        Using N-Triples format by default as it's much faster for large graphs.
        """
        if output_path is None:
            base, ext = os.path.splitext(self.kg_path)
            output_path = f"{base}_with_areas.nt"
        
        print(f"Saving enhanced KG to {output_path}...")
        self.graph.serialize(destination=output_path, format=format)
        print(f"✓ Saved {len(self.graph):,} triples")
        
        return output_path


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def enhance_kg_with_areas(
    kg_path: str,
    cities: List[Tuple[str, str]],
    output_path: Optional[str] = None,
    claude_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None
) -> str:
    """
    Main function to enhance a knowledge graph with LLM-discovered areas.
    """
    print("="*60)
    print("MULTI-LLM KNOWLEDGE GRAPH ENHANCEMENT")
    print("="*60)
    
    # Initialize discovery pipeline
    discovery = MultiLLMAreaDiscovery(
        claude_api_key=claude_api_key,
        gemini_api_key=gemini_api_key
    )
    
    # Discover areas
    results = discovery.discover_all(cities)
    
    print(f"\n{'='*60}")
    print("DISCOVERY SUMMARY")
    print("="*60)
    print(f"Total neighborhoods: {len(results['neighborhoods'])}")
    print(f"Total districts: {len(results['districts'])}")
    
    # High confidence (both LLMs agree)
    high_conf_n = sum(1 for a in results['neighborhoods'] if a.confidence >= 0.9)
    high_conf_d = sum(1 for a in results['districts'] if a.confidence >= 0.9)
    print(f"High confidence neighborhoods: {high_conf_n}")
    print(f"High confidence districts: {high_conf_d}")
    
    # Integrate into KG
    print(f"\n{'='*60}")
    print("KNOWLEDGE GRAPH INTEGRATION")
    print("="*60)
    
    integrator = KGIntegrator(kg_path)
    
    integrator.add_areas(results['neighborhoods'])
    integrator.add_areas(results['districts'])
    
    # Save - use N-Triples for faster saving
    output = integrator.save(output_path, format='nt')
    
    # Save discovery results as JSON for reference
    json_output = output.replace('.nt', '_areas.json').replace('.ttl', '_areas.json')
    with open(json_output, 'w') as f:
        json.dump({
            'neighborhoods': [
                {
                    'name': a.name,
                    'city': a.city,
                    'type': a.subtype,
                    'uko_class': a.uko_class,
                    'confidence': a.confidence,
                    'sources': [s.value for s in a.sources],
                    'boundaries': a.boundaries,
                    'characteristics': a.characteristics
                }
                for a in results['neighborhoods']
            ],
            'districts': [
                {
                    'name': a.name,
                    'city': a.city,
                    'type': a.subtype,
                    'uko_class': a.uko_class,
                    'confidence': a.confidence,
                    'sources': [s.value for s in a.sources],
                    'boundaries': a.boundaries,
                    'characteristics': a.characteristics
                }
                for a in results['districts']
            ]
        }, f, indent=2)
    print(f"✓ Saved discovery results to {json_output}")
    
    return output


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Enhance knowledge graph with LLM-discovered neighborhoods and districts"
    )
    parser.add_argument(
        "--kg_path",
        default="contracosta_kg_enhanced.ttl",
        help="Path to input knowledge graph"
    )
    parser.add_argument(
        "--output",
        help="Output path (default: adds '_with_areas' suffix)"
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        default=["Walnut Creek", "Antioch", "Richmond", "Pittsburg", "Pleasant Hill"],
        help="Cities to process"
    )
    parser.add_argument(
        "--state",
        default="CA",
        help="State code"
    )
    
    args = parser.parse_args()
    
    # Convert cities to tuples
    cities = [(city, args.state) for city in args.cities]
    
    # Run enhancement
    enhance_kg_with_areas(
        kg_path=args.kg_path,
        cities=cities,
        output_path=args.output
    )
