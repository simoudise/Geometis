"""
Sidewalk and Pedestrian Infrastructure Inference Module

Capabilities:
1. Infer sidewalk presence from street characteristics
2. Analyze Street View imagery for sidewalk detection
3. Infer crosswalk locations
4. Estimate sidewalk connectivity

Copyright (c) 2025 Synapse Partners, LLC
"""

import json
import asyncio
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import math

from .core import (
    LLMProvider, CandidateTriple, SourceEvidence, DataSource,
    SidewalkInference, VerificationResult
)


class StreetType(Enum):
    """OSM highway types with sidewalk likelihood."""
    MOTORWAY = ("motorway", 0.0)
    TRUNK = ("trunk", 0.1)
    PRIMARY = ("primary", 0.6)
    SECONDARY = ("secondary", 0.7)
    TERTIARY = ("tertiary", 0.75)
    RESIDENTIAL = ("residential", 0.8)
    LIVING_STREET = ("living_street", 0.9)
    SERVICE = ("service", 0.3)
    FOOTWAY = ("footway", 1.0)
    PATH = ("path", 0.5)
    
    @property
    def osm_value(self):
        return self.value[0]
    
    @property
    def sidewalk_likelihood(self):
        return self.value[1]


@dataclass
class StreetSegment:
    """A street segment from OSM."""
    segment_id: str
    osm_id: Optional[str] = None
    name: Optional[str] = None
    highway_type: Optional[str] = None
    speed_limit: Optional[int] = None  # mph or km/h
    lanes: Optional[int] = None
    surface: Optional[str] = None
    lit: Optional[bool] = None  # Has street lighting
    geometry: Optional[List[Tuple[float, float]]] = None  # List of (lat, lon)
    
    # Existing sidewalk tags from OSM
    sidewalk_tag: Optional[str] = None  # "both", "left", "right", "none", None
    
    @property
    def centroid(self) -> Optional[Tuple[float, float]]:
        """Get centroid of segment."""
        if not self.geometry:
            return None
        lats = [p[0] for p in self.geometry]
        lons = [p[1] for p in self.geometry]
        return (sum(lats) / len(lats), sum(lons) / len(lons))


@dataclass
class CrosswalkInference:
    """Inference about crosswalk presence at an intersection."""
    intersection_id: str
    lat: float
    lon: float
    has_crosswalk: bool = False
    crosswalk_type: Optional[str] = None  # "marked", "unmarked", "signalized"
    confidence: float = 0.5
    evidence: List[SourceEvidence] = field(default_factory=list)


class SidewalkHeuristicInferrer:
    """
    Infers sidewalk presence using heuristic rules.
    
    No LLM calls - pure rule-based inference.
    Fast and deterministic.
    """
    
    # Speed limit thresholds (mph)
    HIGH_SPEED_THRESHOLD = 45
    LOW_SPEED_THRESHOLD = 30
    
    # Context factors that increase sidewalk likelihood
    POSITIVE_CONTEXT = {
        "school": 0.15,
        "library": 0.12,
        "hospital": 0.12,
        "retail": 0.10,
        "park": 0.10,
        "transit_stop": 0.12
    }
    
    def infer(
        self,
        segment: StreetSegment,
        nearby_pois: Optional[List[Dict]] = None
    ) -> SidewalkInference:
        """
        Infer sidewalk presence using heuristics.
        
        Returns SidewalkInference with confidence score.
        """
        # If OSM already has sidewalk data, use it
        if segment.sidewalk_tag and segment.sidewalk_tag != "unknown":
            return SidewalkInference(
                segment_id=segment.segment_id,
                has_sidewalk=segment.sidewalk_tag != "none",
                sidewalk_side=segment.sidewalk_tag if segment.sidewalk_tag != "none" else "none",
                confidence=0.95,
                evidence=[SourceEvidence(
                    source=DataSource.OSM,
                    method=f"osm_sidewalk_tag={segment.sidewalk_tag}"
                )]
            )
        
        # Start with base probability from street type
        base_prob = self._get_base_probability(segment.highway_type)
        
        # Adjust based on speed limit
        speed_adj = self._speed_adjustment(segment.speed_limit)
        
        # Adjust based on lanes
        lane_adj = self._lane_adjustment(segment.lanes)
        
        # Adjust based on street lighting
        lighting_adj = 0.05 if segment.lit else 0.0
        
        # Adjust based on nearby POIs
        context_adj = self._context_adjustment(nearby_pois)
        
        # Combine adjustments
        final_prob = min(0.95, max(0.05, 
            base_prob + speed_adj + lane_adj + lighting_adj + context_adj
        ))
        
        # Determine sidewalk side
        sidewalk_side = "both" if final_prob > 0.6 else "unknown"
        
        return SidewalkInference(
            segment_id=segment.segment_id,
            has_sidewalk=final_prob > 0.5,
            sidewalk_side=sidewalk_side,
            confidence=final_prob,
            evidence=[SourceEvidence(
                source=DataSource.COMPUTED,
                method=f"heuristic: base={base_prob:.2f}, speed_adj={speed_adj:.2f}, "
                       f"lane_adj={lane_adj:.2f}, context_adj={context_adj:.2f}"
            )]
        )
    
    def _get_base_probability(self, highway_type: Optional[str]) -> float:
        """Get base probability from highway type."""
        if not highway_type:
            return 0.5
        
        for st in StreetType:
            if st.osm_value == highway_type:
                return st.sidewalk_likelihood
        
        return 0.5  # Default
    
    def _speed_adjustment(self, speed_limit: Optional[int]) -> float:
        """Adjust probability based on speed limit."""
        if speed_limit is None:
            return 0.0
        
        if speed_limit >= self.HIGH_SPEED_THRESHOLD:
            return -0.2  # High speed = less likely to have sidewalk
        elif speed_limit <= self.LOW_SPEED_THRESHOLD:
            return 0.1  # Low speed = more likely
        else:
            return 0.0
    
    def _lane_adjustment(self, lanes: Optional[int]) -> float:
        """Adjust based on number of lanes."""
        if lanes is None:
            return 0.0
        
        if lanes >= 4:
            return 0.05  # More lanes = more urban = more likely
        elif lanes <= 1:
            return -0.05  # Single lane might be rural
        return 0.0
    
    def _context_adjustment(self, nearby_pois: Optional[List[Dict]]) -> float:
        """Adjust based on nearby POIs."""
        if not nearby_pois:
            return 0.0
        
        adjustment = 0.0
        seen_types = set()
        
        for poi in nearby_pois:
            poi_type = poi.get("type", "").lower()
            for context_type, adj in self.POSITIVE_CONTEXT.items():
                if context_type in poi_type and context_type not in seen_types:
                    adjustment += adj
                    seen_types.add(context_type)
        
        return min(0.25, adjustment)  # Cap context adjustment


class StreetViewAnalyzer:
    """
    Analyzes Street View imagery to detect sidewalks.
    
    Uses LLM vision capabilities to analyze images.
    """
    
    ANALYSIS_PROMPT = """Analyze this street view image for pedestrian infrastructure.

Identify and describe:
1. SIDEWALK PRESENCE: Is there a sidewalk visible? (yes/no/unclear)
2. SIDEWALK SIDE: Which side of the street? (left/right/both/none)
3. SIDEWALK WIDTH: Estimate width (narrow <1m, standard 1-2m, wide >2m)
4. SIDEWALK CONDITION: (good/fair/poor)
5. CURB RAMPS: Are there curb ramps visible at intersections? (yes/no/unclear)
6. OBSTRUCTIONS: Any obstacles blocking the sidewalk? (poles, signs, vegetation)
7. CROSSWALKS: Any crosswalks visible? (marked/unmarked/none)
8. PEDESTRIAN SIGNALS: Traffic signals for pedestrians? (yes/no)

Return JSON:
{
  "sidewalk_present": true/false,
  "sidewalk_side": "both/left/right/none",
  "width_estimate": "narrow/standard/wide",
  "condition": "good/fair/poor",
  "curb_ramps": true/false/null,
  "obstructions": ["list of obstructions"],
  "crosswalk": "marked/unmarked/none",
  "pedestrian_signal": true/false,
  "confidence": 0.85,
  "notes": "any additional observations"
}
"""

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider
    
    async def analyze_segment(
        self,
        segment: StreetSegment,
        image_data: bytes
    ) -> SidewalkInference:
        """
        Analyze street view image for sidewalk presence.
        
        Args:
            segment: The street segment being analyzed
            image_data: JPEG image bytes from Street View
            
        Returns:
            SidewalkInference with LLM analysis results
        """
        response = await self.llm.analyze_image(image_data, self.ANALYSIS_PROMPT)
        
        try:
            # Parse JSON response
            json_match = __import__('re').search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                
                width_map = {"narrow": 0.8, "standard": 1.5, "wide": 2.5}
                
                return SidewalkInference(
                    segment_id=segment.segment_id,
                    has_sidewalk=result.get("sidewalk_present", False),
                    sidewalk_side=result.get("sidewalk_side", "unknown"),
                    width_estimate_m=width_map.get(result.get("width_estimate")),
                    condition=result.get("condition"),
                    has_curb_ramps=result.get("curb_ramps"),
                    confidence=result.get("confidence", 0.7),
                    evidence=[SourceEvidence(
                        source=DataSource.STREET_VIEW,
                        method="llm_image_analysis",
                        raw_response=response
                    )]
                )
        except json.JSONDecodeError:
            pass
        
        # Fallback
        return SidewalkInference(
            segment_id=segment.segment_id,
            confidence=0.3,
            evidence=[SourceEvidence(
                source=DataSource.STREET_VIEW,
                method="llm_image_analysis_failed"
            )]
        )


class SidewalkInferencePipeline:
    """
    Complete pipeline for sidewalk inference.
    
    Combines:
    1. OSM existing data
    2. Heuristic inference
    3. Street View analysis (optional)
    4. Context from nearby POIs
    """
    
    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        use_street_view: bool = False,
        street_view_api_key: Optional[str] = None
    ):
        self.heuristic_inferrer = SidewalkHeuristicInferrer()
        
        self.use_street_view = use_street_view and llm_provider is not None
        if self.use_street_view:
            self.street_view_analyzer = StreetViewAnalyzer(llm_provider)
        
        self.street_view_api_key = street_view_api_key
    
    async def infer_sidewalks(
        self,
        segments: List[StreetSegment],
        poi_index: Optional[Dict[str, List[Dict]]] = None
    ) -> List[SidewalkInference]:
        """
        Infer sidewalks for multiple street segments.
        
        Args:
            segments: List of street segments
            poi_index: Optional dict mapping segment_id to nearby POIs
            
        Returns:
            List of SidewalkInference results
        """
        results = []
        
        for segment in segments:
            nearby_pois = poi_index.get(segment.segment_id, []) if poi_index else []
            
            # Step 1: Heuristic inference
            inference = self.heuristic_inferrer.infer(segment, nearby_pois)
            
            # Step 2: Street View analysis (if enabled and confidence is medium)
            if self.use_street_view and 0.4 <= inference.confidence <= 0.7:
                sv_inference = await self._analyze_with_street_view(segment)
                if sv_inference and sv_inference.confidence > inference.confidence:
                    # Merge evidence
                    inference = sv_inference
                    inference.evidence.extend(inference.evidence)
            
            results.append(inference)
        
        return results
    
    async def _analyze_with_street_view(
        self,
        segment: StreetSegment
    ) -> Optional[SidewalkInference]:
        """Get Street View image and analyze."""
        if not segment.centroid or not self.street_view_api_key:
            return None
        
        # Fetch Street View image
        image_data = await self._fetch_street_view(segment.centroid)
        if not image_data:
            return None
        
        return await self.street_view_analyzer.analyze_segment(segment, image_data)
    
    async def _fetch_street_view(
        self,
        coords: Tuple[float, float]
    ) -> Optional[bytes]:
        """Fetch Street View image from Google API."""
        if not self.street_view_api_key:
            return None
        
        import aiohttp
        
        url = "https://maps.googleapis.com/maps/api/streetview"
        params = {
            "size": "640x480",
            "location": f"{coords[0]},{coords[1]}",
            "key": self.street_view_api_key,
            "source": "outdoor"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.read()
        except:
            pass
        
        return None
    
    def to_triples(
        self,
        inferences: List[SidewalkInference],
        segment_uris: Dict[str, str]
    ) -> List[CandidateTriple]:
        """
        Convert sidewalk inferences to KG triples.
        
        Args:
            inferences: List of SidewalkInference
            segment_uris: Mapping of segment_id to KG URI
            
        Returns:
            List of CandidateTriple
        """
        triples = []
        
        for inf in inferences:
            segment_uri = segment_uris.get(inf.segment_id)
            if not segment_uri:
                continue
            
            # hasSidewalk property
            triples.append(CandidateTriple(
                subject=segment_uri,
                predicate="uko:hasSidewalk",
                object=str(inf.has_sidewalk).lower(),
                confidence=inf.confidence,
                evidence=inf.evidence,
                requires_review=inf.confidence < 0.7
            ))
            
            # Sidewalk side
            if inf.sidewalk_side and inf.sidewalk_side != "unknown":
                triples.append(CandidateTriple(
                    subject=segment_uri,
                    predicate="uko:sidewalkSide",
                    object=f'"{inf.sidewalk_side}"',
                    confidence=inf.confidence,
                    evidence=inf.evidence
                ))
            
            # Width estimate
            if inf.width_estimate_m:
                triples.append(CandidateTriple(
                    subject=segment_uri,
                    predicate="uko:sidewalkWidth",
                    object=str(inf.width_estimate_m),
                    confidence=inf.confidence * 0.8,  # Lower confidence for estimate
                    evidence=inf.evidence
                ))
            
            # Condition
            if inf.condition:
                triples.append(CandidateTriple(
                    subject=segment_uri,
                    predicate="uko:sidewalkCondition",
                    object=f'"{inf.condition}"',
                    confidence=inf.confidence * 0.9,
                    evidence=inf.evidence
                ))
            
            # Curb ramps
            if inf.has_curb_ramps is not None:
                triples.append(CandidateTriple(
                    subject=segment_uri,
                    predicate="uko:hasCurbRamp",
                    object=str(inf.has_curb_ramps).lower(),
                    confidence=inf.confidence,
                    evidence=inf.evidence
                ))
        
        return triples


class CrosswalkInferrer:
    """
    Infers crosswalk presence at intersections.
    """
    
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider
    
    def infer_from_context(
        self,
        intersection_id: str,
        lat: float,
        lon: float,
        connecting_streets: List[StreetSegment],
        nearby_pois: Optional[List[Dict]] = None
    ) -> CrosswalkInference:
        """
        Infer crosswalk presence from intersection context.
        """
        # Check if any connecting street is high-traffic
        high_traffic = any(
            s.highway_type in ["primary", "secondary", "tertiary"]
            for s in connecting_streets
        )
        
        # Check if near school, transit, or other pedestrian generators
        pedestrian_generator = False
        if nearby_pois:
            ped_types = ["school", "transit", "library", "park", "hospital"]
            pedestrian_generator = any(
                any(pt in poi.get("type", "").lower() for pt in ped_types)
                for poi in nearby_pois
            )
        
        # Signalized intersection likely has crosswalk
        signalized = any(
            s.highway_type in ["primary", "secondary"] 
            for s in connecting_streets
        ) and len(connecting_streets) >= 3
        
        # Calculate probability
        prob = 0.3  # Base probability
        
        if high_traffic:
            prob += 0.2
        if pedestrian_generator:
            prob += 0.25
        if signalized:
            prob += 0.2
        
        prob = min(0.9, prob)
        
        crosswalk_type = None
        if prob > 0.5:
            crosswalk_type = "signalized" if signalized else "marked"
        
        return CrosswalkInference(
            intersection_id=intersection_id,
            lat=lat,
            lon=lon,
            has_crosswalk=prob > 0.5,
            crosswalk_type=crosswalk_type,
            confidence=prob,
            evidence=[SourceEvidence(
                source=DataSource.COMPUTED,
                method=f"context_inference: high_traffic={high_traffic}, "
                       f"ped_generator={pedestrian_generator}, signalized={signalized}"
            )]
        )
