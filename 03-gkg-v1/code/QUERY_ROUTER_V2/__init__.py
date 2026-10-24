"""
Query Router Package for Geospatial Knowledge Graph

A clean, modular query routing system that:
- Classifies natural language queries
- Generates SPARQL with proper city filters
- Executes against KG and embeddings
- Formats results for transportation planners

Copyright (c) 2025 Synapse Partners, LLC
"""

try:
    from .router import QueryRouter, QueryResult, create_router
    from .query_classifier import QueryClassifier, QueryType, Classification, classify_query
    from .sparql_generator import SPARQLGenerator, GeneratedSPARQL, generate_sparql
    from .entity_extractors import EntityExtractor, ExtractedEntities, extract_entities
except ImportError:
    from router import QueryRouter, QueryResult, create_router
    from query_classifier import QueryClassifier, QueryType, Classification, classify_query
    from sparql_generator import SPARQLGenerator, GeneratedSPARQL, generate_sparql
    from entity_extractors import EntityExtractor, ExtractedEntities, extract_entities

__all__ = [
    # Main router
    'QueryRouter',
    'QueryResult', 
    'create_router',
    
    # Classification
    'QueryClassifier',
    'QueryType',
    'Classification',
    'classify_query',
    
    # SPARQL generation
    'SPARQLGenerator',
    'GeneratedSPARQL',
    'generate_sparql',
    
    # Entity extraction
    'EntityExtractor',
    'ExtractedEntities',
    'extract_entities',
]
