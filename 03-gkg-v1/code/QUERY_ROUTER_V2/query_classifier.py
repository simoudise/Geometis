"""
Query Classifier for Geospatial Knowledge Graph

Classifies natural language queries into types:
- AGGREGATION: count, sum, "most", rankings
- LOOKUP: find specific entities
- SIMILARITY: find similar entities
- CLUSTERING: group entities
- PREDICTION: predict missing links
- SCHEMA: what types/relations exist

Copyright (c) 2025 Synapse Partners, LLC
"""

from enum import Enum
from dataclasses import dataclass
from typing import List
import re


class QueryType(Enum):
    """Types of queries the system handles."""
    # Knowledge Graph queries (SPARQL)
    AGGREGATION = "aggregation"      # count, rankings, "most"
    LOOKUP = "lookup"                # find entities
    MULTI_HOP = "multi_hop"          # traverse relationships
    SCHEMA = "schema"                # TBox: types, relations
    
    # Embedding queries
    SIMILARITY = "similarity"        # find similar entities
    CLUSTERING = "clustering"        # group entities
    PREDICTION = "prediction"        # predict missing links
    
    # Combined/Other
    INFRASTRUCTURE = "infrastructure"  # infrastructure around entity
    UNKNOWN = "unknown"


@dataclass  
class Classification:
    """Result of query classification."""
    query_type: QueryType
    confidence: float
    matched_pattern: str
    needs_kg: bool
    needs_embeddings: bool


class QueryClassifier:
    """Classifies queries to determine routing."""
    
    # Pattern definitions (order matters - more specific first)
    PATTERNS = [
        # Schema queries
        (QueryType.SCHEMA, [
            r'what types',
            r'what kinds',
            r'what classes',
            r'what relations',
            r'what properties',
            r'list.*types',
            r'show.*schema',
        ]),
        
        # Similarity (embeddings)
        (QueryType.SIMILARITY, [
            r'similar to',
            r'similar.*profile',
            r'most similar',
            r'like\s+\w+\s+school',
            r'comparable',
            r'resembles',
        ]),
        
        # Clustering (embeddings)
        (QueryType.CLUSTERING, [
            r'cluster',
            r'group.*by',
            r'categorize',
            r'segment',
            r'safety profile',
            r'risk profile',
        ]),
        
        # Prediction (embeddings)
        (QueryType.PREDICTION, [
            r'predict which',
            r'predict.*need',
            r'likely to need',
            r'should have',
            r'probably need',
            r'candidates for',
            r'likely.*lack',
        ]),
        
        # Infrastructure queries (specific entity)
        (QueryType.INFRASTRUCTURE, [
            r'infrastructure.*around',
            r'infrastructure.*near',
            r'pedestrian.*around',
            r'pedestrian.*near',
            r'around\s+[A-Z]',
            r'near\s+[A-Z].*infrastructure',
        ]),
        
        # Aggregation (count, rankings)
        (QueryType.AGGREGATION, [
            r'how many',
            r'count',
            r'total',
            r'most collision',
            r'have the most',
            r'highest',
            r'lowest',
            r'primary.*factor',
            r'by severity',
            r'ranking',
        ]),
        
        # Multi-hop (relationships)
        (QueryType.MULTI_HOP, [
            r'near\s+school.*hin',
            r'hin.*near.*school',
            r'near\s+senior',
            r'that\s+lack',
            r'without\s+crossing',
            r'in\s+low.?income',
        ]),
        
        # Lookup (find entities)
        (QueryType.LOOKUP, [
            r'find\s+all',
            r'find\s+schools',
            r'find\s+roads',
            r'find\s+hin',
            r'list\s+schools',
            r'list\s+roads',
            r'which\s+schools',
            r'which\s+roads',
            r'show\s+me',
        ]),
    ]
    
    def classify(self, query: str) -> Classification:
        """
        Classify a query to determine type and routing.
        
        Args:
            query: Natural language query
            
        Returns:
            Classification with type, confidence, and requirements
        """
        query_lower = query.lower()
        
        for query_type, patterns in self.PATTERNS:
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return Classification(
                        query_type=query_type,
                        confidence=0.85,
                        matched_pattern=pattern,
                        needs_kg=self._needs_kg(query_type),
                        needs_embeddings=self._needs_embeddings(query_type)
                    )
        
        # Default to lookup
        return Classification(
            query_type=QueryType.LOOKUP,
            confidence=0.5,
            matched_pattern="",
            needs_kg=True,
            needs_embeddings=False
        )
    
    def _needs_kg(self, query_type: QueryType) -> bool:
        """Check if query type requires knowledge graph."""
        return query_type in [
            QueryType.AGGREGATION,
            QueryType.LOOKUP,
            QueryType.MULTI_HOP,
            QueryType.SCHEMA,
            QueryType.INFRASTRUCTURE,
        ]
    
    def _needs_embeddings(self, query_type: QueryType) -> bool:
        """Check if query type requires embeddings."""
        return query_type in [
            QueryType.SIMILARITY,
            QueryType.CLUSTERING,
            QueryType.PREDICTION,
        ]


def classify_query(query: str) -> Classification:
    """Convenience function to classify a query."""
    classifier = QueryClassifier()
    return classifier.classify(query)
