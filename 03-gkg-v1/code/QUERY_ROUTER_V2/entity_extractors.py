"""
Entity Extractors for Query Processing

Extracts structured information from natural language queries:
- City names (project-specific: 5 Contra Costa cities)
- Entity types (school, road, collision, etc.)
- Entity names
- Modifiers (fatal, severe, etc.)

Copyright (c) 2025 Synapse Partners, LLC
"""

import re
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class ExtractedEntities:
    """Entities extracted from a query."""
    city: Optional[str] = None
    entity_type: Optional[str] = None
    entity_name: Optional[str] = None
    severity: Optional[str] = None  # 'fatal', 'severe', or None
    is_low_income: bool = False
    limit: int = 20


class EntityExtractor:
    """Extracts entities and parameters from natural language queries."""
    
    # Project scope: 5 cities in Contra Costa County
    VALID_CITIES = [
        'Antioch',
        'Pittsburg', 
        'Richmond',
        'Walnut Creek',
        'Pleasant Hill'
    ]
    
    # Entity type keywords to ontology types
    ENTITY_TYPE_MAP = {
        # Schools
        'school': 'School',
        'schools': 'School',
        'kindergarten': 'Kindergarten',
        'kindergartens': 'Kindergarten',
        'elementary': 'School',
        'middle school': 'School',
        'high school': 'School',
        
        # Transportation
        'road': 'Road',
        'roads': 'Road',
        'street': 'Road',
        'streets': 'Road',
        'highway': 'Road',
        
        # Collisions
        'collision': 'Collision',
        'collisions': 'Collision',
        'crash': 'Collision',
        'crashes': 'Collision',
        'accident': 'Collision',
        'accidents': 'Collision',
        
        # Transit
        'transit': 'BusStop',
        'bus': 'BusStop',
        'bus stop': 'BusStop',
        'bus stops': 'BusStop',
        'bart': 'TrainStation',
        'train': 'TrainStation',
        'rail': 'TrainStation',
        'station': 'TrainStation',
        
        # Safety
        'hin': 'HighInjuryNetwork',
        'high injury': 'HighInjuryNetwork',
        'high injury network': 'HighInjuryNetwork',
        
        # Census
        'tract': 'CensusTract',
        'census tract': 'CensusTract',
        'census': 'CensusTract',
        
        # POIs
        'senior': 'SeniorCenter',
        'senior center': 'SeniorCenter',
        'hospital': 'Hospital',
        'hospitals': 'Hospital',
        
        # Infrastructure
        'sidewalk': 'Sidewalk',
        'sidewalks': 'Sidewalk',
        'crossing': 'Crossing',
        'crosswalk': 'Crossing',
        'crosswalks': 'Crossing',
    }
    
    def extract(self, query: str) -> ExtractedEntities:
        """
        Extract all entities from a query.
        
        Args:
            query: Natural language query
            
        Returns:
            ExtractedEntities with extracted information
        """
        result = ExtractedEntities()
        query_lower = query.lower()
        
        # Extract city
        result.city = self._extract_city(query)
        
        # Extract entity type
        result.entity_type = self._extract_entity_type(query_lower)
        
        # Extract severity
        if 'fatal' in query_lower:
            result.severity = 'fatal'
        elif 'severe' in query_lower:
            result.severity = 'severe'
        
        # Check low income filter
        result.is_low_income = 'low-income' in query_lower or 'low income' in query_lower
        
        # Extract entity name
        result.entity_name = self._extract_entity_name(query)
        
        # Extract limit
        result.limit = self._extract_limit(query_lower)
        
        return result
    
    def _extract_city(self, query: str) -> Optional[str]:
        """
        Extract city name from query.
        
        Returns city with proper capitalization if found.
        """
        query_lower = query.lower()
        
        for city in self.VALID_CITIES:
            if city.lower() in query_lower:
                return city  # Return with original capitalization
        
        return None
    
    def _extract_entity_type(self, query_lower: str) -> Optional[str]:
        """Extract primary entity type from query."""
        # Check longer phrases first to avoid partial matches
        sorted_items = sorted(
            self.ENTITY_TYPE_MAP.items(), 
            key=lambda x: -len(x[0])
        )
        
        for phrase, entity_type in sorted_items:
            if phrase in query_lower:
                return entity_type
        
        return None
    
    def _extract_entity_name(self, query: str) -> Optional[str]:
        """
        Extract specific entity name from query.
        
        Looks for patterns like:
        - "around Lincoln Elementary"
        - "near Washington School"
        - "at the Walnut Creek BART"
        """
        # Patterns to match entity names
        patterns = [
            r'around\s+([A-Z][A-Za-z\s]+?)(?:\s+school|\s+elementary|\s+middle|\s+high|\?|\.|$)',
            r'near\s+([A-Z][A-Za-z\s]+?)(?:\s+school|\s+elementary|\s+middle|\s+high|\?|\.|$)',
            r'at\s+(?:the\s+)?([A-Z][A-Za-z\s]+?)(?:\s+bart|\s+station|\?|\.|$)',
            r'for\s+([A-Z][A-Za-z\s]+?)(?:\s+school|\s+elementary|\?|\.|$)',
            r'to\s+([A-Z][A-Za-z\s]+?)(?:\s+school|\s+elementary|\?|\.|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                name = match.group(1).strip()
                # Filter out common false positives
                if name.lower() not in ['the', 'a', 'an', 'this', 'that']:
                    return name
        
        # Also check for BART station names
        bart_stations = [
            'walnut creek', 'pleasant hill', 'concord', 'pittsburg',
            'antioch', 'richmond', 'el cerrito'
        ]
        query_lower = query.lower()
        for station in bart_stations:
            if station in query_lower:
                return station
        
        return None
    
    def _extract_limit(self, query_lower: str) -> int:
        """Extract result limit from query."""
        # Look for "top N" or "first N" patterns
        match = re.search(r'(?:top|first)\s+(\d+)', query_lower)
        if match:
            return min(int(match.group(1)), 100)
        return 20  # Default


def extract_entities(query: str) -> ExtractedEntities:
    """Convenience function to extract entities from a query."""
    extractor = EntityExtractor()
    return extractor.extract(query)
