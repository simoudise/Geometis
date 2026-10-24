"""
SPARQL Generator for Geospatial Knowledge Graph

Maps natural language queries to SPARQL using templates.
Ensures city filters are always applied when a city is specified.

Copyright (c) 2025 Synapse Partners, LLC
"""

from typing import Optional, Tuple
from dataclasses import dataclass

try:
    from .entity_extractors import EntityExtractor, ExtractedEntities
    from . import sparql_templates as templates
except ImportError:
    from entity_extractors import EntityExtractor, ExtractedEntities
    import sparql_templates as templates


@dataclass
class GeneratedSPARQL:
    """Result of SPARQL generation."""
    sparql: str
    query_key: str
    city: Optional[str]
    has_city_filter: bool
    description: str


class SPARQLGenerator:
    """
    Generates SPARQL from natural language queries.
    
    Guarantees: When a city is extracted from the query, all
    location-bound queries will include the appropriate city filter.
    """
    
    def __init__(self):
        self.extractor = EntityExtractor()
    
    def generate(self, query: str) -> Optional[GeneratedSPARQL]:
        """
        Generate SPARQL from natural language query.
        
        Args:
            query: Natural language query
            
        Returns:
            GeneratedSPARQL or None if no pattern matches
        """
        entities = self.extractor.extract(query)
        query_lower = query.lower()
        
        # Try patterns in order of specificity
        
        # === SCHOOL COLLISION QUERIES (high priority) ===
        is_school_query = 'school' in query_lower or 'kindergarten' in query_lower
        is_collision_query = 'collision' in query_lower or 'crash' in query_lower or 'accident' in query_lower
        is_ranking_query = 'most' in query_lower or 'have the most' in query_lower
        
        if is_school_query and is_collision_query:
            sparql = templates.schools_with_most_collisions(
                city=entities.city,
                limit=entities.limit
            )
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='schools_most_collisions',
                city=entities.city,
                has_city_filter=entities.city is not None,
                description=f"Schools with collisions{' in ' + entities.city if entities.city else ''}"
            )
        
        # === INFRASTRUCTURE QUERIES ===
        if ('infrastructure' in query_lower or 'pedestrian' in query_lower) and (
            'around' in query_lower or 'near' in query_lower
        ):
            if entities.entity_name:
                if 'school' in query_lower or entities.entity_type == 'School':
                    sparql = templates.infrastructure_near_school(
                        school_name=entities.entity_name,
                        limit=entities.limit
                    )
                else:
                    sparql = templates.infrastructure_near_entity(
                        entity_name=entities.entity_name,
                        limit=entities.limit
                    )
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='infrastructure_near',
                    city=entities.city,
                    has_city_filter=False,  # Uses name matching
                    description=f"Infrastructure near {entities.entity_name}"
                )
        
        # === SCHOOLS NEAR HIN ===
        if 'school' in query_lower and 'hin' in query_lower:
            sparql = templates.schools_near_hin(
                city=entities.city,
                low_income=entities.is_low_income,
                limit=entities.limit
            )
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='schools_near_hin',
                city=entities.city,
                has_city_filter=entities.city is not None,
                description=f"Schools near HIN{' in ' + entities.city if entities.city else ''}"
            )
        
        # === HIN QUERIES ===
        if 'hin' in query_lower:
            if 'senior' in query_lower:
                sparql = templates.hin_near_senior_centers(
                    city=entities.city,
                    limit=entities.limit
                )
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='hin_near_seniors',
                    city=entities.city,
                    has_city_filter=entities.city is not None,
                    description=f"HIN near seniors{' in ' + entities.city if entities.city else ''}"
                )
            elif 'school' in query_lower:
                sparql = templates.hin_near_schools(
                    city=entities.city,
                    limit=entities.limit
                )
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='hin_near_schools',
                    city=entities.city,
                    has_city_filter=entities.city is not None,
                    description=f"HIN near schools{' in ' + entities.city if entities.city else ''}"
                )
            else:
                sparql = templates.find_hin(
                    city=entities.city,
                    limit=entities.limit
                )
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='find_hin',
                    city=entities.city,
                    has_city_filter=entities.city is not None,
                    description=f"Find HIN{' in ' + entities.city if entities.city else ''}"
                )
        
        # === COUNT QUERIES ===
        if 'how many' in query_lower or 'count' in query_lower:
            if 'school' in query_lower:
                sparql = templates.count_schools(city=entities.city)
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='count_schools',
                    city=entities.city,
                    has_city_filter=entities.city is not None,
                    description=f"Count schools{' in ' + entities.city if entities.city else ''}"
                )
            elif 'collision' in query_lower:
                sparql = templates.count_collisions(
                    city=entities.city,
                    severity=entities.severity
                )
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='count_collisions',
                    city=entities.city,
                    has_city_filter=entities.city is not None,
                    description=f"Count collisions{' in ' + entities.city if entities.city else ''}"
                )
        
        # === COLLISION FACTOR QUERIES ===
        if 'primary' in query_lower and 'factor' in query_lower:
            sparql = templates.primary_collision_factors(
                city=entities.city,
                limit=entities.limit
            )
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='collision_factors',
                city=entities.city,
                has_city_filter=entities.city is not None,
                description=f"Collision factors{' in ' + entities.city if entities.city else ''}"
            )
        
        # === COLLISIONS NEAR SCHOOLS ===
        if 'collision' in query_lower and 'near school' in query_lower:
            sparql = templates.collisions_near_schools(
                city=entities.city,
                severity=entities.severity,
                limit=entities.limit
            )
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='collisions_near_schools',
                city=entities.city,
                has_city_filter=entities.city is not None,
                description=f"Collisions near schools{' in ' + entities.city if entities.city else ''}"
            )
        
        # === ROAD QUERIES ===
        if 'road' in query_lower and ('most collision' in query_lower or 'most fatal' in query_lower):
            sparql = templates.roads_with_most_collisions(
                city=entities.city,
                fatal_only=entities.severity == 'fatal',
                limit=entities.limit
            )
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='roads_most_collisions',
                city=entities.city,
                has_city_filter=entities.city is not None,
                description=f"Roads with most collisions{' in ' + entities.city if entities.city else ''}"
            )
        
        # === TRANSIT QUERIES ===
        if ('transit' in query_lower or 'bus' in query_lower) and 'school' in query_lower:
            sparql = templates.transit_stops_near_schools(
                city=entities.city,
                limit=entities.limit
            )
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='transit_near_schools',
                city=entities.city,
                has_city_filter=entities.city is not None,
                description=f"Transit near schools{' in ' + entities.city if entities.city else ''}"
            )
        
        # === BART QUERIES ===
        if 'bart' in query_lower:
            if entities.entity_name:
                sparql = templates.bart_station_infrastructure(
                    station_name=entities.entity_name,
                    limit=entities.limit
                )
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='bart_infrastructure',
                    city=entities.city,
                    has_city_filter=False,
                    description=f"Infrastructure at {entities.entity_name} BART"
                )
            else:
                sparql = templates.list_bart_stations(limit=entities.limit)
                return GeneratedSPARQL(
                    sparql=sparql,
                    query_key='list_bart',
                    city=entities.city,
                    has_city_filter=False,
                    description="List BART stations"
                )
        
        # === SCHEMA QUERIES ===
        if 'type' in query_lower and ('what' in query_lower or 'list' in query_lower):
            sparql = templates.list_classes()
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='list_classes',
                city=None,
                has_city_filter=False,
                description="List ontology classes"
            )
        
        if 'relation' in query_lower and ('what' in query_lower or 'list' in query_lower):
            sparql = templates.list_relations()
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='list_relations',
                city=None,
                has_city_filter=False,
                description="List ontology relations"
            )
        
        # === FALLBACK: Find schools in city ===
        if 'school' in query_lower and entities.city:
            sparql = templates.find_schools(
                city=entities.city,
                limit=entities.limit
            )
            return GeneratedSPARQL(
                sparql=sparql,
                query_key='find_schools',
                city=entities.city,
                has_city_filter=True,
                description=f"Find schools in {entities.city}"
            )
        
        return None
    
    def validate_city_filter(self, generated: GeneratedSPARQL, entities: ExtractedEntities) -> bool:
        """
        Validate that city filter is present when expected.
        
        Returns True if valid, False if city was extracted but filter is missing.
        """
        if entities.city and not generated.has_city_filter:
            # Check if this query type should have city filter
            # Some queries use name matching instead (infrastructure around X)
            if generated.query_key in ['infrastructure_near', 'bart_infrastructure']:
                return True  # These use name matching, not city filter
            return False
        return True


def generate_sparql(query: str) -> Optional[GeneratedSPARQL]:
    """Convenience function to generate SPARQL."""
    generator = SPARQLGenerator()
    return generator.generate(query)
