"""
Enhanced POI Resolver with Full Embedding Integration
Uses geospatial embeddings as primary ranking mechanism
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from poi_resolver import POIResolver, POICandidate


class EmbeddingEnhancedPOIResolver(POIResolver):
    """
    Enhanced POI Resolver that fully leverages geospatial embeddings
    
    Strategy:
    1. Spatial search for nearby POIs (within radius)
    2. For each candidate, compute embedding similarity
    3. Combine spatial + semantic + contextual signals
    4. Rank by composite score
    """
    
    def __init__(self, kg_file: str, embeddings_file: str, 
                 embedding_weight: float = 0.5):
        """
        Initialize with mandatory embeddings
        
        Args:
            kg_file: Knowledge graph TTL file
            embeddings_file: Entity embeddings CSV (REQUIRED)
            embedding_weight: Weight for embedding similarity (0-1)
                            0.5 = equal weight with spatial distance
        """
        super().__init__(kg_file, embeddings_file)
        
        if self.embeddings is None:
            raise ValueError("Embeddings file is required for enhanced resolver")
        
        self.embedding_weight = embedding_weight
        self.spatial_weight = 1.0 - embedding_weight
        
        print(f"✓ Embedding-enhanced resolver initialized")
        print(f"  Embedding weight: {embedding_weight:.1%}")
        print(f"  Spatial weight: {self.spatial_weight:.1%}")
        
        # Build embedding matrix for fast similarity computation
        self._build_embedding_matrix()
    
    def _build_embedding_matrix(self):
        """Pre-compute embedding matrix for vectorized operations"""
        self.embedding_matrix = self.embeddings.values
        self.embedding_uris = list(self.embedding_index.keys())
        print(f"  Built embedding matrix: {self.embedding_matrix.shape}")
    
    def resolve_location(self, 
                        lat: float, 
                        lon: float,
                        context: Optional[Dict] = None,
                        max_candidates: int = 5,
                        min_confidence: float = 0.3) -> List[POICandidate]:
        """
        Enhanced resolution using embeddings as primary ranking
        """
        context = context or {}
        
        # Step 1: Spatial search (cast wide net)
        search_radius = self.SEARCH_RADII['default'] * 2  # Wider search
        nearby_pois = self._spatial_search(lat, lon, radius=search_radius)
        
        if not nearby_pois:
            self.logger.warning(f"No POIs found near ({lat}, {lon})")
            return []
        
        # Step 2: Create location embedding context
        # This is a simple approach - could be enhanced with more sophisticated methods
        location_embedding = self._create_location_embedding(lat, lon, nearby_pois, context)
        
        # Step 3: Compute similarity scores for all candidates
        candidates = []
        for poi in nearby_pois:
            if poi['uri'] not in self.embedding_index:
                continue  # Skip POIs without embeddings
            
            # Get POI embedding
            poi_idx = self.embedding_index[poi['uri']]
            poi_embedding = self.embeddings.iloc[poi_idx].values
            
            # Compute embedding similarity
            embedding_sim = self._cosine_similarity(location_embedding, poi_embedding)
            
            # Compute spatial confidence
            spatial_conf = self._distance_confidence(poi['distance'])
            
            # Compute POI importance
            poi_type_short = poi['type'].split(':')[-1]
            importance = self.POI_IMPORTANCE.get(poi_type_short, self.POI_IMPORTANCE['default'])
            
            # Contextual boost
            context_boost = 1.0
            if context:
                context_boost = self._contextual_matching(poi, context)
            
            # Combined confidence score
            # Formula: (spatial_weight * spatial) + (embedding_weight * semantic) * importance * context
            confidence = (
                self.spatial_weight * spatial_conf + 
                self.embedding_weight * embedding_sim
            ) * importance * context_boost
            
            candidate = POICandidate(
                uri=poi['uri'],
                name=poi['name'],
                poi_type=poi['type'],
                coordinates=(poi['lat'], poi['lon']),
                distance_meters=poi['distance'],
                confidence=min(confidence, 1.0),  # Cap at 1.0
                resolution_method='embedding_enhanced',
                embedding_similarity=embedding_sim,
                attributes=poi.get('attributes', {})
            )
            
            candidates.append(candidate)
        
        # Sort by confidence and filter
        candidates.sort(key=lambda x: x.confidence, reverse=True)
        candidates = [c for c in candidates if c.confidence >= min_confidence]
        
        return candidates[:max_candidates]
    
    def _create_location_embedding(self, lat: float, lon: float, 
                                   nearby_pois: List[Dict],
                                   context: Dict) -> np.ndarray:
        """
        Create embedding representation for the query location
        
        Strategy: Aggregate embeddings of nearby POIs weighted by distance
        This creates a "semantic fingerprint" of the location
        """
        if not nearby_pois:
            # Fallback: return mean embedding
            return np.mean(self.embedding_matrix, axis=0)
        
        # Get embeddings for nearby POIs
        embeddings_list = []
        weights = []
        
        for poi in nearby_pois[:10]:  # Top 10 nearest
            if poi['uri'] in self.embedding_index:
                poi_idx = self.embedding_index[poi['uri']]
                poi_emb = self.embeddings.iloc[poi_idx].values
                embeddings_list.append(poi_emb)
                
                # Weight by inverse distance (closer = higher weight)
                weight = 1.0 / (poi['distance'] + 1.0)  # +1 to avoid division by zero
                weights.append(weight)
        
        if not embeddings_list:
            return np.mean(self.embedding_matrix, axis=0)
        
        # Weighted average of nearby embeddings
        embeddings_array = np.array(embeddings_list)
        weights_array = np.array(weights)
        weights_array = weights_array / weights_array.sum()  # Normalize
        
        location_embedding = np.average(embeddings_array, axis=0, weights=weights_array)
        
        return location_embedding
    
    def _cosine_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings"""
        dot_product = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot_product / (norm1 * norm2)
        
        # Normalize to [0, 1]
        return (similarity + 1) / 2
    
    def find_similar_pois(self, reference_poi_uri: str, 
                         top_k: int = 10,
                         poi_type_filter: Optional[str] = None) -> List[POICandidate]:
        """
        Find POIs similar to a reference POI using embeddings
        Useful for: "Find places similar to X"
        """
        if reference_poi_uri not in self.embedding_index:
            self.logger.error(f"Reference POI not in embeddings: {reference_poi_uri}")
            return []
        
        # Get reference embedding
        ref_idx = self.embedding_index[reference_poi_uri]
        ref_embedding = self.embeddings.iloc[ref_idx].values
        
        # Compute similarity to all other POIs
        similarities = []
        for poi in self.spatial_index:
            if poi['uri'] == reference_poi_uri:
                continue  # Skip self
            
            if poi['uri'] not in self.embedding_index:
                continue
            
            # Apply type filter if specified
            if poi_type_filter and poi_type_filter not in poi['type']:
                continue
            
            poi_idx = self.embedding_index[poi['uri']]
            poi_embedding = self.embeddings.iloc[poi_idx].values
            
            similarity = self._cosine_similarity(ref_embedding, poi_embedding)
            
            similarities.append({
                'poi': poi,
                'similarity': similarity
            })
        
        # Sort by similarity
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        
        # Create candidates
        candidates = []
        for item in similarities[:top_k]:
            poi = item['poi']
            candidate = POICandidate(
                uri=poi['uri'],
                name=poi['name'],
                poi_type=poi['type'],
                coordinates=(poi['lat'], poi['lon']),
                distance_meters=0,  # Not distance-based
                confidence=item['similarity'],
                resolution_method='embedding_similarity',
                embedding_similarity=item['similarity'],
                attributes=poi.get('attributes', {})
            )
            candidates.append(candidate)
        
        return candidates
    
    def cluster_pois_by_similarity(self, poi_uris: List[str], 
                                   n_clusters: int = 5) -> Dict[int, List[str]]:
        """
        Cluster POIs by embedding similarity
        Useful for: Grouping similar destinations
        """
        from sklearn.cluster import KMeans
        
        # Get embeddings for POIs
        embeddings = []
        valid_uris = []
        
        for uri in poi_uris:
            if uri in self.embedding_index:
                poi_idx = self.embedding_index[uri]
                poi_emb = self.embeddings.iloc[poi_idx].values
                embeddings.append(poi_emb)
                valid_uris.append(uri)
        
        if len(embeddings) < n_clusters:
            self.logger.warning(f"Too few POIs for {n_clusters} clusters")
            return {0: valid_uris}
        
        # Cluster
        embeddings_array = np.array(embeddings)
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        labels = kmeans.fit_predict(embeddings_array)
        
        # Group by cluster
        clusters = {}
        for uri, label in zip(valid_uris, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(uri)
        
        return clusters


# Integration with pipeline
def integrate_embedding_resolver(pipeline, kg_file: str, embeddings_file: str):
    """
    Replace standard POI resolver with embedding-enhanced version
    """
    print("\n" + "="*60)
    print("INTEGRATING EMBEDDING-ENHANCED POI RESOLVER")
    print("="*60)
    
    try:
        enhanced_resolver = EmbeddingEnhancedPOIResolver(
            kg_file=kg_file,
            embeddings_file=embeddings_file,
            embedding_weight=0.5  # Equal weight spatial + semantic
        )
        
        pipeline.poi_resolver = enhanced_resolver
        print("✓ Embedding-enhanced resolver integrated")
        return True
        
    except Exception as e:
        print(f"✗ Failed to integrate enhanced resolver: {e}")
        print("  Falling back to standard resolver")
        return False


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python embedding_enhanced_resolver.py <kg_file> <embeddings_file>")
        sys.exit(1)
    
    kg_file = sys.argv[1]
    embeddings_file = sys.argv[2]
    
    # Test enhanced resolver
    resolver = EmbeddingEnhancedPOIResolver(kg_file, embeddings_file)
    
    # Test location
    test_lat, test_lon = 37.9101, -122.0652  # Walnut Creek
    
    print(f"\n--- Testing Enhanced Resolution ---")
    print(f"Location: ({test_lat}, {test_lon})")
    
    candidates = resolver.resolve_location(test_lat, test_lon, max_candidates=5)
    
    print(f"\nFound {len(candidates)} candidates:")
    for i, cand in enumerate(candidates, 1):
        print(f"\n{i}. {cand.name}")
        print(f"   Distance: {cand.distance_meters:.1f}m")
        print(f"   Embedding similarity: {cand.embedding_similarity:.3f}")
        print(f"   Final confidence: {cand.confidence:.3f}")