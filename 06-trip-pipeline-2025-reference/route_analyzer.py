"""
Route Analyzer Module - Refactored
High-level route analysis for trip enhancement pipeline
Uses route_reconstructor.py as backend for OSRM operations
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

# Import the route reconstructor as backend
from route_reconstructor import RouteReconstructor, Route

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AlternativeRoute:
    """Alternative route option for trip enhancement"""
    route_id: str
    distance_meters: float
    duration_seconds: float
    geometry: str  # Polyline encoding
    is_common_sense: bool  # Meets "common sense" criteria
    distance_ratio: float  # Ratio to actual route distance
    duration_ratio: float  # Ratio to actual route duration
    route_type: str  # 'shortest', 'fastest', 'recommended', etc.
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RouteAnalysis:
    """Complete route analysis for a trip"""
    trip_id: str
    
    # Actual route used
    actual_route_distance_m: float
    actual_route_duration_s: float
    actual_route_geometry: str
    actual_route_segments: List[Dict]
    
    # Alternative routes
    alternative_routes: List[AlternativeRoute]
    
    # Route characteristics
    modality: str
    route_quality: float  # Match quality (0-1)
    
    # Comparison metrics
    shortest_available_m: Optional[float] = None
    fastest_available_s: Optional[float] = None
    took_shortest_route: Optional[bool] = None
    took_fastest_route: Optional[bool] = None
    
    # Additional characteristics
    road_type_distribution: Optional[Dict] = None
    average_speed_mps: Optional[float] = None
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data['alternative_routes'] = [r.to_dict() for r in self.alternative_routes]
        return data


class RouteAnalyzer:
    """
    High-level route analysis for trip enhancement pipeline
    - Matches GPS traces to road network (via route_reconstructor)
    - Generates alternative "common sense" routes
    - Calculates comparison metrics (took shortest? took fastest?)
    - Integrates with trip_enhancer.py workflow
    """
    
    def __init__(self):
        """
        Initialize Route Analyzer
        """
        self.logger = logging.getLogger(__name__)
        
        # Initialize backend reconstructor.
        # RouteReconstructor now knows the default servers, so we pass no arguments.
        print("Initializing Route Analyzer...")
        self.reconstructor = RouteReconstructor()
        
        print("✓ Route Analyzer ready")
    
    def analyze_trip_route(self,
                          trip_segments: pd.DataFrame,
                          origin_poi: Optional[Dict] = None,
                          dest_poi: Optional[Dict] = None,
                          modality: Optional[str] = None) -> Optional[RouteAnalysis]:
        """
        Analyze a trip's route - main entry point for trip_enhancer
        
        Args:
            trip_segments: DataFrame with trip segments from validator
            origin_poi: Origin POI data (optional, for context)
            dest_poi: Destination POI data (optional, for context)
            modality: Transportation modality (if not in segments)
            
        Returns:
            RouteAnalysis object or None if failed
        """
        # Extract modality
        if modality is None:
            modality = trip_segments.iloc[0].get('modality', 'unknown')
        
        # Extract coordinates from segments
        coordinates = self._extract_coordinates(trip_segments)
        
        if len(coordinates) < 2:
            self.logger.warning("Not enough coordinates for route matching")
            return None
        
        # Get trip metadata
        trip_id = trip_segments.iloc[0].get('trip_id', 'unknown')
        
        # Extract timestamps if available
        timestamps = self._extract_timestamps(trip_segments)
        
        # Use reconstructor to match actual route
        print(f"    → Matching route to network ({len(coordinates)} points)...")
        actual_route = self.reconstructor.reconstruct_route(
            coordinates=coordinates,
            modality=modality,
            timestamps=timestamps
        )
        
        if not actual_route:
            self.logger.warning(f"Could not reconstruct route for trip {trip_id}")
            return None
        
        print(f"    ✓ Route matched: {actual_route.total_distance_meters:.0f}m, "
              f"{actual_route.total_duration_seconds:.0f}s")
        
        # Generate alternative routes using reconstructor
        print(f"    → Generating alternative routes...")
        alternative_routes = self.reconstructor.generate_alternative_routes(
            start=coordinates[0],
            end=coordinates[-1],
            modality=modality,
            actual_distance=actual_route.total_distance_meters,
            max_alternatives=3
        )
        
        if alternative_routes:
            print(f"    ✓ Found {len(alternative_routes)} alternative routes")
        else:
            print(f"    ⚠ No alternative routes found")
        
        # Calculate route characteristics
        characteristics = self.reconstructor.calculate_route_characteristics(actual_route)
        
        # Create route analysis with comparison metrics
        analysis = self._create_route_analysis(
            trip_id=trip_id,
            actual_route=actual_route,
            alternatives=alternative_routes,
            modality=modality,
            characteristics=characteristics
        )
        
        return analysis
    
    def _extract_coordinates(self, trip_segments: pd.DataFrame) -> List[Tuple[float, float]]:
        """
        Extract (lat, lon) coordinates from trip segments
        Note: route_reconstructor expects (lat, lon) not (lon, lat)
        """
        coordinates = []
        
        # Add origin of first segment
        first_seg = trip_segments.iloc[0]
        coordinates.append((first_seg['origin_lat'], first_seg['origin_long']))
        
        # Add destinations of all segments (avoiding duplicates)
        for idx, seg in trip_segments.iterrows():
            dest_coord = (seg['destination_lat'], seg['destination_long'])
            
            # Check if different from last coordinate (tolerance for GPS noise)
            if not coordinates or self._coords_different(dest_coord, coordinates[-1]):
                coordinates.append(dest_coord)
        
        return coordinates
    
    def _coords_different(self, coord1: Tuple[float, float], 
                         coord2: Tuple[float, float],
                         threshold: float = 0.00001) -> bool:
        """Check if two coordinates are meaningfully different"""
        return (abs(coord1[0] - coord2[0]) > threshold or 
                abs(coord1[1] - coord2[1]) > threshold)
    
    def _extract_timestamps(self, trip_segments: pd.DataFrame) -> Optional[List[datetime]]:
        """Extract timestamps for each coordinate"""
        try:
            timestamps = []
            
            # Add start time of first segment
            first_seg = trip_segments.iloc[0]
            timestamps.append(pd.to_datetime(first_seg['start_timestamp']))
            
            # Add end times of all segments
            for idx, seg in trip_segments.iterrows():
                timestamps.append(pd.to_datetime(seg['end_timestamp']))
            
            return timestamps
        except Exception as e:
            self.logger.warning(f"Could not extract timestamps: {e}")
            return None
    
    def _create_route_analysis(self,
                              trip_id: str,
                              actual_route: Route,
                              alternatives: List[Route],
                              modality: str,
                              characteristics: Dict) -> RouteAnalysis:
        """
        Create RouteAnalysis with comparison metrics
        This is where we add value beyond route_reconstructor
        """
        
        # Convert Route segments to dict format
        actual_segments = [seg.to_dict() for seg in actual_route.segments]
        
        # Convert alternative Routes to AlternativeRoute format
        alternative_route_list = []
        
        for alt_route in alternatives:
            # Use reconstructor's comparison logic
            comparison = self.reconstructor.compare_routes(actual_route, alt_route)
            is_common_sense, reason = self.reconstructor.is_common_sense_alternative(
                actual_route, alt_route
            )
            
            # Calculate ratios
            distance_ratio = (alt_route.total_distance_meters / 
                            actual_route.total_distance_meters if actual_route.total_distance_meters > 0 else 1.0)
            duration_ratio = (alt_route.total_duration_seconds / 
                            actual_route.total_duration_seconds if actual_route.total_duration_seconds > 0 else 1.0)
            
            # Determine route type
            route_type = self._classify_alternative_route(
                alt_route, alternatives, actual_route
            )
            
            alt = AlternativeRoute(
                route_id=alt_route.route_id,
                distance_meters=alt_route.total_distance_meters,
                duration_seconds=alt_route.total_duration_seconds,
                geometry=alt_route.polyline,
                is_common_sense=is_common_sense,
                distance_ratio=distance_ratio,
                duration_ratio=duration_ratio,
                route_type=route_type
            )
            
            alternative_route_list.append(alt)
        
        # Find shortest and fastest alternatives
        shortest = None
        fastest = None
        
        if alternative_route_list:
            shortest = min(alternative_route_list, key=lambda x: x.distance_meters)
            fastest = min(alternative_route_list, key=lambda x: x.duration_seconds)
        
        # Determine if traveler took shortest/fastest route
        took_shortest = None
        took_fastest = None
        
        if shortest:
            # Consider "took shortest" if within 5% of shortest distance
            distance_diff_pct = abs(actual_route.total_distance_meters - shortest.distance_meters) / shortest.distance_meters
            took_shortest = distance_diff_pct < 0.05
        
        if fastest:
            # Consider "took fastest" if within 5% of fastest duration
            duration_diff_pct = abs(actual_route.total_duration_seconds - fastest.duration_seconds) / fastest.duration_seconds
            took_fastest = duration_diff_pct < 0.05
        
        # Create analysis
        analysis = RouteAnalysis(
            trip_id=trip_id,
            actual_route_distance_m=actual_route.total_distance_meters,
            actual_route_duration_s=actual_route.total_duration_seconds,
            actual_route_geometry=actual_route.polyline,
            actual_route_segments=actual_segments,
            alternative_routes=alternative_route_list,
            modality=modality,
            route_quality=actual_route.metadata.get('osrm_confidence', 1.0),
            shortest_available_m=shortest.distance_meters if shortest else None,
            fastest_available_s=fastest.duration_seconds if fastest else None,
            took_shortest_route=took_shortest,
            took_fastest_route=took_fastest,
            road_type_distribution=characteristics.get('road_type_distribution'),
            average_speed_mps=characteristics.get('average_speed_mps')
        )
        
        return analysis
    
    def _classify_alternative_route(self, 
                                    route: Route,
                                    all_alternatives: List[Route],
                                    actual_route: Route) -> str:
        """Classify what type of alternative this is"""
        
        # Check if it's the shortest
        is_shortest = all(route.total_distance_meters <= alt.total_distance_meters 
                         for alt in all_alternatives)
        if is_shortest:
            return 'shortest'
        
        # Check if it's the fastest
        is_fastest = all(route.total_duration_seconds <= alt.total_duration_seconds 
                        for alt in all_alternatives)
        if is_fastest:
            return 'fastest'
        
        # Check if it's the recommended (first alternative from OSRM)
        if route.route_id.endswith('_alt1'):
            return 'recommended'
        
        return 'alternative'
    
    def get_route_statistics(self, analysis: RouteAnalysis) -> Dict:
        """
        Get summary statistics for a route analysis
        Useful for reporting and visualization
        """
        stats = {
            'trip_id': analysis.trip_id,
            'modality': analysis.modality,
            'actual_distance_km': round(analysis.actual_route_distance_m / 1000, 2),
            'actual_duration_min': round(analysis.actual_route_duration_s / 60, 1),
            'actual_speed_kmh': round(analysis.average_speed_mps * 3.6, 1) if analysis.average_speed_mps else None,
            'num_alternatives': len(analysis.alternative_routes),
            'num_common_sense_alternatives': sum(1 for r in analysis.alternative_routes if r.is_common_sense),
            'took_shortest': analysis.took_shortest_route,
            'took_fastest': analysis.took_fastest_route,
            'route_quality': round(analysis.route_quality, 2)
        }
        
        # Add comparison to shortest route
        if analysis.shortest_available_m:
            stats['distance_vs_shortest_pct'] = round(
                (analysis.actual_route_distance_m - analysis.shortest_available_m) / 
                analysis.shortest_available_m * 100, 1
            )
            stats['distance_vs_shortest_m'] = round(
                analysis.actual_route_distance_m - analysis.shortest_available_m, 0
            )
        
        # Add comparison to fastest route
        if analysis.fastest_available_s:
            stats['duration_vs_fastest_pct'] = round(
                (analysis.actual_route_duration_s - analysis.fastest_available_s) / 
                analysis.fastest_available_s * 100, 1
            )
            stats['duration_vs_fastest_s'] = round(
                analysis.actual_route_duration_s - analysis.fastest_available_s, 0
            )
        
        # Add road type distribution if available
        if analysis.road_type_distribution:
            stats['road_types'] = analysis.road_type_distribution
        
        return stats
    
    def explain_route_choice(self, analysis: RouteAnalysis) -> str:
        """
        Generate human-readable explanation of route choice
        Useful for understanding traveler preferences
        """
        explanation = []
        
        # Basic route info
        explanation.append(f"Trip {analysis.trip_id} via {analysis.modality}")
        explanation.append(f"Distance: {analysis.actual_route_distance_m/1000:.1f} km")
        explanation.append(f"Duration: {analysis.actual_route_duration_s/60:.1f} min")
        
        # Route choice analysis
        if analysis.took_shortest_route and analysis.took_fastest_route:
            explanation.append("\n✓ Traveler took the optimal route (shortest AND fastest)")
        elif analysis.took_shortest_route:
            explanation.append("\n✓ Traveler took the shortest route")
            if analysis.fastest_available_s:
                time_diff = analysis.actual_route_duration_s - analysis.fastest_available_s
                explanation.append(f"  (but ~{time_diff:.0f}s slower than fastest alternative)")
        elif analysis.took_fastest_route:
            explanation.append("\n✓ Traveler took the fastest route")
            if analysis.shortest_available_m:
                dist_diff = analysis.actual_route_distance_m - analysis.shortest_available_m
                explanation.append(f"  (but ~{dist_diff:.0f}m longer than shortest alternative)")
        else:
            explanation.append("\n? Traveler did not take shortest or fastest route")
            if analysis.shortest_available_m:
                dist_pct = ((analysis.actual_route_distance_m - analysis.shortest_available_m) / 
                           analysis.shortest_available_m * 100)
                explanation.append(f"  Route was {dist_pct:.1f}% longer than shortest")
            if analysis.fastest_available_s:
                time_pct = ((analysis.actual_route_duration_s - analysis.fastest_available_s) / 
                           analysis.fastest_available_s * 100)
                explanation.append(f"  Route was {time_pct:.1f}% slower than fastest")
        
        # Alternative summary
        common_sense_alts = sum(1 for r in analysis.alternative_routes if r.is_common_sense)
        if common_sense_alts > 0:
            explanation.append(f"\n{common_sense_alts} 'common sense' alternative(s) available")
        
        return '\n'.join(explanation)


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    print("="*60)
    print("ROUTE ANALYZER - TEST (Refactored)")
    print("="*60)
    
    # Initialize analyzer (will initialize reconstructor internally)
    analyzer = RouteAnalyzer()
    
    # Test with example trip (Walnut Creek to Pleasant Hill)
    test_segments = pd.DataFrame([
        {
            'trip_id': 'test_trip_001',
            'origin_lat': 37.9101,
            'origin_long': -122.0652,
            'destination_lat': 37.9480,
            'destination_long': -122.0608,
            'start_timestamp': '2025-01-10 08:00:00',
            'end_timestamp': '2025-01-10 08:15:00',
            'trip_duration_sec': 900,
            'modality': 'driving'
        }
    ])
    
    print("\nAnalyzing test trip...")
    print(f"Origin: Walnut Creek (37.9101, -122.0652)")
    print(f"Destination: Pleasant Hill (37.9480, -122.0608)")
    print(f"Modality: driving")
    
    # Analyze route
    analysis = analyzer.analyze_trip_route(test_segments)
    
    if analysis:
        print("\n" + "="*60)
        print("ROUTE ANALYSIS RESULTS")
        print("="*60)
        
        # Get statistics
        stats = analyzer.get_route_statistics(analysis)
        print("\nStatistics:")
        for key, value in stats.items():
            if key != 'road_types':
                print(f"  {key}: {value}")
        
        # Get explanation
        print("\n" + "-"*60)
        explanation = analyzer.explain_route_choice(analysis)
        print(explanation)
        print("-"*60)
        
        # Show alternatives detail
        if analysis.alternative_routes:
            print("\nAlternative Routes Detail:")
            for i, alt in enumerate(analysis.alternative_routes, 1):
                print(f"\n  {i}. {alt.route_type.upper()}")
                print(f"     Distance: {alt.distance_meters:.0f}m ({alt.distance_ratio:.2%} of actual)")
                print(f"     Duration: {alt.duration_seconds:.0f}s ({alt.duration_ratio:.2%} of actual)")
                print(f"     Common sense: {alt.is_common_sense}")
        
    else:
        print("\n✗ Route analysis failed")
    
    print("\n" + "="*60)