"""
POI Enrichment and Discovery Module

Capabilities:
1. Classify existing OSM POIs into UKO ontology
2. Discover missing POIs via web search
3. Enrich POI attributes (hours, services, accessibility)

Copyright (c) 2025 Synapse Partners, LLC
"""

import json
import asyncio
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass
import re

from .core import (
    LLMProvider, GeocodingService, CandidatePOI, CandidateTriple,
    SourceEvidence, DataSource, ConfidenceLevel, VerificationResult
)


# UKO POI Type Hierarchy for classification
UKO_POI_HIERARCHY = {
    "Food & Dining": {
        "Restaurant": ["FastFood", "CasualDining", "FineDining", "FamilyRestaurant"],
        "Cafe": [],
        "CoffeeShop": [],
        "Bakery": [],
        "Bar": [],
        "Pub": [],
        "IceCreamShop": [],
        "Deli": []
    },
    "Retail": {
        "GroceryStore": ["Supermarket", "ConvenienceStore", "WarehouseClub"],
        "Pharmacy": [],
        "ClothingStore": [],
        "ElectronicsStore": [],
        "HardwareStore": [],
        "BookStore": [],
        "FurnitureStore": [],
        "GasStation": [],
        "AutoDealership": []
    },
    "Healthcare": {
        "Hospital": ["GeneralHospital", "ChildrensHospital"],
        "Clinic": ["MedicalClinic", "UrgentCare", "DentalClinic"],
        "Pharmacy": [],
        "NursingHome": []
    },
    "Education": {
        "School": ["Preschool", "ElementarySchool", "MiddleSchool", "HighSchool"],
        "University": [],
        "College": [],
        "Library": []
    },
    "Services": {
        "Bank": [],
        "PostOffice": [],
        "HairSalon": [],
        "BarberShop": [],
        "AutoRepair": [],
        "CarWash": []
    }
}


class POIClassifier:
    """
    Classifies POIs into UKO ontology categories using LLM.
    
    Low hallucination risk - pattern matching on names and context.
    """
    
    SYSTEM_PROMPT = """You are a POI classification expert. Given a business name and optional context,
classify it into the most specific category from the provided hierarchy.

Rules:
1. Be specific - prefer "CasualDining" over "Restaurant" if you're confident
2. If uncertain, use the broader category
3. Return ONLY the classification in JSON format
4. Include confidence score (0.0-1.0)
5. If the POI type is not in the hierarchy, return the closest match with lower confidence
"""

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider
        self._hierarchy_text = self._build_hierarchy_text()
    
    def _build_hierarchy_text(self) -> str:
        """Build text representation of hierarchy for prompt."""
        lines = []
        for category, types in UKO_POI_HIERARCHY.items():
            lines.append(f"\n{category}:")
            for poi_type, subtypes in types.items():
                if subtypes:
                    lines.append(f"  - {poi_type}: {', '.join(subtypes)}")
                else:
                    lines.append(f"  - {poi_type}")
        return "\n".join(lines)
    
    async def classify(
        self,
        name: str,
        osm_tags: Optional[Dict[str, str]] = None,
        address: Optional[str] = None
    ) -> Tuple[str, float, str]:
        """
        Classify a POI into UKO hierarchy.
        
        Returns: (uko_class, confidence, reasoning)
        """
        context_parts = []
        if osm_tags:
            context_parts.append(f"OSM tags: {json.dumps(osm_tags)}")
        if address:
            context_parts.append(f"Address: {address}")
        
        context = "\n".join(context_parts) if context_parts else "No additional context"
        
        prompt = f"""Classify this POI:

Name: {name}
{context}

Available categories:
{self._hierarchy_text}

Return JSON:
{{"uko_class": "ClassName", "confidence": 0.85, "reasoning": "brief explanation"}}
"""
        
        response = await self.llm.complete(prompt, system_prompt=self.SYSTEM_PROMPT)
        
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                result = json.loads(json_match.group())
                return (
                    result.get("uko_class", "PointOfInterest"),
                    result.get("confidence", 0.5),
                    result.get("reasoning", "")
                )
        except json.JSONDecodeError:
            pass
        
        return ("PointOfInterest", 0.3, "Failed to parse classification")
    
    async def classify_batch(
        self,
        pois: List[Dict]
    ) -> List[Tuple[str, str, float]]:
        """
        Classify multiple POIs efficiently.
        
        Returns: List of (poi_id, uko_class, confidence)
        """
        results = []
        
        # Process in batches to avoid rate limits
        batch_size = 10
        for i in range(0, len(pois), batch_size):
            batch = pois[i:i+batch_size]
            
            tasks = [
                self.classify(
                    poi.get("name", "Unknown"),
                    poi.get("tags"),
                    poi.get("address")
                )
                for poi in batch
            ]
            
            batch_results = await asyncio.gather(*tasks)
            
            for poi, (uko_class, confidence, _) in zip(batch, batch_results):
                results.append((poi.get("id"), uko_class, confidence))
        
        return results


class POIDiscoverer:
    """
    Discovers missing POIs using LLM with web search grounding.
    
    Medium hallucination risk - requires verification.
    """
    
    SYSTEM_PROMPT = """You are a local business researcher. Your task is to find real businesses 
and points of interest in a specified area.

CRITICAL RULES:
1. Only report businesses you can verify exist through web search
2. Always include the source URL where you found the information
3. Include the full street address
4. If you cannot verify a business exists, do not include it
5. Do not make up or guess business names
6. Do not estimate coordinates - leave them blank

Return results as JSON array."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        geocoder: GeocodingService
    ):
        self.llm = llm_provider
        self.geocoder = geocoder
    
    async def discover_in_area(
        self,
        city: str,
        neighborhood: str,
        poi_types: Optional[List[str]] = None,
        existing_pois: Optional[Set[str]] = None
    ) -> List[CandidatePOI]:
        """
        Discover POIs in a specified area.
        
        Args:
            city: City name
            neighborhood: Neighborhood or area name
            poi_types: Specific types to search for (e.g., ["restaurant", "retail"])
            existing_pois: Set of existing POI names to exclude
            
        Returns:
            List of CandidatePOI objects
        """
        existing_pois = existing_pois or set()
        
        type_filter = ""
        if poi_types:
            type_filter = f"\nFocus on these types: {', '.join(poi_types)}"
        
        prompt = f"""Search for businesses and points of interest in {neighborhood}, {city}.
{type_filter}

For each POI found, provide:
1. Business name (exact name as found)
2. Full street address
3. Business type (restaurant, retail, service, etc.)
4. Source URL where you verified this business exists
5. Brief description if available

Already known POIs to skip: {', '.join(list(existing_pois)[:20])}

Return as JSON array:
[
  {{
    "name": "Business Name",
    "address": "123 Main St, {city}, CA",
    "type": "restaurant",
    "source_url": "https://...",
    "description": "optional description"
  }}
]
"""
        
        response = await self.llm.complete(
            prompt, 
            system_prompt=self.SYSTEM_PROMPT,
            use_web_search=True
        )
        
        candidates = await self._parse_and_verify(response, city)
        
        # Filter out existing POIs
        candidates = [
            c for c in candidates 
            if c.name.lower() not in {p.lower() for p in existing_pois}
        ]
        
        return candidates
    
    async def _parse_and_verify(
        self, 
        response: str,
        city: str
    ) -> List[CandidatePOI]:
        """Parse LLM response and geocode addresses."""
        candidates = []
        
        try:
            # Extract JSON array from response
            json_match = re.search(r'\[[\s\S]*\]', response)
            if not json_match:
                return candidates
            
            data = json.loads(json_match.group())
            
            for item in data:
                if not isinstance(item, dict):
                    continue
                
                name = item.get("name", "").strip()
                address = item.get("address", "").strip()
                
                if not name:
                    continue
                
                candidate = CandidatePOI(
                    name=name,
                    address=address,
                    poi_type=item.get("type"),
                    attributes={"description": item.get("description")},
                    confidence=0.6  # Initial confidence before geocoding
                )
                
                # Add source evidence
                if item.get("source_url"):
                    candidate.evidence.append(SourceEvidence(
                        source=DataSource.LLM_WEB_SEARCH,
                        url=item.get("source_url"),
                        method="web_search_discovery"
                    ))
                
                # Geocode the address
                if address:
                    coords = await self.geocoder.geocode(f"{address}, {city}")
                    if coords:
                        candidate.lat, candidate.lon = coords
                        candidate.confidence = 0.75  # Higher confidence with geocoding
                        candidate.evidence.append(SourceEvidence(
                            source=DataSource.COMPUTED,
                            method=f"geocoded_address: {address}"
                        ))
                
                candidates.append(candidate)
                
        except json.JSONDecodeError:
            pass
        
        return candidates
    
    async def verify_poi_exists(self, poi: CandidatePOI) -> VerificationResult:
        """
        Verify a POI exists using web search.
        
        Returns verification result with updated confidence.
        """
        if not poi.name:
            return VerificationResult(
                verified=False,
                confidence=0.0,
                rejection_reason="No POI name provided"
            )
        
        search_query = poi.name
        if poi.address:
            search_query += f" {poi.address}"
        
        prompt = f"""Verify if this business exists and is currently operating:

Business: {poi.name}
Address: {poi.address or 'Unknown'}

Search the web and provide:
1. Does this business exist? (yes/no)
2. Is it currently operating? (yes/no/unknown)
3. Source URL for verification
4. Any corrections to name or address

Return JSON:
{{"exists": true/false, "operating": true/false, "source_url": "...", "corrections": {{}}}}
"""
        
        response = await self.llm.complete(
            prompt,
            use_web_search=True
        )
        
        try:
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                result = json.loads(json_match.group())
                
                if result.get("exists") and result.get("operating", True):
                    return VerificationResult(
                        verified=True,
                        confidence=0.85,
                        evidence=[SourceEvidence(
                            source=DataSource.LLM_WEB_SEARCH,
                            url=result.get("source_url"),
                            method="existence_verification"
                        )]
                    )
                else:
                    return VerificationResult(
                        verified=False,
                        confidence=0.2,
                        rejection_reason="Business not found or not operating"
                    )
        except:
            pass
        
        return VerificationResult(
            verified=False,
            confidence=0.3,
            rejection_reason="Could not verify"
        )


class POIEnricher:
    """
    Enriches existing POIs with additional attributes.
    
    Low hallucination risk for factual lookups.
    """
    
    SYSTEM_PROMPT = """You are a business information researcher. Look up factual information 
about businesses from reliable sources.

Rules:
1. Only provide information you can verify from web search
2. Include source URLs for all claims
3. If information is not available, say "unknown"
4. Do not guess or estimate values
"""

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider
    
    async def enrich_attributes(
        self,
        poi_name: str,
        poi_address: str,
        requested_attributes: List[str]
    ) -> Dict[str, any]:
        """
        Enrich POI with requested attributes.
        
        Available attributes:
        - opening_hours
        - phone_number
        - website
        - wheelchair_accessible
        - services (list)
        - price_range
        - cuisine_type (for restaurants)
        """
        prompt = f"""Look up the following information for this business:

Business: {poi_name}
Address: {poi_address}

Requested information:
{chr(10).join(f'- {attr}' for attr in requested_attributes)}

Return JSON with available information and source URLs:
{{
  "attributes": {{
    "opening_hours": "Mon-Fri 9am-5pm" or null,
    "phone_number": "555-1234" or null,
    ...
  }},
  "sources": ["url1", "url2"],
  "confidence": 0.85
}}
"""
        
        response = await self.llm.complete(
            prompt,
            system_prompt=self.SYSTEM_PROMPT,
            use_web_search=True
        )
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                return result
        except:
            pass
        
        return {"attributes": {}, "sources": [], "confidence": 0.3}


class POIAugmentationPipeline:
    """
    Complete pipeline for POI augmentation.
    
    Orchestrates classification, discovery, and enrichment.
    """
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        geocoder: Optional[GeocodingService] = None,
        existing_kg_path: Optional[str] = None
    ):
        self.classifier = POIClassifier(llm_provider)
        self.discoverer = POIDiscoverer(llm_provider, geocoder or NominatimGeocoder())
        self.enricher = POIEnricher(llm_provider)
        
        self.existing_pois: Set[str] = set()
        
        if existing_kg_path:
            self._load_existing_pois(existing_kg_path)
    
    def _load_existing_pois(self, kg_path: str):
        """Load existing POI names from knowledge graph."""
        # This would parse the KG and extract POI names
        # Simplified for now
        pass
    
    async def augment_area(
        self,
        city: str,
        neighborhood: str,
        classify_existing: bool = True,
        discover_new: bool = True,
        enrich_all: bool = False
    ) -> Dict[str, List]:
        """
        Run full augmentation pipeline for an area.
        
        Returns dict with:
        - classified: POIs with new classifications
        - discovered: Newly discovered POIs
        - enriched: POIs with added attributes
        - triples: Ready-to-add triples for the KG
        """
        results = {
            "classified": [],
            "discovered": [],
            "enriched": [],
            "triples": []
        }
        
        # Step 1: Discover new POIs
        if discover_new:
            print(f"Discovering POIs in {neighborhood}, {city}...")
            new_pois = await self.discoverer.discover_in_area(
                city=city,
                neighborhood=neighborhood,
                existing_pois=self.existing_pois
            )
            
            # Verify each discovered POI
            for poi in new_pois:
                verification = await self.discoverer.verify_poi_exists(poi)
                if verification.verified:
                    poi.confidence = verification.confidence
                    poi.evidence.extend(verification.evidence)
                    results["discovered"].append(poi)
                    
                    # Generate triples
                    triples = self._poi_to_triples(poi)
                    results["triples"].extend(triples)
            
            print(f"  Discovered {len(results['discovered'])} verified POIs")
        
        return results
    
    def _poi_to_triples(self, poi: CandidatePOI) -> List[CandidateTriple]:
        """Convert a POI to knowledge graph triples."""
        triples = []
        uri = poi.to_uri()
        
        # Type triple
        if poi.poi_type:
            triples.append(CandidateTriple(
                subject=uri,
                predicate="rdf:type",
                object=f"uko:{poi.poi_type}",
                confidence=poi.confidence,
                evidence=poi.evidence
            ))
        
        # Name triple
        triples.append(CandidateTriple(
            subject=uri,
            predicate="uko:name",
            object=f'"{poi.name}"',
            confidence=poi.confidence,
            evidence=poi.evidence
        ))
        
        # Coordinate triples
        if poi.has_coordinates:
            triples.append(CandidateTriple(
                subject=uri,
                predicate="uko:latitude",
                object=str(poi.lat),
                confidence=0.95,  # Geocoded coordinates are reliable
                evidence=[SourceEvidence(source=DataSource.COMPUTED, method="geocoding")]
            ))
            triples.append(CandidateTriple(
                subject=uri,
                predicate="uko:longitude",
                object=str(poi.lon),
                confidence=0.95,
                evidence=[SourceEvidence(source=DataSource.COMPUTED, method="geocoding")]
            ))
        
        # Address triple
        if poi.address:
            triples.append(CandidateTriple(
                subject=uri,
                predicate="uko:streetAddress",
                object=f'"{poi.address}"',
                confidence=poi.confidence,
                evidence=poi.evidence
            ))
        
        return triples
