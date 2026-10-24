"""
Transportation Planner Label Generator
Implements labels from Transportation Planner Annotation Taxonomy
For consumer/transportation planning use cases
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
import numpy as np


@dataclass
class TransportationPlannerLabels:
    """Complete set of transportation planner labels"""
    
    # Route characteristic labels (Section 4.1)
    shortest_route: bool
    fastest_route: bool
    toll_free_route: bool
    safest_route: bool
    carbon_neutral: bool
    most_congested_route: bool
    least_congested_route: bool
    
    # Active mobility labels (Section 4.2)
    active_mobility_route: bool
    pedestrian_friendly_route: bool
    
    # Infrastructure scores (Section 4.2)
    pedestrian_infrastructure_score: float  # 0-1
    micromobility_infrastructure_score: float  # 0-1
    active_mobility_segment_risk_score: float  # 0-1
    active_mobility_route_risk_score: float  # 0-1
    
    # Traveler-specific labels (Section 4.2)
    traveler_active_mobility_ratio: Optional[float] = None  # Requires history
    traveler_active_mobility_temporal_profile: Optional[str] = None  # Requires history
    
    def to_dict(self) -> Dict:
        return {
            'route_characteristics': {
                'shortest_route': self.shortest_route,
                'fastest_route': self.fastest_route,
                'toll_free_route': self.toll_free_route,
                'safest_route': self.safest_route,
                'carbon_neutral': self.carbon_neutral,
                'most_congested_route': self.most_congested_route,
                'least_congested_route': self.least_congested_route
            },
            'active_mobility': {
                'active_mobility_route': self.active_mobility_route,
                'pedestrian_friendly_route': self.pedestrian_friendly_route
            },
            'infrastructure_quality': {
                'pedestrian_infrastructure_score': round(self.pedestrian_infrastructure_score, 3),
                'micromobility_infrastructure_score': round(self.micromobility_infrastructure_score, 3),
                'active_mobility_segment_risk_score': round(self.active_mobility_segment_risk_score, 3),
                'active_mobility_route_risk_score': round(self.active_mobility_route_risk_score, 3)
            },
            'traveler_patterns': {
                'active_mobility_ratio': round(self.traveler_active_mobility_ratio, 3) if self.traveler_active_mobility_ratio else None,
                'active_mobility_temporal_profile': self.traveler_active_mobility_temporal_profile
            }
        }


class TransportationPlannerLabelGenerator:
    """
    Generates labels according to Transportation Planner taxonomy
    Implements Section 4.2 of the spec
    """
    
    def __init__(self, kg_accessor=None):
        """
        Initialize label generator
        
        Args:
            kg_accessor: Optional KG accessor for infrastructure queries
        """
        self.kg_accessor = kg_accessor
    
    def generate_labels(self, 
                       trip_data: Dict,
                       stage2_data: Dict,
                       stage3_data: Dict,
                       traveler_history: Optional[List[Dict]] = None) -> TransportationPlannerLabels:
        """
        Generate complete set of transportation planner labels
        
        Args:
            trip_data: Base trip data
            stage2_data: Geospatial enrichment data
            stage3_data: Contextual enrichment data
            traveler_history: Optional trip history for traveler-specific labels
        """
        
        # Route characteristic labels
        route_chars = self._generate_route_characteristics(stage2_data, stage3_data)
        
        # Active mobility labels
        active_mobility_labels = self._generate_active_mobility_labels(stage2_data)
        
        # Infrastructure scores
        infra_scores = self._generate_infrastructure_scores(stage2_data)
        
        # Traveler-specific labels (if history available)
        traveler_labels = self._generate_traveler_labels(traveler_history) if traveler_history else {}
        
        return TransportationPlannerLabels(
            # Route characteristics
            shortest_route=route_chars['shortest_route'],
            fastest_route=route_chars['fastest_route'],
            toll_free_route=route_chars['toll_free_route'],
            safest_route=route_chars['safest_route'],
            carbon_neutral=route_chars['carbon_neutral'],
            most_congested_route=route_chars['most_congested_route'],
            least_congested_route=route_chars['least_congested_route'],
            
            # Active mobility
            active_mobility_route=active_mobility_labels['active_mobility_route'],
            pedestrian_friendly_route=active_mobility_labels['pedestrian_friendly_route'],
            
            # Infrastructure scores
            pedestrian_infrastructure_score=infra_scores['pedestrian_infrastructure_score'],
            micromobility_infrastructure_score=infra_scores['micromobility_infrastructure_score'],
            active_mobility_segment_risk_score=infra_scores['active_mobility_segment_risk_score'],
            active_mobility_route_risk_score=infra_scores['active_mobility_route_risk_score'],
            
            # Traveler patterns
            traveler_active_mobility_ratio=traveler_labels.get('active_mobility_ratio'),
            traveler_active_mobility_temporal_profile=traveler_labels.get('temporal_profile')
        )
    
    def _generate_route_characteristics(self, stage2_data: Dict, stage3_data: Dict) -> Dict:
        """Generate route characteristic labels (Section 4.1)"""
        
        route_used = stage2_data.get('route_used', {})
        alternative_routes = stage2_data.get('alternative_routes', [])
        
        # Get modality segments
        modality_segments = stage2_data.get('modality_segments', [])
       
        # Default values
        labels = {
            'shortest_route': False,
            'fastest_route': True,  # Assume actual route is fastest
            'toll_free_route': True,  # Would need toll data to determine
            'safest_route': False,
            'carbon_neutral': False,
            'most_congested_route': False,
            'least_congested_route': True
        }
        
        # Check modality for carbon neutral
        modality_segments = stage2_data.get('modality_segments', [])
        if modality_segments:
            # Carbon neutral if all segments are active mobility or EV
            all_carbon_neutral = all(
                seg['modality'] in ['walking', 'bicycling'] 
                for seg in modality_segments
            )
            labels['carbon_neutral'] = all_carbon_neutral
        
        # Compare with alternatives if available
        if alternative_routes and route_used:
            actual_distance = route_used.get('total_distance_meters', 0)
            actual_duration = route_used.get('total_duration_seconds', 0)
            
            # Check if shortest
            is_shortest = all(
                actual_distance <= alt.get('total_distance_meters', float('inf'))
                for alt in alternative_routes
            )
            labels['shortest_route'] = is_shortest
            
            # Check if fastest
            is_fastest = all(
                actual_duration <= alt.get('total_duration_seconds', float('inf'))
                for alt in alternative_routes
            )
            labels['fastest_route'] = is_fastest
        
        # Congestion from stage 3
        traffic_data = stage3_data.get('traffic_data', {})
        congestion = traffic_data.get('average_congestion', 0.5)
        
        labels['most_congested_route'] = congestion > 0.7
        labels['least_congested_route'] = congestion < 0.3
        
        return labels
    
    def _generate_active_mobility_labels(self, stage2_data: Dict) -> Dict:
        """Generate active mobility labels (Section 4.2)"""
        
        modality_segments = stage2_data.get('modality_segments', [])
        
        # Check if route is exclusively active mobility
        active_modalities = {'walking', 'bicycling'}
        active_mobility_route = False
        pedestrian_friendly = False
        
        if modality_segments:
            # Active mobility route: all segments are active mobility
            active_mobility_route = all(
                seg['modality'] in active_modalities
                for seg in modality_segments
            )
            
            # Pedestrian friendly: has sidewalks/walking infrastructure
            # This would ideally query KG for sidewalk availability
            # For now, use heuristic: if walking is a modality
            pedestrian_friendly = any(
                seg.get('modality') == 'walking'
                for seg in modality_segments
            )
        
        return {
            'active_mobility_route': active_mobility_route,
            'pedestrian_friendly_route': pedestrian_friendly
        }
    
    def _generate_infrastructure_scores(self, stage2_data: Dict) -> Dict:
        """
        Generate infrastructure quality scores (Section 4.2)
        Scores are 0-1, with 0 = excellent, 1 = poor (risk-based)
        """
        
        # These scores would ideally query the KG for:
        # - Sidewalk availability and quality
        # - Bike lane availability and type (protected vs unprotected)
        # - Crosswalk availability
        # - Surface quality
        # - Lighting
        # - Historical accident data
        
        # For now, use heuristics based on available data
        modality_segments = stage2_data.get('modality_segments', [])
        route_used = stage2_data.get('route_used', {})
        
        # Default scores (medium quality/risk)
        scores = {
            'pedestrian_infrastructure_score': 0.5,
            'micromobility_infrastructure_score': 0.5,
            'active_mobility_segment_risk_score': 0.5,
            'active_mobility_route_risk_score': 0.5
        }
        
        if not modality_segments:
            return scores
        
        # Calculate based on modalities used
        has_walking = any(seg['modality'] == 'walking' for seg in modality_segments)
        has_bicycling = any(seg['modality'] == 'bicycling' for seg in modality_segments)
        
        if has_walking:
            # Better pedestrian score if walking was chosen
            # (implies acceptable infrastructure)
            scores['pedestrian_infrastructure_score'] = 0.3  # Lower = better
        
        if has_bicycling:
            # Better micromobility score if cycling was chosen
            scores['micromobility_infrastructure_score'] = 0.3
        
        # Active mobility risk: lower if active mobility was used
        # (travelers avoid high-risk routes)
        if has_walking or has_bicycling:
            scores['active_mobility_segment_risk_score'] = 0.3
            scores['active_mobility_route_risk_score'] = 0.3
        
        # TODO: Enhance with actual KG queries for:
        # - Sidewalk availability along route
        # - Bike lane type (protected = lower risk)
        # - Traffic volume
        # - Historical accident data
        # - Street lighting
        
        return scores
    
    def _generate_traveler_labels(self, traveler_history: List[Dict]) -> Dict:
        """
        Generate traveler-specific labels from trip history (Section 4.2)
        
        Args:
            traveler_history: List of previous trips for this traveler
        """
        if not traveler_history:
            return {}
        
        # Calculate active mobility ratio
        total_trips = len(traveler_history)
        active_mobility_trips = sum(
            1 for trip in traveler_history
            if self._is_active_mobility_trip(trip)
        )
        
        active_mobility_ratio = active_mobility_trips / total_trips if total_trips > 0 else 0
        
        # Calculate temporal profile
        weekday_active = sum(
            1 for trip in traveler_history
            if self._is_active_mobility_trip(trip) and self._is_weekday(trip)
        )
        
        weekday_ratio = weekday_active / active_mobility_trips if active_mobility_trips > 0 else 0
        
        # Classify temporal profile (per spec Section 4.2)
        if weekday_ratio > 0.7:
            temporal_profile = "Primarily Weekday"
        elif weekday_ratio < 0.3:
            temporal_profile = "Primarily Weekend"
        else:
            temporal_profile = "Evenly Distributed"
        
        return {
            'active_mobility_ratio': active_mobility_ratio,
            'temporal_profile': temporal_profile
        }
    
    def _is_active_mobility_trip(self, trip: Dict) -> bool:
        """Check if trip is active mobility"""
        modality_segments = trip.get('stage2_geospatial_enrichment', {}).get('modality_segments', [])
        if not modality_segments:
            return False
        
        # Trip is active mobility if all segments are walking/bicycling
        return all(
            seg.get('modality') in ['walking', 'bicycling']
            for seg in modality_segments
        )
    
    def _is_weekday(self, trip: Dict) -> bool:
        """Check if trip occurred on weekday"""
        from datetime import datetime
        
        trip_date = trip.get('stage1_base_trip', {}).get('trip_date')
        if not trip_date:
            return True  # Default to weekday
        
        if isinstance(trip_date, str):
            trip_date = datetime.fromisoformat(trip_date)
        
        return trip_date.weekday() < 5  # Monday=0, Sunday=6


# Integration function
def integrate_transportation_planner_labels(pipeline):
    """
    Add transportation planner label generator to pipeline
    """
    print("✓ Integrating Transportation Planner label taxonomy")
    pipeline.tp_label_generator = TransportationPlannerLabelGenerator()
    return pipeline


if __name__ == "__main__":
    # Test label generation
    test_stage2 = {
        'modality_segments': [
            {'modality': 'walking', 'duration_seconds': 600},
            {'modality': 'transit', 'duration_seconds': 1200},
            {'modality': 'walking', 'duration_seconds': 300}
        ],
        'route_used': {
            'total_distance_meters': 5000,
            'total_duration_seconds': 2100
        },
        'alternative_routes': [
            {'total_distance_meters': 5200, 'total_duration_seconds': 1800},
            {'total_distance_meters': 4800, 'total_duration_seconds': 2400}
        ]
    }
    
    test_stage3 = {
        'traffic_data': {
            'average_congestion': 0.4
        }
    }
    
    generator = TransportationPlannerLabelGenerator()
    labels = generator.generate_labels({}, test_stage2, test_stage3)
    
    print("\n" + "="*60)
    print("TRANSPORTATION PLANNER LABELS")
    print("="*60)
    print(json.dumps(labels.to_dict(), indent=2))