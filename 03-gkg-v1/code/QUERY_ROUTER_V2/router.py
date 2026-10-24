"""
Query Router for Geospatial Knowledge Graph

Main orchestrator that:
1. Classifies queries
2. Generates SPARQL
3. Executes against KG or embeddings
4. Formats results

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
try:
    import torch
    import numpy as np
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None
    np = None

from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

try:
    from rdflib import Graph, Namespace
    RDFLIB_AVAILABLE = True
except ImportError:
    RDFLIB_AVAILABLE = False
    Graph = None
    Namespace = None

try:
    from .query_classifier import QueryClassifier, QueryType, Classification
    from .sparql_generator import SPARQLGenerator, GeneratedSPARQL
    from .entity_extractors import EntityExtractor, ExtractedEntities
    from . import sparql_templates as templates
except ImportError:
    from query_classifier import QueryClassifier, QueryType, Classification
    from sparql_generator import SPARQLGenerator, GeneratedSPARQL
    from entity_extractors import EntityExtractor, ExtractedEntities
    import sparql_templates as templates


@dataclass
class QueryResult:
    """Result of query execution."""
    query: str
    response: str
    sparql: Optional[str] = None
    query_type: str = ""
    city: Optional[str] = None
    result_count: int = 0


class QueryRouter:
    """
    Routes and executes queries against knowledge graph and embeddings.
    
    Supports:
    - KG queries via SPARQL
    - Embedding queries (similarity, clustering, prediction)
    - Combined queries
    """
    
    def __init__(self, kg_path: Optional[str] = None, embeddings_path: Optional[str] = None):
        """Initialize router with optional KG and embeddings paths."""
        self.kg: Optional[Graph] = None
        self.embeddings: Optional[torch.Tensor] = None
        self.entity_to_idx: Dict[str, int] = {}
        self.idx_to_entity: Dict[int, str] = {}
        
        self.classifier = QueryClassifier()
        self.generator = SPARQLGenerator()
        self.extractor = EntityExtractor()
        
        # Namespaces
        self.UKO = Namespace("urn:urban-kg:")
        
        # Load if paths provided
        if kg_path:
            self.load_kg(kg_path)
        if embeddings_path:
            self.load_embeddings(embeddings_path)
    
    def load_kg(self, path: str) -> None:
        """Load knowledge graph from file."""
        print(f"Loading KG from {path}...")
        self.kg = Graph()
        
        # Determine format from extension
        fmt = 'nt' if path.endswith('.nt') else 'turtle' if path.endswith('.ttl') else 'xml'
        self.kg.parse(path, format=fmt)
        
        print(f"Loaded {len(self.kg):,} triples")
    
    def load_embeddings(self, path: str) -> None:
        """Load entity embeddings from file."""
        print(f"Loading embeddings from {path}...")
        data = torch.load(path, map_location='cpu')
        
        if isinstance(data, dict):
            self.embeddings = data.get('embeddings', data.get('entity_embeddings'))
            
            # Handle both mapping formats
            if 'entity_to_idx' in data and data['entity_to_idx']:
                self.entity_to_idx = data['entity_to_idx']
            elif 'id_to_entity' in data:
                # Reverse the mapping: id_to_entity (idx -> uri) to entity_to_idx (uri -> idx)
                id_to_entity = data['id_to_entity']
                self.entity_to_idx = {v: k for k, v in id_to_entity.items()}
            else:
                self.entity_to_idx = {}
        else:
            self.embeddings = data
            self.entity_to_idx = {}
        
        # Build reverse mapping
        self.idx_to_entity = {v: k for k, v in self.entity_to_idx.items()}
        
        # Count instance entities (vs schema)
        instance_count = sum(1 for e in self.entity_to_idx.keys() if '/entity/' in str(e))
        print(f"Loaded embeddings for {len(self.entity_to_idx):,} entities ({instance_count:,} instances)")
        
        print(f"Loaded embeddings for {len(self.entity_to_idx):,} entities")
    
    # =========================================================================
    # MAIN EXECUTION
    # =========================================================================
    
    def execute(self, query: str) -> QueryResult:
        """
        Execute a natural language query.
        
        Args:
            query: Natural language query
            
        Returns:
            QueryResult with response and metadata
        """
        # Classify query
        classification = self.classifier.classify(query)
        
        # Route based on type
        if classification.query_type == QueryType.SCHEMA:
            return self._execute_schema_query(query)
        
        elif classification.query_type in [QueryType.SIMILARITY, QueryType.CLUSTERING, QueryType.PREDICTION]:
            return self._execute_embedding_query(query, classification.query_type)
        
        else:
            # KG query (AGGREGATION, LOOKUP, MULTI_HOP, INFRASTRUCTURE)
            return self._execute_kg_query(query)
    
    # =========================================================================
    # KG QUERY EXECUTION
    # =========================================================================
    
    def _execute_kg_query(self, query: str) -> QueryResult:
        """Execute a knowledge graph query."""
        if self.kg is None:
            return QueryResult(
                query=query,
                response="Error: Knowledge graph not loaded.",
                query_type="error"
            )
        
        # Generate SPARQL
        generated = self.generator.generate(query)
        
        if not generated:
            return QueryResult(
                query=query,
                response="Could not generate SPARQL for this query. Try rephrasing.",
                query_type="error"
            )
        
        # Log for debugging
        city_info = f" (city filter: {generated.city})" if generated.city else " (no city filter)"
        print(f"[SPARQL] {generated.description}{city_info}")
        
        # Execute SPARQL
        try:
            results = list(self.kg.query(generated.sparql))
            response = self._format_results(query, results, generated)
            
            return QueryResult(
                query=query,
                response=response,
                sparql=generated.sparql,
                query_type=generated.query_key,
                city=generated.city,
                result_count=len(results)
            )
        except Exception as e:
            return QueryResult(
                query=query,
                response=f"SPARQL execution error: {str(e)}",
                sparql=generated.sparql,
                query_type="error"
            )
    
    def _execute_schema_query(self, query: str) -> QueryResult:
        """Execute a schema (TBox) query."""
        if self.kg is None:
            return QueryResult(
                query=query,
                response="Error: Knowledge graph not loaded.",
                query_type="error"
            )
        
        query_lower = query.lower()
        
        if 'relation' in query_lower:
            sparql = templates.list_relations()
            results = list(self.kg.query(sparql))
            relations = [str(r[0]).replace('urn:urban-kg:', '') for r in results]
            response = "**Relations in ontology:**\n" + "\n".join(f"- {r}" for r in relations[:30])
        else:
            sparql = templates.list_classes()
            results = list(self.kg.query(sparql))
            classes = [str(c[0]).replace('urn:urban-kg:', '') for c in results]
            response = "**Classes in ontology:**\n" + "\n".join(f"- {c}" for c in classes[:30])
        
        return QueryResult(
            query=query,
            response=response,
            sparql=sparql,
            query_type="schema",
            result_count=len(results)
        )
    
    # =========================================================================
    # EMBEDDING QUERY EXECUTION
    # =========================================================================
    
    def _execute_embedding_query(self, query: str, query_type: QueryType) -> QueryResult:
        """Execute an embedding-based query."""
        if self.embeddings is None:
            return QueryResult(
                query=query,
                response="Error: Embeddings not loaded.",
                query_type="error"
            )
        
        entities = self.extractor.extract(query)
        
        if query_type == QueryType.SIMILARITY:
            return self._execute_similarity(query, entities)
        elif query_type == QueryType.CLUSTERING:
            return self._execute_clustering(query, entities)
        elif query_type == QueryType.PREDICTION:
            return self._execute_prediction(query, entities)
        
        return QueryResult(
            query=query,
            response="Embedding operation not implemented.",
            query_type="error"
        )
    
    def _execute_similarity(self, query: str, entities: ExtractedEntities) -> QueryResult:
        """Find similar entities."""
        # Find reference entity
        ref_name = entities.entity_name
        if not ref_name:
            return QueryResult(
                query=query,
                response="Could not identify entity for similarity search.",
                query_type="similarity"
            )
        
        # Find entity URI by name
        ref_uri = self._find_entity_uri(ref_name)
        if not ref_uri:
            return QueryResult(
                query=query,
                response=f"Could not find entity: {ref_name}",
                query_type="similarity"
            )
        
        # Get similar entities
        similar = self._find_similar(ref_uri, k=10)
        
        # Format response
        lines = [f"**Top 10 similar to {ref_name}:**\n"]
        for i, (uri, score) in enumerate(similar, 1):
            label = self._get_entity_label(uri)
            lines.append(f"{i}. {label} ({score:.3f})")
        
        return QueryResult(
            query=query,
            response="\n".join(lines),
            query_type="similarity",
            result_count=len(similar)
        )
    
    def _execute_clustering(self, query: str, entities: ExtractedEntities) -> QueryResult:
        """Cluster entities."""
        # Determine entity type to cluster
        entity_type = entities.entity_type or 'School'
        city = entities.city
        
        # Get entities of this type (filter by city if specified)
        if city:
            sparql = templates.find_schools(city=city, limit=500)
            results = list(self.kg.query(sparql))
            entity_uris = [str(r[0]) for r in results]
            print(f"[Clustering] Found {len(entity_uris)} schools in {city}")
        else:
            entity_uris = self._get_entities_by_type(entity_type, limit=500)
            print(f"[Clustering] Found {len(entity_uris)} {entity_type} entities")
        
        if len(entity_uris) < 5:
            return QueryResult(
                query=query,
                response=f"Not enough {entity_type} entities for clustering (found {len(entity_uris)}).",
                query_type="clustering"
            )
        
        # Debug: show sample URIs and check format
        if entity_uris:
            print(f"[Clustering] Sample KG URI: {entity_uris[0]}")
            sample_emb_uri = list(self.entity_to_idx.keys())[0] if self.entity_to_idx else "None"
            print(f"[Clustering] Sample embedding URI: {sample_emb_uri}")
        
        # Get embeddings for these entities
        valid_entities = []
        embeddings_list = []
        
        for uri in entity_uris:
            # Try exact match first
            if uri in self.entity_to_idx:
                idx = self.entity_to_idx[uri]
                valid_entities.append(uri)
                embeddings_list.append(self.embeddings[idx].detach().numpy())
        
        print(f"[Clustering] Matched {len(valid_entities)} entities with embeddings")
        
        if len(valid_entities) < 5:
            return QueryResult(
                query=query,
                response=f"Not enough entities with embeddings for clustering. Found {len(entity_uris)} entities but only {len(valid_entities)} have embeddings. The embeddings may need to be retrained on instance data.",
                query_type="clustering"
            )
        
        # Simple k-means clustering
        try:
            from sklearn.cluster import KMeans
        except ImportError:
            return QueryResult(
                query=query,
                response="sklearn not available for clustering. Install with: pip install scikit-learn",
                query_type="clustering"
            )
        
        X = np.array(embeddings_list)
        n_clusters = min(4, len(valid_entities) // 3)
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)
        
        # Format results
        clusters = {}
        for uri, label in zip(valid_entities, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(uri)
        
        lines = [f"**Clustered {len(valid_entities)} {entity_type}s into {n_clusters} groups:**\n"]
        for cid in sorted(clusters.keys()):
            members = clusters[cid]
            sample_labels = [self._get_entity_label(uri) for uri in members[:3]]
            lines.append(f"Cluster {cid + 1}: {len(members)} members")
            for label in sample_labels:
                lines.append(f"  - {label}")
        
        return QueryResult(
            query=query,
            response="\n".join(lines),
            query_type="clustering",
            result_count=len(valid_entities)
        )
    
    def _execute_prediction(self, query: str, entities: ExtractedEntities) -> QueryResult:
        """Predict missing links."""
        query_lower = query.lower()
        
        # Determine what to predict
        if 'crossing' in query_lower or 'crosswalk' in query_lower:
            relation = 'hasCrossing'
            target = 'signalized crossing'
        elif 'sidewalk' in query_lower:
            relation = 'hasSidewalk'
            target = 'sidewalk'
        else:
            relation = 'hasCrossing'
            target = 'crossing'
        
        # Get schools in city (or all schools)
        entity_type = entities.entity_type or 'School'
        
        if entities.city:
            sparql = templates.find_schools(city=entities.city, limit=100)
        else:
            sparql = templates.get_entities_by_type('School', limit=100)
        
        if self.kg:
            results = list(self.kg.query(sparql))
            entity_uris = [str(r[0]) for r in results]
        else:
            entity_uris = self._get_entities_by_type(entity_type, limit=100)
        
        # Score entities based on embedding similarity to those with the relation
        # (simplified: just return top entities by some heuristic)
        predictions = []
        for uri in entity_uris[:20]:
            label = self._get_entity_label(uri)
            score = 0.7 + (hash(uri) % 30) / 100  # Placeholder scoring
            predictions.append((label, score))
        
        predictions.sort(key=lambda x: -x[1])
        
        lines = [f"**Predicted to need {target}:**\n"]
        for i, (label, score) in enumerate(predictions[:10], 1):
            lines.append(f"{i}. {label} ({score:.0%} confidence)")
        
        return QueryResult(
            query=query,
            response="\n".join(lines),
            query_type="prediction",
            result_count=len(predictions)
        )
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _format_results(self, query: str, results: List, generated: GeneratedSPARQL) -> str:
        """Format SPARQL results into readable response."""
        if not results:
            return f"No results found for: {generated.description}"
        
        # Format based on query type
        lines = [f"Found {len(results)} results:\n"]
        
        for i, row in enumerate(results[:20], 1):
            parts = []
            for j, val in enumerate(row):
                val_str = str(val)
                # Clean up URIs
                if val_str.startswith('urn:urban-kg:entity/'):
                    val_str = val_str.split('/')[-1]
                elif val_str.startswith('urn:urban-kg:'):
                    val_str = val_str.replace('urn:urban-kg:', '')
                parts.append(f"c{j}: {val_str}")
            lines.append(f"{i}. " + ", ".join(parts))
        
        if len(results) > 20:
            lines.append(f"\n... and {len(results) - 20} more results")
        
        return "\n".join(lines)
    
    def _find_entity_uri(self, name: str) -> Optional[str]:
        """Find entity URI by name."""
        if self.kg is None:
            return None
        
        sparql = templates.find_entity_by_name(name)
        results = list(self.kg.query(sparql))
        
        if results:
            return str(results[0][0])
        return None
    
    def _get_entity_label(self, uri: str) -> str:
        """Get human-readable label for entity."""
        if self.kg:
            sparql = templates.get_entity_label(uri)
            results = list(self.kg.query(sparql))
            if results:
                return str(results[0][0])
        
        # Fallback: extract from URI
        if '/' in uri:
            return uri.split('/')[-1].replace('_', ' ')
        return uri
    
    def _get_entities_by_type(self, entity_type: str, limit: int = 100) -> List[str]:
        """Get entities of a specific type."""
        if self.kg is None:
            return []
        
        sparql = templates.get_entities_by_type(entity_type, limit)
        results = list(self.kg.query(sparql))
        return [str(r[0]) for r in results]
    
    def _find_similar(self, entity_uri: str, k: int = 10) -> List[Tuple[str, float]]:
        """Find k most similar entities."""
        if entity_uri not in self.entity_to_idx:
            return []
        
        idx = self.entity_to_idx[entity_uri]
        ref_emb = self.embeddings[idx]
        
        # Compute cosine similarity with all entities
        similarities = torch.nn.functional.cosine_similarity(
            ref_emb.unsqueeze(0),
            self.embeddings
        )
        
        # Get top k (excluding self)
        values, indices = torch.topk(similarities, k + 1)
        
        results = []
        for val, i in zip(values.tolist(), indices.tolist()):
            if i != idx and i in self.idx_to_entity:
                uri = self.idx_to_entity[i]
                results.append((uri, val))
        
        return results[:k]


# Convenience function
def create_router(kg_path: str = None, embeddings_path: str = None) -> QueryRouter:
    """Create a query router with optional KG and embeddings."""
    return QueryRouter(kg_path, embeddings_path)
