"""
LLM Data Augmentation Module for Geospatial Knowledge Graphs

This module provides capabilities to augment OSM-based knowledge graphs
with LLM-derived data, including:

1. POI Classification - Classify existing POIs into UKO ontology
2. POI Discovery - Find missing POIs via web search
3. Sidewalk Inference - Infer pedestrian infrastructure
4. Triple Verification - Verify LLM-generated data before ingestion
5. Area Discovery - Discover neighborhoods and functional districts

Copyright (c) 2025 Synapse Partners, LLC
"""

from .core import (
    DataSource,
    ConfidenceLevel,
    SourceEvidence,
    CandidateTriple,
    CandidatePOI,
    SidewalkInference,
    LLMProvider,
    AnthropicProvider,
    MockLLMProvider,
    GeocodingService,
    NominatimGeocoder,
    TripleVerifier,
    VerificationResult
)

from .poi_augmentation import (
    POIClassifier,
    POIDiscoverer,
    POIEnricher,
    POIAugmentationPipeline,
    UKO_POI_HIERARCHY
)

from .sidewalk_inference import (
    StreetSegment,
    StreetType,
    SidewalkHeuristicInferrer,
    StreetViewAnalyzer,
    SidewalkInferencePipeline,
    CrosswalkInferrer,
    CrosswalkInference
)

from .pipeline import (
    AugmentationConfig,
    AugmentationResult,
    LLMAugmentationPipeline,
    run_augmentation
)

from .area_discovery import (
    AreaType,
    CandidateArea,
    POICluster,
    NeighborhoodDiscoverer,
    FunctionalDistrictDiscoverer,
    AreaDiscoveryPipeline,
    run_area_discovery,
    FUNCTIONAL_DISTRICT_TYPES,
    ETHNIC_ENCLAVE_TYPES
)

__all__ = [
    # Core classes
    "DataSource",
    "ConfidenceLevel", 
    "SourceEvidence",
    "CandidateTriple",
    "CandidatePOI",
    "SidewalkInference",
    
    # LLM providers
    "LLMProvider",
    "AnthropicProvider",
    "MockLLMProvider",
    
    # Geocoding
    "GeocodingService",
    "NominatimGeocoder",
    
    # Verification
    "TripleVerifier",
    "VerificationResult",
    
    # POI augmentation
    "POIClassifier",
    "POIDiscoverer",
    "POIEnricher",
    "POIAugmentationPipeline",
    "UKO_POI_HIERARCHY",
    
    # Sidewalk inference
    "StreetSegment",
    "StreetType",
    "SidewalkHeuristicInferrer",
    "StreetViewAnalyzer",
    "SidewalkInferencePipeline",
    "CrosswalkInferrer",
    "CrosswalkInference",
    
    # Area discovery (neighborhoods & districts)
    "AreaType",
    "CandidateArea",
    "POICluster",
    "NeighborhoodDiscoverer",
    "FunctionalDistrictDiscoverer",
    "AreaDiscoveryPipeline",
    "run_area_discovery",
    "FUNCTIONAL_DISTRICT_TYPES",
    "ETHNIC_ENCLAVE_TYPES",
    
    # Main pipeline
    "AugmentationConfig",
    "AugmentationResult",
    "LLMAugmentationPipeline",
    "run_augmentation"
]
