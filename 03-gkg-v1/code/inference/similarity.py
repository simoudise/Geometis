"""
Entity Similarity Search for GeoRotatE

Enables queries like:
- "Which school in Antioch has similar pedestrian infrastructure as Buena Vista in Walnut Creek?"
- "Find POIs similar to this location"

Copyright (c) 2025 Synapse Partners, LLC
"""

import torch
import torch.nn.functional as F
import numpy as np
from typing import List, Dict, Tuple, Optional, Union
import json
import os
from dataclasses import dataclass


@dataclass
class SimilarityResult:
    """Result from a similarity query."""
    entity_uri: str
    entity_id: int
    similarity_score: float
    semantic_similarity: float
    spatial_similarity: float
    topological_similarity: float
    distance_meters: Optional[float] = None


class GeoRotatESimilaritySearch:
    """
    Similarity search using GeoRotatE embeddings.
    
    Supports multiple similarity modes:
    - semantic: Pure embedding similarity
    - spatial: Location-based similarity
    - topological: Shape/structure similarity
    - combined: Weighted combination of all
    """
    
    def __init__(
        self,
        embeddings_path: str,
        coordinates_path: Optional[str] = None,
        topo_features_path: Optional[str] = None,
        device: torch.device = None
    ):
        """
        Load embeddings and supporting data.
        
        Args:
            embeddings_path: Path to entity_embeddings.pt
            coordinates_path: Path to coordinates.txt (optional)
            topo_features_path: Path to topological_features.npz (optional)
            device: Torch device
        """
        self.device = device or torch.device('cpu')
        
        # Load embeddings
        print(f"Loading embeddings from: {embeddings_path}")
        data = torch.load(embeddings_path, map_location='cpu')
        
        self.embeddings = data['embeddings'].to(self.device)
        self.id_to_entity = data.get('id_to_entity', {})
        self.entity_to_id = {v: int(k) for k, v in self.id_to_entity.items()}
        
        self.num_entities = self.embeddings.shape[0]
        self.embedding_dim = self.embeddings.shape[1]
        
        print(f"  Loaded {self.num_entities:,} entity embeddings (dim={self.embedding_dim})")
        
        # Normalize embeddings for cosine similarity
        self.embeddings_normalized = F.normalize(self.embeddings, p=2, dim=1)
        
        # Load coordinates
        self.coordinates = None
        if coordinates_path and os.path.exists(coordinates_path):
            self._load_coordinates(coordinates_path)
        
        # Load topological features
        self.topo_features = None
        if topo_features_path and os.path.exists(topo_features_path):
            self._load_topo_features(topo_features_path)
    
    def _load_coordinates(self, path: str):
        """Load coordinate data."""
        print(f"Loading coordinates from: {path}")
        self.coordinates = torch.zeros(self.num_entities, 2, dtype=torch.float32)
        
        loaded = 0
        with open(path, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) == 3:
                    uri, lat, lon = parts
                    entity_id = self.entity_to_id.get(uri)
                    if entity_id is not None:
                        self.coordinates[entity_id, 0] = float(lat)
                        self.coordinates[entity_id, 1] = float(lon)
                        loaded += 1
        
        self.coordinates = self.coordinates.to(self.device)
        print(f"  Loaded coordinates for {loaded:,} entities")
    
    def _load_topo_features(self, path: str):
        """Load topological features."""
        print(f"Loading topological features from: {path}")
        data = np.load(path, allow_pickle=True)
        uris = data['uris']
        features = data['features']
        
        topo_dim = features.shape[1]
        self.topo_features = torch.zeros(self.num_entities, topo_dim, dtype=torch.float32)
        
        loaded = 0
        for uri, feat in zip(uris, features):
            entity_id = self.entity_to_id.get(str(uri))
            if entity_id is not None:
                self.topo_features[entity_id] = torch.from_numpy(feat)
                loaded += 1
        
        self.topo_features = self.topo_features.to(self.device)
        self.topo_features_normalized = F.normalize(self.topo_features, p=2, dim=1)
        print(f"  Loaded topological features for {loaded:,} entities")
    
    def find_similar(
        self,
        query: Union[str, int, torch.Tensor],
        k: int = 10,
        mode: str = 'combined',
        semantic_weight: float = 0.4,
        spatial_weight: float = 0.3,
        topo_weight: float = 0.3,
        entity_type_filter: Optional[str] = None,
        city_filter: Optional[str] = None,
        max_distance_km: Optional[float] = None,
        exclude_query: bool = True
    ) -> List[SimilarityResult]:
        """
        Find entities similar to the query.
        
        Args:
            query: Entity URI, entity ID, or embedding tensor
            k: Number of results to return
            mode: 'semantic', 'spatial', 'topological', or 'combined'
            semantic_weight: Weight for semantic similarity (combined mode)
            spatial_weight: Weight for spatial similarity (combined mode)
            topo_weight: Weight for topological similarity (combined mode)
            entity_type_filter: Filter by entity type (e.g., 'School', 'Park')
            city_filter: Filter by city name
            max_distance_km: Maximum distance from query entity
            exclude_query: Exclude the query entity from results
            
        Returns:
            List of SimilarityResult objects
        """
        # Resolve query to entity ID
        query_id = self._resolve_query(query)
        
        if query_id is None:
            raise ValueError(f"Could not resolve query: {query}")
        
        # Get query embedding
        query_embed = self.embeddings_normalized[query_id].unsqueeze(0)
        
        # Compute semantic similarity (cosine)
        semantic_sim = torch.mm(query_embed, self.embeddings_normalized.t()).squeeze(0)
        
        # Compute spatial similarity
        spatial_sim = torch.zeros(self.num_entities, device=self.device)
        distances = None
        
        if self.coordinates is not None:
            query_coords = self.coordinates[query_id]
            distances = self._haversine_batch(query_coords, self.coordinates)
            # Convert distance to similarity: sim = exp(-dist/scale)
            spatial_sim = torch.exp(-distances / 5000)  # 5km scale
        
        # Compute topological similarity
        topo_sim = torch.zeros(self.num_entities, device=self.device)
        
        if self.topo_features is not None:
            query_topo = self.topo_features_normalized[query_id].unsqueeze(0)
            topo_sim = torch.mm(query_topo, self.topo_features_normalized.t()).squeeze(0)
            topo_sim = (topo_sim + 1) / 2  # Map [-1, 1] to [0, 1]
        
        # Combine scores based on mode
        if mode == 'semantic':
            combined_sim = semantic_sim
        elif mode == 'spatial':
            combined_sim = spatial_sim
        elif mode == 'topological':
            combined_sim = topo_sim
        elif mode == 'combined':
            # Normalize weights
            total_weight = semantic_weight + spatial_weight + topo_weight
            sw = semantic_weight / total_weight
            spw = spatial_weight / total_weight
            tw = topo_weight / total_weight
            
            combined_sim = sw * semantic_sim + spw * spatial_sim + tw * topo_sim
        else:
            raise ValueError(f"Unknown mode: {mode}")
        
        # Apply filters
        mask = torch.ones(self.num_entities, dtype=torch.bool, device=self.device)
        
        if exclude_query:
            mask[query_id] = False
        
        if max_distance_km is not None and distances is not None:
            mask = mask & (distances <= max_distance_km * 1000)
        
        # Apply mask
        combined_sim = torch.where(mask, combined_sim, torch.tensor(-float('inf'), device=self.device))
        
        # Get top-k
        top_scores, top_indices = torch.topk(combined_sim, min(k, mask.sum().item()))
        
        # Build results
        results = []
        for idx, score in zip(top_indices.cpu().numpy(), top_scores.cpu().numpy()):
            idx = int(idx)
            
            dist = None
            if distances is not None:
                dist = float(distances[idx].cpu())
            
            result = SimilarityResult(
                entity_uri=self.id_to_entity.get(idx, f"entity_{idx}"),
                entity_id=idx,
                similarity_score=float(score),
                semantic_similarity=float(semantic_sim[idx].cpu()),
                spatial_similarity=float(spatial_sim[idx].cpu()) if self.coordinates is not None else 0.0,
                topological_similarity=float(topo_sim[idx].cpu()) if self.topo_features is not None else 0.0,
                distance_meters=dist
            )
            results.append(result)
        
        return results
    
    def find_similar_to_multiple(
        self,
        queries: List[Union[str, int]],
        k: int = 10,
        aggregation: str = 'mean',
        **kwargs
    ) -> List[SimilarityResult]:
        """
        Find entities similar to multiple query entities.
        
        Useful for queries like: "Find locations similar to both School A and School B"
        
        Args:
            queries: List of entity URIs or IDs
            k: Number of results
            aggregation: 'mean', 'max', or 'min' for combining similarities
            **kwargs: Additional arguments passed to find_similar
            
        Returns:
            List of SimilarityResult objects
        """
        # Get query IDs
        query_ids = [self._resolve_query(q) for q in queries]
        query_ids = [qid for qid in query_ids if qid is not None]
        
        if not query_ids:
            raise ValueError("No valid queries provided")
        
        # Compute mean query embedding
        query_embeds = self.embeddings_normalized[query_ids]
        
        if aggregation == 'mean':
            combined_query = query_embeds.mean(dim=0, keepdim=True)
        elif aggregation == 'max':
            combined_query = query_embeds.max(dim=0, keepdim=True)[0]
        else:
            combined_query = query_embeds.min(dim=0, keepdim=True)[0]
        
        combined_query = F.normalize(combined_query, p=2, dim=1)
        
        # Compute similarity
        semantic_sim = torch.mm(combined_query, self.embeddings_normalized.t()).squeeze(0)
        
        # Exclude query entities
        mask = torch.ones(self.num_entities, dtype=torch.bool, device=self.device)
        for qid in query_ids:
            mask[qid] = False
        
        semantic_sim = torch.where(mask, semantic_sim, torch.tensor(-float('inf'), device=self.device))
        
        # Get top-k
        top_scores, top_indices = torch.topk(semantic_sim, k)
        
        results = []
        for idx, score in zip(top_indices.cpu().numpy(), top_scores.cpu().numpy()):
            idx = int(idx)
            results.append(SimilarityResult(
                entity_uri=self.id_to_entity.get(idx, f"entity_{idx}"),
                entity_id=idx,
                similarity_score=float(score),
                semantic_similarity=float(score),
                spatial_similarity=0.0,
                topological_similarity=0.0
            ))
        
        return results
    
    def compare_entities(
        self,
        entity_a: Union[str, int],
        entity_b: Union[str, int]
    ) -> Dict[str, float]:
        """
        Compare two entities across all similarity dimensions.
        
        Args:
            entity_a: First entity URI or ID
            entity_b: Second entity URI or ID
            
        Returns:
            Dict with similarity scores
        """
        id_a = self._resolve_query(entity_a)
        id_b = self._resolve_query(entity_b)
        
        if id_a is None or id_b is None:
            raise ValueError("Could not resolve one or both entities")
        
        # Semantic similarity
        embed_a = self.embeddings_normalized[id_a]
        embed_b = self.embeddings_normalized[id_b]
        semantic_sim = float(torch.dot(embed_a, embed_b).cpu())
        
        result = {
            'semantic_similarity': semantic_sim,
            'spatial_similarity': 0.0,
            'topological_similarity': 0.0,
            'distance_meters': None
        }
        
        # Spatial similarity
        if self.coordinates is not None:
            coords_a = self.coordinates[id_a]
            coords_b = self.coordinates[id_b]
            distance = float(self._haversine(coords_a[0], coords_a[1], coords_b[0], coords_b[1]).cpu())
            result['distance_meters'] = distance
            result['spatial_similarity'] = float(torch.exp(torch.tensor(-distance / 5000)))
        
        # Topological similarity
        if self.topo_features is not None:
            topo_a = self.topo_features_normalized[id_a]
            topo_b = self.topo_features_normalized[id_b]
            topo_sim = float(torch.dot(topo_a, topo_b).cpu())
            result['topological_similarity'] = (topo_sim + 1) / 2
        
        return result
    
    def _resolve_query(self, query: Union[str, int, torch.Tensor]) -> Optional[int]:
        """Resolve query to entity ID."""
        if isinstance(query, int):
            return query if 0 <= query < self.num_entities else None
        elif isinstance(query, str):
            return self.entity_to_id.get(query)
        elif isinstance(query, torch.Tensor):
            # Return None - caller should handle embedding directly
            return None
        return None
    
    def _haversine(self, lat1, lon1, lat2, lon2) -> torch.Tensor:
        """Haversine distance between two points."""
        lat1_rad = torch.deg2rad(lat1)
        lon1_rad = torch.deg2rad(lon1)
        lat2_rad = torch.deg2rad(lat2)
        lon2_rad = torch.deg2rad(lon2)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = torch.sin(dlat / 2) ** 2 + torch.cos(lat1_rad) * torch.cos(lat2_rad) * torch.sin(dlon / 2) ** 2
        c = 2 * torch.asin(torch.sqrt(torch.clamp(a, 0, 1)))
        
        return c * 6371000  # Earth radius in meters
    
    def _haversine_batch(self, coord1: torch.Tensor, coords2: torch.Tensor) -> torch.Tensor:
        """Haversine distance from one point to many points."""
        lat1 = torch.deg2rad(coord1[0])
        lon1 = torch.deg2rad(coord1[1])
        lat2 = torch.deg2rad(coords2[:, 0])
        lon2 = torch.deg2rad(coords2[:, 1])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = torch.sin(dlat / 2) ** 2 + torch.cos(lat1) * torch.cos(lat2) * torch.sin(dlon / 2) ** 2
        c = 2 * torch.asin(torch.sqrt(torch.clamp(a, 0, 1)))
        
        return c * 6371000


def demo_similarity_search():
    """Demo usage of similarity search."""
    print("="*60)
    print("GeoRotatE Similarity Search Demo")
    print("="*60)
    
    # This would be run after training
    # search = GeoRotatESimilaritySearch(
    #     embeddings_path="georotate_output/entity_embeddings.pt",
    #     coordinates_path="georotate_training_data/coordinates.txt",
    #     topo_features_path="georotate_training_data/topological_features.npz"
    # )
    
    # Example query: Find schools similar to Buena Vista
    # results = search.find_similar(
    #     query="urn:urban-kg:BuenaVistaSchool",
    #     k=5,
    #     mode='combined',
    #     topo_weight=0.5,  # Higher weight on topology for infrastructure
    #     city_filter="Antioch"
    # )
    
    # for r in results:
    #     print(f"{r.entity_uri}: score={r.similarity_score:.3f}, "
    #           f"topo={r.topological_similarity:.3f}, "
    #           f"dist={r.distance_meters/1000:.1f}km")
    
    print("\nTo use after training:")
    print("  from inference.similarity import GeoRotatESimilaritySearch")
    print("  search = GeoRotatESimilaritySearch('georotate_output/entity_embeddings.pt')")
    print("  results = search.find_similar('urn:urban-kg:BuenaVistaSchool', k=5)")


if __name__ == "__main__":
    demo_similarity_search()
