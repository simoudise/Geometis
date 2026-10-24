"""
LLM Data Augmentation Module for Geospatial Knowledge Graphs

Provides capabilities to:
1. Classify and enrich existing OSM entities
2. Discover missing POIs via grounded web search
3. Infer pedestrian infrastructure (sidewalks, crosswalks)
4. Validate and verify LLM-generated data

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import json
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set, Any
from enum import Enum
from datetime import datetime
import hashlib

# Geometry handling
try:
    from shapely.geometry import Point, Polygon, LineString
    from shapely.ops import nearest_points
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    print("Warning: Shapely not available. Spatial operations will be limited.")


class DataSource(Enum):
    """Source of data in the knowledge graph."""
    OSM = "osm"
    LLM_INFERENCE = "llm_inference"
    LLM_WEB_SEARCH = "llm_web_search"
    GOOGLE_PLACES = "google_places"
    STREET_VIEW = "street_view"
    USER_CONTRIBUTED = "user_contributed"
    COMPUTED = "computed"  # Derived from spatial computation


class ConfidenceLevel(Enum):
    """Confidence levels for data quality."""
    VERIFIED = 0.95      # Cross-validated by multiple sources
    HIGH = 0.85          # Single authoritative source
    MEDIUM = 0.70        # LLM inference with supporting evidence
    LOW = 0.50           # LLM inference, plausible but unverified
    UNCERTAIN = 0.30     # Needs human review


@dataclass
class SourceEvidence:
    """Evidence supporting a data claim."""
    source: DataSource
    url: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    raw_response: Optional[str] = None
    method: Optional[str] = None  # e.g., "web_search", "classification"
    
    def to_dict(self) -> Dict:
        return {
            "source": self.source.value,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "method": self.method
        }


@dataclass
class CandidateTriple:
    """A candidate triple to be added to the knowledge graph."""
    subject: str           # Entity URI
    predicate: str         # Relation URI
    object: str            # Object URI or literal value
    confidence: float      # 0.0 to 1.0
    evidence: List[SourceEvidence] = field(default_factory=list)
    requires_review: bool = False
    verified: bool = False
    rejection_reason: Optional[str] = None
    
    @property
    def triple_hash(self) -> str:
        """Unique hash for deduplication."""
        content = f"{self.subject}|{self.predicate}|{self.object}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
            "requires_review": self.requires_review,
            "verified": self.verified
        }


@dataclass 
class CandidatePOI:
    """A candidate POI discovered by LLM."""
    name: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    poi_type: Optional[str] = None  # UKO class
    attributes: Dict[str, Any] = field(default_factory=dict)
    evidence: List[SourceEvidence] = field(default_factory=list)
    confidence: float = 0.5
    
    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None
    
    def to_uri(self, namespace: str = "urn:urban-kg:") -> str:
        """Generate a URI for this POI."""
        # Create URL-safe identifier from name
        safe_name = "".join(c if c.isalnum() else "_" for c in self.name)
        coord_hash = ""
        if self.has_coordinates:
            coord_hash = f"_{abs(hash((self.lat, self.lon))) % 10000}"
        return f"{namespace}poi_{safe_name}{coord_hash}"


@dataclass
class SidewalkInference:
    """Inference about sidewalk presence on a street segment."""
    segment_id: str
    segment_geometry: Optional[Any] = None  # LineString
    has_sidewalk: bool = False
    sidewalk_side: str = "both"  # "both", "left", "right", "none"
    width_estimate_m: Optional[float] = None
    condition: Optional[str] = None  # "good", "fair", "poor"
    has_curb_ramps: Optional[bool] = None
    confidence: float = 0.5
    evidence: List[SourceEvidence] = field(default_factory=list)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def complete(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        use_web_search: bool = False
    ) -> str:
        """Generate a completion."""
        pass
    
    @abstractmethod
    async def analyze_image(
        self,
        image_data: bytes,
        prompt: str
    ) -> str:
        """Analyze an image."""
        pass


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None
    
    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("Please install anthropic: pip install anthropic")
        return self._client
    
    async def complete(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        use_web_search: bool = False
    ) -> str:
        """Generate completion using Claude."""
        messages = [{"role": "user", "content": prompt}]
        
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages
        }
        
        if system_prompt:
            kwargs["system"] = system_prompt
        
        # Note: Web search would require tool use setup
        # This is a simplified version
        
        response = self.client.messages.create(**kwargs)
        return response.content[0].text
    
    async def analyze_image(self, image_data: bytes, prompt: str) -> str:
        """Analyze image using Claude's vision."""
        import base64
        
        image_b64 = base64.b64encode(image_data).decode()
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        return response.content[0].text


class MockLLMProvider(LLMProvider):
    """Mock provider for testing without API calls."""
    
    async def complete(self, prompt: str, system_prompt: Optional[str] = None,
                      use_web_search: bool = False) -> str:
        return json.dumps({
            "status": "mock_response",
            "message": "This is a mock LLM response for testing"
        })
    
    async def analyze_image(self, image_data: bytes, prompt: str) -> str:
        return json.dumps({
            "has_sidewalk": True,
            "confidence": 0.7,
            "description": "Mock sidewalk analysis"
        })


class GeocodingService(ABC):
    """Abstract geocoding service."""
    
    @abstractmethod
    async def geocode(self, address: str) -> Optional[Tuple[float, float]]:
        """Convert address to coordinates."""
        pass
    
    @abstractmethod
    async def reverse_geocode(self, lat: float, lon: float) -> Optional[str]:
        """Convert coordinates to address."""
        pass


class NominatimGeocoder(GeocodingService):
    """OpenStreetMap Nominatim geocoder."""
    
    def __init__(self, user_agent: str = "GeoKG-Augmentation/1.0"):
        self.user_agent = user_agent
        self.base_url = "https://nominatim.openstreetmap.org"
    
    async def geocode(self, address: str) -> Optional[Tuple[float, float]]:
        """Geocode an address using Nominatim."""
        import aiohttp
        
        params = {
            "q": address,
            "format": "json",
            "limit": 1
        }
        
        headers = {"User-Agent": self.user_agent}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/search",
                params=params,
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data:
                        return (float(data[0]["lat"]), float(data[0]["lon"]))
        return None
    
    async def reverse_geocode(self, lat: float, lon: float) -> Optional[str]:
        """Reverse geocode coordinates."""
        import aiohttp
        
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json"
        }
        
        headers = {"User-Agent": self.user_agent}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/reverse",
                params=params,
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("display_name")
        return None


class VerificationResult:
    """Result of verification process."""
    
    def __init__(
        self,
        verified: bool,
        confidence: float,
        evidence: List[SourceEvidence] = None,
        rejection_reason: Optional[str] = None
    ):
        self.verified = verified
        self.confidence = confidence
        self.evidence = evidence or []
        self.rejection_reason = rejection_reason


class TripleVerifier:
    """
    Verifies candidate triples before adding to knowledge graph.
    
    Verification strategies:
    1. Spatial verification - for spatial relations, compute from coordinates
    2. Cross-reference - check against external APIs
    3. Consistency - check against existing KG
    4. Plausibility - LLM-based sanity check
    """
    
    # Relations that can be verified spatially
    SPATIAL_RELATIONS = {
        "uko:near", "uko:veryNear", "uko:within", "uko:contains",
        "uko:adjacentTo", "uko:intersects", "uko:crosses"
    }
    
    # Distance thresholds for spatial relations (meters)
    SPATIAL_THRESHOLDS = {
        "uko:veryNear": 50,
        "uko:near": 500,
        "uko:adjacentTo": 20
    }
    
    def __init__(
        self,
        existing_kg: Optional[Dict] = None,
        geocoder: Optional[GeocodingService] = None
    ):
        self.existing_kg = existing_kg or {}
        self.geocoder = geocoder or NominatimGeocoder()
        self.entity_coordinates: Dict[str, Tuple[float, float]] = {}
    
    def load_coordinates(self, coords_file: str):
        """Load entity coordinates from file."""
        with open(coords_file, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) == 3:
                    uri, lat, lon = parts
                    self.entity_coordinates[uri] = (float(lat), float(lon))
    
    async def verify(self, triple: CandidateTriple) -> VerificationResult:
        """
        Verify a candidate triple.
        
        Returns VerificationResult with updated confidence and evidence.
        """
        predicate = triple.predicate.split('/')[-1].split('#')[-1]
        
        # Spatial relations - verify computationally
        if any(sr.endswith(predicate) for sr in self.SPATIAL_RELATIONS):
            return await self._verify_spatial(triple)
        
        # Type assertions - cross-reference if possible
        if predicate in ["type", "rdf:type", "a"]:
            return await self._verify_type(triple)
        
        # Default: accept with reduced confidence
        return VerificationResult(
            verified=True,
            confidence=triple.confidence * 0.8,
            evidence=triple.evidence
        )
    
    async def _verify_spatial(self, triple: CandidateTriple) -> VerificationResult:
        """Verify spatial relationship by computing from coordinates."""
        subj_coords = self.entity_coordinates.get(triple.subject)
        obj_coords = self.entity_coordinates.get(triple.object)
        
        if not subj_coords or not obj_coords:
            return VerificationResult(
                verified=False,
                confidence=0.3,
                rejection_reason="Missing coordinates for spatial verification"
            )
        
        # Compute actual distance
        distance = self._haversine(
            subj_coords[0], subj_coords[1],
            obj_coords[0], obj_coords[1]
        )
        
        # Get threshold for this relation
        predicate = triple.predicate.split('/')[-1].split('#')[-1]
        threshold = None
        for rel, thresh in self.SPATIAL_THRESHOLDS.items():
            if rel.endswith(predicate):
                threshold = thresh
                break
        
        if threshold is None:
            threshold = 1000  # Default 1km
        
        # Verify
        if distance <= threshold:
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=[SourceEvidence(
                    source=DataSource.COMPUTED,
                    method=f"haversine_distance={distance:.1f}m, threshold={threshold}m"
                )]
            )
        else:
            return VerificationResult(
                verified=False,
                confidence=0.0,
                rejection_reason=f"Distance {distance:.1f}m exceeds threshold {threshold}m"
            )
    
    async def _verify_type(self, triple: CandidateTriple) -> VerificationResult:
        """Verify type assertion."""
        # For now, accept with moderate confidence
        # Could be enhanced with Google Places API verification
        return VerificationResult(
            verified=True,
            confidence=triple.confidence * 0.9,
            evidence=triple.evidence
        )
    
    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Compute Haversine distance in meters."""
        import math
        
        R = 6371000  # Earth radius in meters
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2)**2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2)
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c
