"""
GeoRotatE: Geospatially-Aware Knowledge Graph Embeddings

A novel KGE model that combines:
1. RotatE base - relation modeling via rotation in complex space
2. Multi-scale location encoding (Space2Vec-style)
3. Topological feature encoding for shape signatures
4. Path-distance aware scoring with graceful fallback
5. Temporal encoding hooks for GTFS integration

Copyright (c) 2025 Synapse Partners, LLC
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Optional, Dict, Tuple, Set
import math


class MultiScaleLocationEncoder(nn.Module):
    """
    Space2Vec-style multi-scale location encoder.
    
    Encodes continuous (lat, lon) coordinates into dense embeddings using
    sinusoidal position encoding at multiple spatial scales, inspired by
    Transformer position encoding and neuroscience grid cell research.
    
    Key insight: Different spatial scales capture different granularities
    of geographic relationships (neighborhood vs. city vs. region).
    """
    
    def __init__(
        self, 
        coord_dim: int = 2,  # (lat, lon)
        embed_dim: int = 64,
        num_scales: int = 16,
        min_scale: float = 0.001,  # ~100m resolution
        max_scale: float = 1.0,    # ~100km resolution
        learnable_freqs: bool = True
    ):
        super().__init__()
        self.coord_dim = coord_dim
        self.embed_dim = embed_dim
        self.num_scales = num_scales
        
        # Initialize frequency bands (log-spaced scales)
        freqs = torch.logspace(
            math.log10(1/max_scale), 
            math.log10(1/min_scale), 
            num_scales
        )
        
        if learnable_freqs:
            self.freqs = nn.Parameter(freqs)
        else:
            self.register_buffer('freqs', freqs)
        
        # Project sinusoidal features to embedding space
        # Input: coord_dim * num_scales * 2 (sin and cos for each scale and coord)
        pe_dim = coord_dim * num_scales * 2
        self.projection = nn.Sequential(
            nn.Linear(pe_dim, embed_dim * 2),
            nn.LayerNorm(embed_dim * 2),
            nn.GELU(),
            nn.Linear(embed_dim * 2, embed_dim),
            nn.LayerNorm(embed_dim)
        )
    
    def forward(self, coords: torch.Tensor) -> torch.Tensor:
        """
        Args:
            coords: Tensor of shape (batch_size, 2) with (lat, lon) in degrees
            
        Returns:
            Location embeddings of shape (batch_size, embed_dim)
        """
        batch_size = coords.shape[0]
        
        # Normalize coordinates to roughly [-1, 1] range
        # Lat: [-90, 90] -> [-1, 1], Lon: [-180, 180] -> [-1, 1]
        lat_norm = coords[:, 0:1] / 90.0
        lon_norm = coords[:, 1:2] / 180.0
        coords_norm = torch.cat([lat_norm, lon_norm], dim=1)  # (batch, 2)
        
        # Compute multi-scale sinusoidal encoding
        # For each coordinate and each frequency, compute sin and cos
        pe_list = []
        for freq in self.freqs:
            for coord_idx in range(self.coord_dim):
                coord_val = coords_norm[:, coord_idx:coord_idx+1]  # (batch, 1)
                pe_list.append(torch.sin(2 * math.pi * freq * coord_val))
                pe_list.append(torch.cos(2 * math.pi * freq * coord_val))
        
        # Concatenate all position encoding features
        pe = torch.cat(pe_list, dim=1)  # (batch, coord_dim * num_scales * 2)
        
        # Project to final embedding dimension
        location_embed = self.projection(pe)
        
        return location_embed


class TopologicalEncoder(nn.Module):
    """
    Encodes topological/shape features of geographic entities.
    
    For entities with polygon or linestring geometries, this encodes:
    - Shape descriptors (area, perimeter, compactness)
    - Orientation (primary axis direction)
    - Complexity (number of vertices, convexity)
    - Fourier shape descriptors
    
    This addresses the "centroid simplification" problem by preserving
    information about entity shape, size, and orientation.
    """
    
    def __init__(
        self,
        num_shape_features: int = 16,  # Basic shape descriptors
        num_fourier_coeffs: int = 8,    # Fourier descriptor coefficients
        embed_dim: int = 64
    ):
        super().__init__()
        self.num_shape_features = num_shape_features
        self.num_fourier_coeffs = num_fourier_coeffs
        
        # Total input features
        input_dim = num_shape_features + num_fourier_coeffs * 2  # real and imag
        
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, embed_dim),
            nn.LayerNorm(embed_dim),
            nn.GELU(),
            nn.Linear(embed_dim, embed_dim),
            nn.LayerNorm(embed_dim)
        )
        
        # For entities without topology data, learn a default embedding
        self.default_topo = nn.Parameter(torch.zeros(1, input_dim))
        nn.init.normal_(self.default_topo, std=0.01)
    
    def forward(
        self, 
        topo_features: Optional[torch.Tensor] = None,
        mask: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Args:
            topo_features: Shape features (batch_size, input_dim) or None
            mask: Boolean mask indicating which entities have topo features
            
        Returns:
            Topological embeddings (batch_size, embed_dim)
        """
        if topo_features is None:
            # All entities use default (point entities)
            batch_size = 1 if mask is None else mask.shape[0]
            features = self.default_topo.expand(batch_size, -1)
        else:
            if mask is not None:
                # Mix actual features with defaults based on mask
                default_expanded = self.default_topo.expand(topo_features.shape[0], -1)
                features = torch.where(
                    mask.unsqueeze(-1), 
                    topo_features, 
                    default_expanded
                )
            else:
                features = topo_features
        
        return self.encoder(features)


class TemporalEncoder(nn.Module):
    """
    Temporal encoding module for time-dependent relationships.
    
    Supports:
    - Time-of-day encoding (cyclical)
    - Day-of-week encoding (cyclical)
    - Seasonal encoding (cyclical)
    - Event-based temporal markers
    
    Designed for integration with GTFS transit schedules and traffic patterns.
    """
    
    def __init__(
        self,
        embed_dim: int = 64,
        num_time_slots: int = 24,     # Hours in day
        num_day_slots: int = 7,        # Days in week
        include_seasonal: bool = True
    ):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_time_slots = num_time_slots
        self.num_day_slots = num_day_slots
        
        # Cyclical time features: sin/cos for hour, day, month
        num_cyclical = 6 if include_seasonal else 4  # hour + day (+ month)
        
        self.temporal_proj = nn.Sequential(
            nn.Linear(num_cyclical, embed_dim),
            nn.LayerNorm(embed_dim),
            nn.GELU(),
            nn.Linear(embed_dim, embed_dim),
            nn.LayerNorm(embed_dim)
        )
        
        # Learnable time slot embeddings for discrete time periods
        self.time_slot_embed = nn.Embedding(num_time_slots, embed_dim // 2)
        self.day_slot_embed = nn.Embedding(num_day_slots, embed_dim // 2)
        
        # Combine cyclical and discrete
        self.combiner = nn.Linear(embed_dim + embed_dim, embed_dim)
    
    def forward(
        self,
        hour: torch.Tensor,          # Hour of day (0-23)
        day_of_week: torch.Tensor,   # Day of week (0-6)
        month: Optional[torch.Tensor] = None  # Month (1-12)
    ) -> torch.Tensor:
        """
        Args:
            hour: Tensor of shape (batch_size,) with hours (0-23)
            day_of_week: Tensor of shape (batch_size,) with days (0-6)
            month: Optional tensor of shape (batch_size,) with months (1-12)
            
        Returns:
            Temporal embeddings of shape (batch_size, embed_dim)
        """
        batch_size = hour.shape[0]
        
        # Cyclical encoding for continuous time features
        hour_norm = hour.float() / 24.0
        day_norm = day_of_week.float() / 7.0
        
        cyclical = [
            torch.sin(2 * math.pi * hour_norm),
            torch.cos(2 * math.pi * hour_norm),
            torch.sin(2 * math.pi * day_norm),
            torch.cos(2 * math.pi * day_norm),
        ]
        
        if month is not None:
            month_norm = (month.float() - 1) / 12.0
            cyclical.extend([
                torch.sin(2 * math.pi * month_norm),
                torch.cos(2 * math.pi * month_norm),
            ])
        
        cyclical_features = torch.stack(cyclical, dim=1)
        cyclical_embed = self.temporal_proj(cyclical_features)
        
        # Discrete slot embeddings
        time_embed = self.time_slot_embed(hour.long())
        day_embed = self.day_slot_embed(day_of_week.long())
        discrete_embed = torch.cat([time_embed, day_embed], dim=1)
        
        # Combine
        combined = torch.cat([cyclical_embed, discrete_embed], dim=1)
        temporal_embed = self.combiner(combined)
        
        return temporal_embed


class GeoRotatE(nn.Module):
    """
    GeoRotatE: Geospatially-Aware Knowledge Graph Embedding Model
    
    Combines RotatE's relation-as-rotation paradigm with:
    1. Multi-scale location encoding for continuous coordinate embedding
    2. Topological features for shape-aware entity representation
    3. Path-distance scoring for network-aware spatial relationships
    4. Temporal encoding for time-dependent reasoning
    
    The model uses a hybrid scoring function that weighs:
    - Semantic score (standard RotatE)
    - Spatial score (location + path distance)
    - Topological score (shape similarity)
    
    The weights are learned based on relation type.
    """
    
    def __init__(
        self,
        num_entities: int,
        num_relations: int,
        embedding_dim: int = 256,
        location_dim: int = 64,
        topo_dim: int = 64,
        gamma: float = 12.0,  # Margin for scoring
        spatial_relation_ids: Optional[Set[int]] = None,
        use_temporal: bool = False,
        device: torch.device = None
    ):
        super().__init__()
        
        self.num_entities = num_entities
        self.num_relations = num_relations
        self.embedding_dim = embedding_dim
        self.gamma = nn.Parameter(torch.tensor([gamma]), requires_grad=False)
        self.epsilon = 2.0
        self.device = device or torch.device('cpu')
        
        # Store spatial relation IDs for hybrid scoring
        self.spatial_relation_ids = spatial_relation_ids or set()
        
        # ========== Entity Embeddings ==========
        # Complex embeddings for RotatE (real + imaginary)
        self.entity_embedding_real = nn.Embedding(num_entities, embedding_dim)
        self.entity_embedding_imag = nn.Embedding(num_entities, embedding_dim)
        
        # ========== Relation Embeddings ==========
        # Phase embeddings for rotation
        self.relation_embedding = nn.Embedding(num_relations, embedding_dim)
        
        # ========== Spatial Components ==========
        self.location_encoder = MultiScaleLocationEncoder(
            embed_dim=location_dim,
            num_scales=16
        )
        
        self.topo_encoder = TopologicalEncoder(
            embed_dim=topo_dim
        )
        
        # ========== Temporal Component (optional) ==========
        self.use_temporal = use_temporal
        if use_temporal:
            self.temporal_encoder = TemporalEncoder(embed_dim=64)
        
        # ========== Score Combination ==========
        # Learn per-relation weights for combining scores
        # [semantic_weight, spatial_weight, topo_weight]
        self.relation_score_weights = nn.Embedding(num_relations, 3)
        
        # ========== Spatial Distance Parameters ==========
        # Learnable parameters for path distance fallback
        self.path_distance_scale = nn.Parameter(torch.tensor([1.0]))
        self.haversine_to_path_ratio = nn.Parameter(torch.tensor([1.5]))  # typical path/straight-line ratio
        
        # ========== Initialize Weights ==========
        self._init_weights()
    
    def _init_weights(self):
        """Initialize model weights using appropriate schemes."""
        # Entity embeddings: uniform in range for complex unit circle
        embedding_range = (self.gamma.item() + self.epsilon) / self.embedding_dim
        nn.init.uniform_(self.entity_embedding_real.weight, -embedding_range, embedding_range)
        nn.init.uniform_(self.entity_embedding_imag.weight, -embedding_range, embedding_range)
        
        # Relation embeddings: phases in [0, 2π]
        nn.init.uniform_(self.relation_embedding.weight, -math.pi, math.pi)
        
        # Score weights: start with equal weighting for spatial relations
        # Non-spatial relations: 100% semantic
        with torch.no_grad():
            # Default: semantic only
            self.relation_score_weights.weight.fill_(0)
            self.relation_score_weights.weight[:, 0] = 1.0  # semantic weight = 1
            
            # For spatial relations, use balanced weights
            if self.spatial_relation_ids:
                for rel_id in self.spatial_relation_ids:
                    if rel_id < self.num_relations:
                        self.relation_score_weights.weight[rel_id, 0] = 0.4  # semantic
                        self.relation_score_weights.weight[rel_id, 1] = 0.4  # spatial
                        self.relation_score_weights.weight[rel_id, 2] = 0.2  # topo
    
    def get_entity_embedding(self, entity_ids: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Get complex embeddings for entities."""
        real = self.entity_embedding_real(entity_ids)
        imag = self.entity_embedding_imag(entity_ids)
        return real, imag
    
    def get_relation_phase(self, relation_ids: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Get rotation phase (as cos, sin) for relations."""
        phase = self.relation_embedding(relation_ids)
        return torch.cos(phase), torch.sin(phase)
    
    def rotate(
        self, 
        entity_real: torch.Tensor, 
        entity_imag: torch.Tensor,
        rel_cos: torch.Tensor, 
        rel_sin: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Apply rotation to entity embedding.
        
        Complex multiplication: (a + bi)(c + di) = (ac - bd) + (ad + bc)i
        """
        rotated_real = entity_real * rel_cos - entity_imag * rel_sin
        rotated_imag = entity_real * rel_sin + entity_imag * rel_cos
        return rotated_real, rotated_imag
    
    def semantic_score(
        self,
        head_real: torch.Tensor,
        head_imag: torch.Tensor,
        tail_real: torch.Tensor,
        tail_imag: torch.Tensor,
        rel_cos: torch.Tensor,
        rel_sin: torch.Tensor
    ) -> torch.Tensor:
        """
        Compute RotatE semantic score.
        
        Score = γ - ||h ∘ r - t||
        
        Where h ∘ r is complex rotation of head by relation phase.
        """
        # Rotate head by relation
        rotated_real, rotated_imag = self.rotate(head_real, head_imag, rel_cos, rel_sin)
        
        # Distance to tail in complex space
        diff_real = rotated_real - tail_real
        diff_imag = rotated_imag - tail_imag
        
        # L2 norm of complex difference
        score = torch.sqrt(diff_real ** 2 + diff_imag ** 2 + 1e-8)
        score = self.gamma - score.sum(dim=-1)
        
        return score
    
    def spatial_score(
        self,
        head_coords: torch.Tensor,
        tail_coords: torch.Tensor,
        path_distances: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Compute spatial similarity score.
        
        Uses path distance if available, otherwise estimates from Haversine
        with learned correction factor.
        """
        # Compute Haversine distance as baseline
        haversine_dist = self._haversine_distance(
            head_coords[:, 0], head_coords[:, 1],
            tail_coords[:, 0], tail_coords[:, 1]
        )
        
        if path_distances is not None:
            # Use actual path distances where available
            # -1 indicates missing path distance
            valid_mask = path_distances >= 0
            
            # Estimate path distance for missing values
            estimated_path = haversine_dist * self.haversine_to_path_ratio
            
            actual_dist = torch.where(
                valid_mask,
                path_distances,
                estimated_path
            )
        else:
            # Estimate all path distances
            actual_dist = haversine_dist * self.haversine_to_path_ratio
        
        # Convert distance to score (closer = higher score)
        # Use smooth decay: score = γ * exp(-dist / scale)
        normalized_dist = actual_dist / (self.path_distance_scale * 1000)  # km scale
        spatial_score = self.gamma * torch.exp(-normalized_dist)
        
        return spatial_score
    
    def topological_score(
        self,
        head_topo: torch.Tensor,
        tail_topo: torch.Tensor
    ) -> torch.Tensor:
        """
        Compute topological similarity score.
        
        Uses cosine similarity of topological embeddings.
        """
        # Normalize embeddings
        head_norm = F.normalize(head_topo, p=2, dim=-1)
        tail_norm = F.normalize(tail_topo, p=2, dim=-1)
        
        # Cosine similarity scaled by gamma
        similarity = (head_norm * tail_norm).sum(dim=-1)
        topo_score = self.gamma * (similarity + 1) / 2  # Map [-1, 1] to [0, γ]
        
        return topo_score
    
    def _haversine_distance(
        self,
        lat1: torch.Tensor,
        lon1: torch.Tensor,
        lat2: torch.Tensor,
        lon2: torch.Tensor
    ) -> torch.Tensor:
        """
        Compute Haversine distance in meters.
        
        GPU-accelerated implementation.
        """
        # Convert to radians
        lat1_rad = torch.deg2rad(lat1)
        lon1_rad = torch.deg2rad(lon1)
        lat2_rad = torch.deg2rad(lat2)
        lon2_rad = torch.deg2rad(lon2)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = torch.sin(dlat / 2) ** 2 + \
            torch.cos(lat1_rad) * torch.cos(lat2_rad) * torch.sin(dlon / 2) ** 2
        c = 2 * torch.asin(torch.sqrt(torch.clamp(a, 0, 1)))
        
        # Earth radius in meters
        r = 6371000
        
        return c * r
    
    def forward(
        self,
        head_ids: torch.Tensor,
        relation_ids: torch.Tensor,
        tail_ids: torch.Tensor,
        head_coords: Optional[torch.Tensor] = None,
        tail_coords: Optional[torch.Tensor] = None,
        head_topo: Optional[torch.Tensor] = None,
        tail_topo: Optional[torch.Tensor] = None,
        path_distances: Optional[torch.Tensor] = None,
        mode: str = 'single'  # 'single', 'head-batch', or 'tail-batch'
    ) -> torch.Tensor:
        """
        Compute scores for triples.
        
        Args:
            head_ids: Head entity IDs (batch_size,) or (batch_size, num_neg)
            relation_ids: Relation IDs (batch_size,)
            tail_ids: Tail entity IDs (batch_size,) or (batch_size, num_neg)
            head_coords: Head coordinates (batch_size, 2) - optional
            tail_coords: Tail coordinates (batch_size, 2) - optional
            head_topo: Head topological features - optional
            tail_topo: Tail topological features - optional
            path_distances: Pre-computed path distances - optional
            mode: Scoring mode for negative sampling
            
        Returns:
            Scores tensor
        """
        # Get entity embeddings
        head_real, head_imag = self.get_entity_embedding(head_ids)
        tail_real, tail_imag = self.get_entity_embedding(tail_ids)
        
        # Get relation rotation
        rel_cos, rel_sin = self.get_relation_phase(relation_ids)
        
        # Handle batch mode for negative sampling
        if mode == 'head-batch':
            rel_cos = rel_cos.unsqueeze(1)
            rel_sin = rel_sin.unsqueeze(1)
            tail_real = tail_real.unsqueeze(1)
            tail_imag = tail_imag.unsqueeze(1)
        elif mode == 'tail-batch':
            rel_cos = rel_cos.unsqueeze(1)
            rel_sin = rel_sin.unsqueeze(1)
            head_real = head_real.unsqueeze(1)
            head_imag = head_imag.unsqueeze(1)
        
        # Compute semantic score (always)
        sem_score = self.semantic_score(
            head_real, head_imag,
            tail_real, tail_imag,
            rel_cos, rel_sin
        )
        
        # Get per-relation score weights
        weights = torch.softmax(self.relation_score_weights(relation_ids), dim=-1)
        
        if mode != 'single':
            weights = weights.unsqueeze(1)
        
        # Start with weighted semantic score
        final_score = weights[..., 0] * sem_score
        
        # Add spatial score if coordinates available
        if head_coords is not None and tail_coords is not None:
            spa_score = self.spatial_score(head_coords, tail_coords, path_distances)
            if mode != 'single':
                spa_score = spa_score.unsqueeze(1)
            final_score = final_score + weights[..., 1] * spa_score
        
        # Add topological score if features available
        if head_topo is not None and tail_topo is not None:
            topo_score = self.topological_score(head_topo, tail_topo)
            if mode != 'single':
                topo_score = topo_score.unsqueeze(1)
            final_score = final_score + weights[..., 2] * topo_score
        
        return final_score
    
    def get_entity_embeddings(self) -> torch.Tensor:
        """
        Get combined entity embeddings for downstream tasks.
        
        Returns concatenated real and imaginary parts.
        """
        real = self.entity_embedding_real.weight
        imag = self.entity_embedding_imag.weight
        return torch.cat([real, imag], dim=-1)
    
    def get_enhanced_embeddings(
        self,
        entity_ids: torch.Tensor,
        coords: Optional[torch.Tensor] = None,
        topo_features: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Get enhanced embeddings combining semantic, spatial, and topological info.
        
        Useful for entity similarity queries like:
        "Which school has similar pedestrian infrastructure?"
        """
        # Semantic embedding
        real, imag = self.get_entity_embedding(entity_ids)
        semantic_embed = torch.cat([real, imag], dim=-1)
        
        embeddings = [semantic_embed]
        
        # Location embedding
        if coords is not None:
            loc_embed = self.location_encoder(coords)
            embeddings.append(loc_embed)
        
        # Topological embedding
        if topo_features is not None:
            topo_embed = self.topo_encoder(topo_features)
            embeddings.append(topo_embed)
        
        return torch.cat(embeddings, dim=-1)
