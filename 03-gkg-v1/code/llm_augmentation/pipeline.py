"""
LLM Augmentation Pipeline

Main orchestration module that combines:
1. POI classification and discovery
2. Sidewalk inference
3. Triple verification
4. KG integration

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import json
import asyncio
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .core import (
    LLMProvider, AnthropicProvider, MockLLMProvider,
    GeocodingService, NominatimGeocoder,
    CandidateTriple, TripleVerifier,
    DataSource, ConfidenceLevel
)
from .poi_augmentation import (
    POIClassifier, POIDiscoverer, POIEnricher, POIAugmentationPipeline
)
from .sidewalk_inference import (
    SidewalkInferencePipeline, StreetSegment, SidewalkHeuristicInferrer
)


@dataclass
class AugmentationConfig:
    """Configuration for the augmentation pipeline."""
    
    # LLM settings
    llm_provider: str = "anthropic"  # "anthropic", "mock"
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    
    # Geocoding
    geocoder: str = "nominatim"
    
    # Street View (optional)
    use_street_view: bool = False
    google_street_view_api_key: Optional[str] = None
    
    # Processing
    batch_size: int = 10
    max_concurrent_requests: int = 5
    
    # Confidence thresholds
    auto_accept_threshold: float = 0.85
    review_threshold: float = 0.60
    reject_threshold: float = 0.40
    
    # Output
    output_dir: str = "augmentation_output"


@dataclass
class AugmentationResult:
    """Result of an augmentation run."""
    
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Counts
    pois_discovered: int = 0
    pois_classified: int = 0
    sidewalks_inferred: int = 0
    
    # Triples by status
    triples_accepted: List[CandidateTriple] = field(default_factory=list)
    triples_pending_review: List[CandidateTriple] = field(default_factory=list)
    triples_rejected: List[CandidateTriple] = field(default_factory=list)
    
    # Errors
    errors: List[str] = field(default_factory=list)
    
    def summary(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "pois_discovered": self.pois_discovered,
            "pois_classified": self.pois_classified,
            "sidewalks_inferred": self.sidewalks_inferred,
            "triples_accepted": len(self.triples_accepted),
            "triples_pending_review": len(self.triples_pending_review),
            "triples_rejected": len(self.triples_rejected),
            "errors": len(self.errors)
        }


class LLMAugmentationPipeline:
    """
    Main augmentation pipeline.
    
    Orchestrates all augmentation components and manages the flow:
    1. Load existing KG data
    2. Run POI discovery/classification
    3. Run sidewalk inference
    4. Verify all candidate triples
    5. Output accepted triples and review queue
    """
    
    def __init__(self, config: AugmentationConfig):
        self.config = config
        
        # Initialize LLM provider
        if config.llm_provider == "anthropic":
            self.llm = AnthropicProvider(
                api_key=config.anthropic_api_key,
                model=config.anthropic_model
            )
        else:
            self.llm = MockLLMProvider()
        
        # Initialize geocoder
        self.geocoder = NominatimGeocoder()
        
        # Initialize sub-pipelines
        self.poi_pipeline = POIAugmentationPipeline(
            llm_provider=self.llm,
            geocoder=self.geocoder
        )
        
        self.sidewalk_pipeline = SidewalkInferencePipeline(
            llm_provider=self.llm if config.use_street_view else None,
            use_street_view=config.use_street_view,
            street_view_api_key=config.google_street_view_api_key
        )
        
        # Initialize verifier
        self.verifier = TripleVerifier(geocoder=self.geocoder)
        
        # Create output directory
        os.makedirs(config.output_dir, exist_ok=True)
    
    def load_existing_kg(self, kg_path: str):
        """Load existing knowledge graph for context."""
        # Load coordinates for verification
        coords_path = kg_path.replace(".ttl", "_coordinates.txt")
        if os.path.exists(coords_path):
            self.verifier.load_coordinates(coords_path)
        
        # Could also load existing POIs, relations, etc.
    
    async def augment_area(
        self,
        city: str,
        neighborhood: str,
        discover_pois: bool = True,
        infer_sidewalks: bool = True,
        street_segments: Optional[List[StreetSegment]] = None
    ) -> AugmentationResult:
        """
        Run full augmentation for an area.
        
        Args:
            city: City name (e.g., "Walnut Creek")
            neighborhood: Neighborhood/area (e.g., "downtown")
            discover_pois: Whether to discover new POIs
            infer_sidewalks: Whether to infer sidewalk presence
            street_segments: Optional list of street segments for sidewalk inference
            
        Returns:
            AugmentationResult with all triples and statistics
        """
        result = AugmentationResult()
        all_candidate_triples: List[CandidateTriple] = []
        
        print(f"\n{'='*60}")
        print(f"LLM Augmentation Pipeline")
        print(f"Area: {neighborhood}, {city}")
        print(f"{'='*60}\n")
        
        # Step 1: POI Discovery
        if discover_pois:
            print("Step 1: POI Discovery...")
            try:
                poi_results = await self.poi_pipeline.augment_area(
                    city=city,
                    neighborhood=neighborhood,
                    discover_new=True
                )
                
                result.pois_discovered = len(poi_results.get("discovered", []))
                all_candidate_triples.extend(poi_results.get("triples", []))
                
                print(f"  ✓ Discovered {result.pois_discovered} new POIs")
                print(f"  ✓ Generated {len(poi_results.get('triples', []))} candidate triples")
                
            except Exception as e:
                error_msg = f"POI discovery error: {str(e)}"
                result.errors.append(error_msg)
                print(f"  ✗ {error_msg}")
        
        # Step 2: Sidewalk Inference
        if infer_sidewalks and street_segments:
            print("\nStep 2: Sidewalk Inference...")
            try:
                sidewalk_inferences = await self.sidewalk_pipeline.infer_sidewalks(
                    segments=street_segments
                )
                
                result.sidewalks_inferred = len(sidewalk_inferences)
                
                # Convert to triples
                segment_uris = {s.segment_id: f"urn:urban-kg:segment_{s.segment_id}" 
                               for s in street_segments}
                sidewalk_triples = self.sidewalk_pipeline.to_triples(
                    sidewalk_inferences, segment_uris
                )
                all_candidate_triples.extend(sidewalk_triples)
                
                print(f"  ✓ Inferred sidewalks for {result.sidewalks_inferred} segments")
                print(f"  ✓ Generated {len(sidewalk_triples)} candidate triples")
                
            except Exception as e:
                error_msg = f"Sidewalk inference error: {str(e)}"
                result.errors.append(error_msg)
                print(f"  ✗ {error_msg}")
        
        # Step 3: Verify all triples
        print(f"\nStep 3: Verifying {len(all_candidate_triples)} candidate triples...")
        
        for triple in all_candidate_triples:
            try:
                verification = await self.verifier.verify(triple)
                
                triple.verified = verification.verified
                triple.confidence = verification.confidence
                triple.evidence.extend(verification.evidence)
                
                if verification.rejection_reason:
                    triple.rejection_reason = verification.rejection_reason
                
                # Categorize by confidence
                if triple.confidence >= self.config.auto_accept_threshold:
                    result.triples_accepted.append(triple)
                elif triple.confidence >= self.config.review_threshold:
                    triple.requires_review = True
                    result.triples_pending_review.append(triple)
                else:
                    result.triples_rejected.append(triple)
                    
            except Exception as e:
                triple.rejection_reason = str(e)
                result.triples_rejected.append(triple)
        
        print(f"  ✓ Accepted: {len(result.triples_accepted)}")
        print(f"  ⚠ Pending review: {len(result.triples_pending_review)}")
        print(f"  ✗ Rejected: {len(result.triples_rejected)}")
        
        # Step 4: Save results
        print(f"\nStep 4: Saving results...")
        self._save_results(result, city, neighborhood)
        
        print(f"\n{'='*60}")
        print("Augmentation Complete!")
        print(f"{'='*60}")
        
        return result
    
    def _save_results(
        self, 
        result: AugmentationResult,
        city: str,
        neighborhood: str
    ):
        """Save augmentation results to files."""
        timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
        base_name = f"{city}_{neighborhood}_{timestamp}".replace(" ", "_").lower()
        
        # Save accepted triples as TTL
        accepted_path = os.path.join(
            self.config.output_dir, 
            f"{base_name}_accepted.ttl"
        )
        self._write_triples_ttl(result.triples_accepted, accepted_path)
        print(f"  ✓ Saved accepted triples: {accepted_path}")
        
        # Save pending review as JSON (for human review interface)
        review_path = os.path.join(
            self.config.output_dir,
            f"{base_name}_review.json"
        )
        self._write_triples_json(result.triples_pending_review, review_path)
        print(f"  ✓ Saved review queue: {review_path}")
        
        # Save rejected with reasons
        rejected_path = os.path.join(
            self.config.output_dir,
            f"{base_name}_rejected.json"
        )
        self._write_triples_json(result.triples_rejected, rejected_path)
        print(f"  ✓ Saved rejected triples: {rejected_path}")
        
        # Save summary
        summary_path = os.path.join(
            self.config.output_dir,
            f"{base_name}_summary.json"
        )
        with open(summary_path, 'w') as f:
            json.dump(result.summary(), f, indent=2)
        print(f"  ✓ Saved summary: {summary_path}")
    
    def _write_triples_ttl(self, triples: List[CandidateTriple], path: str):
        """Write triples in Turtle format."""
        with open(path, 'w') as f:
            # Prefixes
            f.write("@prefix uko: <urn:urban-kg:> .\n")
            f.write("@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n")
            f.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
            f.write("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n")
            f.write("\n")
            
            # Triples with provenance comments
            for triple in triples:
                # Add provenance as comment
                sources = [e.source.value for e in triple.evidence]
                f.write(f"# Confidence: {triple.confidence:.2f}, Sources: {sources}\n")
                
                # Write triple
                subj = triple.subject if triple.subject.startswith("<") else f"<{triple.subject}>"
                pred = triple.predicate
                obj = triple.object
                
                # Handle literal vs URI
                if obj.startswith('"'):
                    f.write(f"{subj} {pred} {obj} .\n")
                elif obj.startswith("http") or obj.startswith("urn:"):
                    f.write(f"{subj} {pred} <{obj}> .\n")
                else:
                    f.write(f"{subj} {pred} {obj} .\n")
                
                f.write("\n")
    
    def _write_triples_json(self, triples: List[CandidateTriple], path: str):
        """Write triples as JSON for review."""
        data = [triple.to_dict() for triple in triples]
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)


async def run_augmentation(
    city: str,
    neighborhood: str,
    kg_path: Optional[str] = None,
    config: Optional[AugmentationConfig] = None
) -> AugmentationResult:
    """
    Convenience function to run augmentation.
    
    Example:
        result = await run_augmentation(
            city="Walnut Creek",
            neighborhood="downtown",
            kg_path="contracosta_kg.ttl"
        )
    """
    config = config or AugmentationConfig()
    pipeline = LLMAugmentationPipeline(config)
    
    if kg_path:
        pipeline.load_existing_kg(kg_path)
    
    return await pipeline.augment_area(
        city=city,
        neighborhood=neighborhood,
        discover_pois=True,
        infer_sidewalks=False  # Need street segments for this
    )


# CLI interface
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="LLM Data Augmentation for GeoKG")
    parser.add_argument("--city", required=True, help="City name")
    parser.add_argument("--neighborhood", required=True, help="Neighborhood/area name")
    parser.add_argument("--kg_path", help="Path to existing knowledge graph")
    parser.add_argument("--output_dir", default="augmentation_output", help="Output directory")
    parser.add_argument("--anthropic_key", help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM for testing")
    
    args = parser.parse_args()
    
    config = AugmentationConfig(
        llm_provider="mock" if args.mock else "anthropic",
        anthropic_api_key=args.anthropic_key,
        output_dir=args.output_dir
    )
    
    result = asyncio.run(run_augmentation(
        city=args.city,
        neighborhood=args.neighborhood,
        kg_path=args.kg_path,
        config=config
    ))
    
    print(f"\nFinal Summary:")
    print(json.dumps(result.summary(), indent=2))


if __name__ == "__main__":
    main()
