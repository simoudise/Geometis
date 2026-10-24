"""
Route Reconstructor Module
Maps GPS breadcrumbs to actual road networks using OSRM
Generates alternative routes and detects transit usage
"""

import requests
import polyline
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import logging


@dataclass
class RouteSegment:
    """A segment of a route on a specific road"""
    segment_id: str
    road_name: str
    road_type: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    distance_meters: float
    duration_seconds: float
    geometry: str  # Encoded polyline
    
    def to_dict(self) -> Dict:
        return {
            'segment_id': self.segment_id,
            'road_name': self.road_name,
            'road_type': self.road_type,
            'start_coordinates': {
                'latitude': self.start_lat,
                'longitude': self.start_lon
            },
            'end_coordinates': {
                'latitude': self.end_lat,
                'longitude': self.end_lon
            },
            'distance_meters': round(self.distance_meters, 2),
            'duration_seconds': round(self.duration_seconds, 1),
            'geometry': self.geometry
        }


@dataclass
class Route:
    """A complete route with metadata"""
    route_id: str
    route_type: str  # 'actual', 'alternative', 'transit'
    modality: str  # 'driving', 'walking', 'bicycling', 'transit'
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    total_distance_meters: float
    total_duration_seconds: float
    segments: List[RouteSegment]
    polyline: str
    metadata: Dict
    
    def to_dict(self) -> Dict:
        return {
            'route_id': self.route_id,
            'route_type': self.route_type,
            'modality': self.modality,
            'start_coordinates': {
                'latitude': self.start_lat,
                'longitude': self.start_lon
            },
            'end_coordinates': {
                'latitude': self.end_lat,
                'longitude': self.end_lon
            },
            'total_distance_meters': round(self.total_distance_meters, 2),
            'total_duration_seconds': round(self.total_duration_seconds, 1),
            'polyline': self.polyline,
            'segments': [seg.to_dict() for seg in self.segments],
            'metadata': self.metadata
        }


class RouteReconstructor:
    """
    Reconstructs actual routes from GPS traces using OSRM
    Generates alternative "common sense" routes
    Detects transit usage by matching to GTFS routes
    """
    
    # OSRM profiles for different modalities
    OSRM_PROFILES = {
        'driving': 'car',
        'walking': 'foot',
        'bicycling': 'bike'
    }
    
    DEFAULT_OSRM_HOSTS = {
        'driving': 'http://localhost:5001',
        'walking': 'http://localhost:5002',
        'bicycling': 'http://localhost:5002'
    }

    # Alternative route search tolerances (as fraction of actual distance)
    ROUTE_TOLERANCES = {
        'walking': 0.10,    # ±10% for walking
        'bicycling': 0.15,  # ±15% for cycling
        'driving': 0.20     # ±20% for driving
    }
    
    def __init__(self, osrm_hosts: Dict[str, str] = None, kg_file: Optional[str] = None):
        """
        Initialize Route Reconstructor
        
        Args:
            osrm_hosts: Dictionary mapping modality to OSRM server URL
            kg_file: Optional knowledge graph for transit matching
        """
        if osrm_hosts is None:
            self.osrm_hosts = self.DEFAULT_OSRM_HOSTS
        else:
            self.osrm_hosts = osrm_hosts
            
        self.logger = logging.getLogger(__name__)
        
        # Test OSRM connectivity for all hosts
        print("Testing OSRM server connections...")
        for modality, host in self.osrm_hosts.items():
            # A simple route request is a better health check than the old /health endpoint
            health_check_url = f"{host.rstrip('/')}/route/v1/{self.OSRM_PROFILES.get(modality, 'car')}/-0.0001,0.0001;-0.0002,0.0002"
            try:
                response = requests.get(health_check_url, timeout=2)
                if response.status_code == 200:
                    print(f"  ✓ Connected to '{modality}' server: {host}")
                else:
                    print(f"  ⚠ '{modality}' server ({host}) responded with status {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"  ⚠ Could not connect to '{modality}' server: {host} ({e})")
        
        # TODO: Load knowledge graph for transit matching
        self.kg = None
        if kg_file:
            pass  # Load graph with GTFS data
    
    def reconstruct_route(self,
                         coordinates: List[Tuple[float, float]],
                         modality: str = 'driving',
                         timestamps: Optional[List[datetime]] = None) -> Optional[Route]:
        """
        Reconstruct actual route from GPS breadcrumbs
        
        Args:
            coordinates: List of (lat, lon) tuples
            modality: Transportation mode
            timestamps: Optional timestamps for each coordinate
            
        Returns:
            Route object with matched road segments
        """
        if len(coordinates) < 2:
            self.logger.error("Need at least 2 coordinates to reconstruct route")
            return None
        
        # Use OSRM match service to snap GPS trace to roads
        matched_route = self._osrm_match(coordinates, modality)
        
        if not matched_route:
            # Fallback: use simple routing between first and last point
            self.logger.warning("OSRM matching failed, using simple routing")
            matched_route = self._osrm_route(
                coordinates[0], coordinates[-1], modality
            )
        
        if not matched_route:
            self.logger.error("Route reconstruction failed")
            return None
        
        # Parse OSRM response into Route object
        route = self._parse_osrm_response(
            matched_route,
            coordinates[0],
            coordinates[-1],
            modality,
            route_type='actual'
        )
        
        return route
    
    def generate_alternative_routes(self,
                                    start: Tuple[float, float],
                                    end: Tuple[float, float],
                                    modality: str,
                                    actual_distance: float,
                                    max_alternatives: int = 2) -> List[Route]:
        """
        Generate "common sense" alternative routes
        Routes must be within tolerance of actual distance
        
        Args:
            start: Starting coordinates (lat, lon)
            end: Ending coordinates (lat, lon)
            modality: Transportation mode
            actual_distance: Distance of actual route (meters)
            max_alternatives: Maximum number of alternatives
            
        Returns:
            List of alternative Route objects
        """
        tolerance = self.ROUTE_TOLERANCES.get(modality, 0.15)
        min_distance = actual_distance * (1 - tolerance)
        max_distance = actual_distance * (1 + tolerance)
        
        alternatives = []
        
        # Use OSRM alternative routes
        alternative_responses = self._osrm_alternatives(start, end, modality, max_alternatives + 2)
        
        for i, alt_response in enumerate(alternative_responses):
            route = self._parse_osrm_response(
                alt_response,
                start,
                end,
                modality,
                route_type='alternative',
                route_id_suffix=f"_alt{i+1}"
            )
            
            if route:
                # Check if within distance tolerance
                if min_distance <= route.total_distance_meters <= max_distance:
                    alternatives.append(route)
                    
                    if len(alternatives) >= max_alternatives:
                        break
        
        return alternatives
    
    def _osrm_match(self, coordinates: List[Tuple[float, float]], modality: str) -> Optional[Dict]:
        """
        Use OSRM match service to snap GPS trace to roads
        """
        # Get the specific host for this modality, falling back to the driving server
        host = self.osrm_hosts.get(modality, self.osrm_hosts.get('driving'))
        profile = self.OSRM_PROFILES.get(modality, 'car')
        
        # Format coordinates into a string like 'lon1,lat1;lon2,lat2;...'
        coord_string = ";".join([f"{lon},{lat}" for lat, lon in coordinates])
        
        url = f"{host.rstrip('/')}/match/v1/{profile}/{coord_string}"
        
        params = {
            'overview': 'full',
            'geometries': 'polyline',
            'steps': 'true',
            'annotations': 'true'
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') == 'Ok' and data.get('matchings'):
                return data['matchings'][0]
            else:
                self.logger.warning(f"OSRM match failed: {data.get('code', 'unknown')}")
                return None
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"OSRM match request failed: {e}")
            return None
    
    def _osrm_route(self, start: Tuple[float, float], end: Tuple[float, float], 
                    modality: str) -> Optional[Dict]:
        """
        Use OSRM route service for simple routing
        """
        # Get the specific host for this modality, falling back to the driving server
        host = self.osrm_hosts.get(modality, self.osrm_hosts.get('driving'))
        profile = self.OSRM_PROFILES.get(modality, 'car')

        start_lon, start_lat = start[1], start[0]
        end_lon, end_lat = end[1], end[0]
        
        url = f"{host.rstrip('/')}/route/v1/{profile}/{start_lon},{start_lat};{end_lon},{end_lat}"
 
        params = {
            'overview': 'full',
            'geometries': 'polyline',
            'steps': 'true'
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') == 'Ok' and data.get('routes'):
                return data['routes'][0]
            else:
                return None
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"OSRM route request failed: {e}")
            return None
    
    def _osrm_alternatives(self, start: Tuple[float, float], end: Tuple[float, float],
                            modality: str, max_alternatives: int) -> List[Dict]:
        """
        Get alternative routes from OSRM
        """
        # Get the specific host for this modality, falling back to the driving server
        host = self.osrm_hosts.get(modality, self.osrm_hosts.get('driving'))
        profile = self.OSRM_PROFILES.get(modality, 'car')

        start_lon, start_lat = start[1], start[0]
        end_lon, end_lat = end[1], end[0]

        url = f"{host.rstrip('/')}/route/v1/{profile}/{start_lon},{start_lat};{end_lon},{end_lat}"
        
        params = {
            'overview': 'full',
            'geometries': 'polyline',
            'steps': 'true',
            'alternatives': 'true',
            'number': max_alternatives
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') == 'Ok' and data.get('routes'):
                # Return all routes except the first (that's the main route)
                return data['routes'][1:]
            else:
                return []
                
        except Exception as e:
            self.logger.error(f"OSRM alternatives request failed: {e}")
            return []
    
    def _parse_osrm_response(self, osrm_data: Dict, start: Tuple[float, float],
                            end: Tuple[float, float], modality: str, route_type: str,
                            route_id_suffix: str = "") -> Optional[Route]:
        """
        Parse OSRM response into Route object
        """
        try:
            # Extract basic route info
            total_distance = osrm_data.get('distance', 0)
            total_duration = osrm_data.get('duration', 0)
            route_polyline = osrm_data.get('geometry', '')
            
            # Parse legs and steps into segments
            segments = []
            legs = osrm_data.get('legs', [])
            
            segment_counter = 0
            for leg in legs:
                steps = leg.get('steps', [])
                
                for step in steps:
                    # Extract step details
                    step_distance = step.get('distance', 0)
                    step_duration = step.get('duration', 0)
                    step_name = step.get('name', 'Unnamed Road')
                    step_mode = step.get('mode', 'unknown')
                    
                    # Get step coordinates
                    maneuver = step.get('maneuver', {})
                    step_location = maneuver.get('location', [0, 0])
                    
                    # Create segment
                    segment = RouteSegment(
                        segment_id=f"SEG_{segment_counter}",
                        road_name=step_name,
                        road_type=self._classify_road_type(step, modality),
                        start_lat=step_location[1] if step_location else 0,
                        start_lon=step_location[0] if step_location else 0,
                        end_lat=step_location[1] if step_location else 0,  # Approximate
                        end_lon=step_location[0] if step_location else 0,
                        distance_meters=step_distance,
                        duration_seconds=step_duration,
                        geometry=step.get('geometry', '')
                    )
                    
                    segments.append(segment)
                    segment_counter += 1
            
            # Create route
            route_id = f"ROUTE_{route_type}_{modality}{route_id_suffix}"
            
            route = Route(
                route_id=route_id,
                route_type=route_type,
                modality=modality,
                start_lat=start[0],
                start_lon=start[1],
                end_lat=end[0],
                end_lon=end[1],
                total_distance_meters=total_distance,
                total_duration_seconds=total_duration,
                segments=segments,
                polyline=route_polyline,
                metadata={
                    'osrm_confidence': osrm_data.get('confidence', 1.0),
                    'legs_count': len(legs),
                    'steps_count': sum(len(leg.get('steps', [])) for leg in legs)
                }
            )
            
            return route
            
        except Exception as e:
            self.logger.error(f"Failed to parse OSRM response: {e}")
            return None
    
    def _classify_road_type(self, step: Dict, modality: str) -> str:
        """
        Classify road type from OSRM step data
        """
        # Try to get from step mode or ref
        mode = step.get('mode', '')
        ref = step.get('ref', '')
        
        # Map to UKO road types
        if 'motorway' in mode.lower() or 'highway' in ref.lower():
            return 'uko:Motorway'
        elif 'trunk' in mode.lower():
            return 'uko:TrunkRoad'
        elif 'primary' in mode.lower():
            return 'uko:PrimaryRoad'
        elif 'secondary' in mode.lower():
            return 'uko:SecondaryRoad'
        elif 'tertiary' in mode.lower():
            return 'uko:TertiaryRoad'
        elif 'residential' in mode.lower():
            return 'uko:ResidentialRoad'
        elif modality == 'walking':
            return 'uko:Sidewalk'
        elif modality == 'bicycling':
            return 'uko:BicycleLane'
        else:
            return 'uko:UnclassifiedRoad'
    
    def detect_transit_usage(self, 
                            coordinates: List[Tuple[float, float]],
                            timestamps: List[datetime]) -> Optional[Dict]:
        """
        Detect if trip used public transit by matching to GTFS routes
        
        Args:
            coordinates: GPS trace
            timestamps: Corresponding timestamps
            
        Returns:
            Transit detection result with route info
        """
        # TODO: Implement transit detection using GTFS data from KG
        # Strategy:
        # 1. Check if speeds indicate vehicle transport (but not personal car)
        # 2. Match coordinates to known transit routes
        # 3. Check if stops align with transit stops
        # 4. Look for boarding/alighting patterns
        
        return None
    
    def calculate_route_characteristics(self, route: Route) -> Dict:
        """
        Calculate additional route characteristics
        - Elevation profile (if available)
        - Road type distribution
        - Speed profile
        - Complexity metrics
        """
        characteristics = {
            'road_type_distribution': {},
            'average_speed_mps': route.total_distance_meters / route.total_duration_seconds if route.total_duration_seconds > 0 else 0,
            'segment_count': len(route.segments),
            'unique_roads': len(set(seg.road_name for seg in route.segments))
        }
        
        # Road type distribution
        for segment in route.segments:
            road_type = segment.road_type.split(':')[-1]
            characteristics['road_type_distribution'][road_type] = \
                characteristics['road_type_distribution'].get(road_type, 0) + segment.distance_meters
        
        # Normalize to percentages
        total_dist = route.total_distance_meters
        if total_dist > 0:
            for road_type in characteristics['road_type_distribution']:
                characteristics['road_type_distribution'][road_type] = \
                    characteristics['road_type_distribution'][road_type] / total_dist * 100
        
        return characteristics
    
    def compare_routes(self, route1: Route, route2: Route) -> Dict:
        """
        Compare two routes (e.g., actual vs alternative)
        
        Returns:
            Comparison metrics
        """
        comparison = {
            'distance_difference_meters': route2.total_distance_meters - route1.total_distance_meters,
            'distance_difference_percent': ((route2.total_distance_meters - route1.total_distance_meters) / 
                                           route1.total_distance_meters * 100) if route1.total_distance_meters > 0 else 0,
            'duration_difference_seconds': route2.total_duration_seconds - route1.total_duration_seconds,
            'duration_difference_percent': ((route2.total_duration_seconds - route1.total_duration_seconds) / 
                                           route1.total_duration_seconds * 100) if route1.total_duration_seconds > 0 else 0,
            'route1_is_shorter': route1.total_distance_meters < route2.total_distance_meters,
            'route1_is_faster': route1.total_duration_seconds < route2.total_duration_seconds
        }
        
        return comparison
    
    def is_common_sense_alternative(self, 
                                    actual_route: Route,
                                    alternative_route: Route) -> Tuple[bool, str]:
        """
        Determine if alternative route is a "common sense" choice
        
        Returns:
            (is_common_sense, reason)
        """
        modality = actual_route.modality
        tolerance = self.ROUTE_TOLERANCES.get(modality, 0.15)
        
        # Check distance tolerance
        distance_diff_pct = abs(alternative_route.total_distance_meters - actual_route.total_distance_meters) / \
                            actual_route.total_distance_meters
        
        if distance_diff_pct > tolerance:
            return False, f"Distance difference {distance_diff_pct*100:.1f}% exceeds tolerance {tolerance*100:.1f}%"
        
        # Check modality compatibility
        if alternative_route.modality != actual_route.modality:
            return False, "Different modality"
        
        # Check if unreasonably slower
        if alternative_route.total_duration_seconds > actual_route.total_duration_seconds * 1.5:
            return False, "Significantly slower"
        
        return True, "Within acceptable parameters"
    
    def decode_polyline(self, encoded: str) -> List[Tuple[float, float]]:
        """
        Decode polyline string to list of coordinates
        Uses Google's polyline encoding algorithm
        """
        try:
            decoded = polyline.decode(encoded)
            return decoded
        except Exception as e:
            self.logger.error(f"Failed to decode polyline: {e}")
            return []
    
    def encode_polyline(self, coordinates: List[Tuple[float, float]]) -> str:
        """
        Encode coordinates to polyline string
        """
        try:
            encoded = polyline.encode(coordinates)
            return encoded
        except Exception as e:
            self.logger.error(f"Failed to encode polyline: {e}")
            return ""
    
    def simplify_route(self, route: Route, tolerance_meters: float = 10.0) -> Route:
        """
        Simplify route by removing redundant points
        Uses Douglas-Peucker algorithm
        """
        # Decode polyline
        coords = self.decode_polyline(route.polyline)
        
        if not coords:
            return route
        
        # Simplify using tolerance
        simplified_coords = self._douglas_peucker(coords, tolerance_meters)
        
        # Re-encode
        simplified_polyline = self.encode_polyline(simplified_coords)
        
        # Create new route with simplified polyline
        simplified_route = Route(
            route_id=route.route_id + "_simplified",
            route_type=route.route_type,
            modality=route.modality,
            start_lat=route.start_lat,
            start_lon=route.start_lon,
            end_lat=route.end_lat,
            end_lon=route.end_lon,
            total_distance_meters=route.total_distance_meters,
            total_duration_seconds=route.total_duration_seconds,
            segments=route.segments,
            polyline=simplified_polyline,
            metadata={**route.metadata, 'simplified': True, 'original_points': len(coords), 'simplified_points': len(simplified_coords)}
        )
        
        return simplified_route
    
    def _douglas_peucker(self, points: List[Tuple[float, float]], tolerance: float) -> List[Tuple[float, float]]:
        """
        Douglas-Peucker algorithm for line simplification
        """
        if len(points) < 3:
            return points
        
        # Find point with maximum distance from line
        max_distance = 0
        max_index = 0
        
        for i in range(1, len(points) - 1):
            distance = self._perpendicular_distance(points[i], points[0], points[-1])
            if distance > max_distance:
                max_distance = distance
                max_index = i
        
        # If max distance is greater than tolerance, recursively simplify
        if max_distance > tolerance:
            # Recursive call
            results1 = self._douglas_peucker(points[:max_index+1], tolerance)
            results2 = self._douglas_peucker(points[max_index:], tolerance)
            
            # Combine results
            return results1[:-1] + results2
        else:
            return [points[0], points[-1]]
    
    def _perpendicular_distance(self, point: Tuple[float, float], 
                                line_start: Tuple[float, float],
                                line_end: Tuple[float, float]) -> float:
        """
        Calculate perpendicular distance from point to line
        Returns distance in meters (approximate)
        """
        # Simple approximation using Haversine for small distances
        x0, y0 = point
        x1, y1 = line_start
        x2, y2 = line_end
        
        # Convert to approximate meters (at this latitude)
        lat_to_m = 111000
        lon_to_m = 111000 * np.cos(np.radians(x0))
        
        x0_m, y0_m = x0 * lat_to_m, y0 * lon_to_m
        x1_m, y1_m = x1 * lat_to_m, y1 * lon_to_m
        x2_m, y2_m = x2 * lat_to_m, y2 * lon_to_m
        
        # Calculate perpendicular distance
        num = abs((y2_m - y1_m) * x0_m - (x2_m - x1_m) * y0_m + x2_m * y1_m - y2_m * x1_m)
        den = np.sqrt((y2_m - y1_m)**2 + (x2_m - x1_m)**2)
        
        if den == 0:
            return 0
        
        return num / den


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python route_reconstructor.py <osrm_host> [mode]")
        print("Example: python route_reconstructor.py http://localhost:5000 driving")
        sys.exit(1)
    
    osrm_host = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else 'driving'
    
    # Initialize reconstructor
    # For testing, we might pass a dictionary of hosts
    # In the main script, the orchestrator will pass the dictionary
    hosts_dict = {
        'driving': osrm_host,
        'walking': 'http://localhost:5002',
        'bicycling': 'http://localhost:5002'
    }
    reconstructor = RouteReconstructor(osrm_hosts=hosts_dict)
    
    # Test with example route (Walnut Creek to Pleasant Hill)
    test_coordinates = [
        (37.9101, -122.0652),  # Downtown Walnut Creek
        (3.9200, -122.0600),  # Mid-point
        (37.9298, -122.0574)   # Pleasant Hill BART
    ]
    
    print("\n" + "="*60)
    print("TESTING ROUTE RECONSTRUCTION")
    print("="*60)
    print(f"Mode: {mode}")
    print(f"Coordinates: {len(test_coordinates)} points")
    
    # Reconstruct actual route
    print("\n--- Reconstructing Actual Route ---")
    actual_route = reconstructor.reconstruct_route(test_coordinates, mode)
    
    if actual_route:
        print(f"✓ Route reconstructed successfully")
        print(f"  Distance: {actual_route.total_distance_meters:.1f}m")
        print(f"  Duration: {actual_route.total_duration_seconds:.1f}s")
        print(f"  Segments: {len(actual_route.segments)}")
        
        # Calculate characteristics
        characteristics = reconstructor.calculate_route_characteristics(actual_route)
        print(f"\nRoute Characteristics:")
        print(f"  Average speed: {characteristics['average_speed_mps']*3.6:.1f} km/h")
        print(f"  Unique roads: {characteristics['unique_roads']}")
        
        # Generate alternatives
        print("\n--- Generating Alternative Routes ---")
        alternatives = reconstructor.generate_alternative_routes(
            test_coordinates[0],
            test_coordinates[-1],
            mode,
            actual_route.total_distance_meters,
            max_alternatives=2
        )
        
        if alternatives:
            print(f"✓ Found {len(alternatives)} alternative routes")
            for i, alt in enumerate(alternatives, 1):
                comparison = reconstructor.compare_routes(actual_route, alt)
                is_common_sense, reason = reconstructor.is_common_sense_alternative(actual_route, alt)
                
                print(f"\nAlternative {i}:")
                print(f"  Distance: {alt.total_distance_meters:.1f}m ({comparison['distance_difference_percent']:+.1f}%)")
                print(f"  Duration: {alt.total_duration_seconds:.1f}s ({comparison['duration_difference_percent']:+.1f}%)")
                print(f"  Common sense: {is_common_sense} ({reason})")
        else:
            print("  No suitable alternatives found")
    else:
        print("✗ Route reconstruction failed")
    
    print("\n" + "="*60)