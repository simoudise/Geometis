"""
Trucker Profile Manager
Builds and maintains behavioral profiles for commercial truck drivers
Handles short-haul, medium-haul, and long-haul trucking patterns
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
from dataclasses import dataclass, asdict
import numpy as np
from math import radians, sin, cos, sqrt, atan2


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two coordinates"""
    R = 6371000  # Earth radius in meters
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    return R * c


@dataclass
class DepotCandidate:
    """Candidate depot/terminal for a trucker"""
    poi_id: str
    poi_name: str
    poi_type: str
    coordinates: Tuple[float, float]
    
    # Shift patterns
    shift_start_count: int  # Trips originating here
    shift_end_count: int    # Trips ending here
    avg_shift_start_time: str  # HH:MM format
    avg_shift_end_time: str
    
    # Visit patterns
    total_visits: int
    weekday_visits: int
    weekend_visits: int
    avg_dwell_minutes: float
    
    confidence: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DeliveryTerritory:
    """Geographic territory where trucker operates"""
    territory_id: str
    territory_name: str
    
    # Geographic bounds
    center_lat: float
    center_lon: float
    radius_km: float
    
    # Delivery patterns
    unique_delivery_locations: int
    total_deliveries: int
    avg_deliveries_per_day: float
    
    # POI types delivered to
    common_delivery_types: Dict[str, int]  # poi_type -> count
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RoutePattern:
    """Recurring route pattern"""
    pattern_id: str
    pattern_type: str  # 'fixed_route', 'milk_run', 'point_to_point'
    
    # Route characteristics
    origin_poi_id: str
    destination_poi_id: str
    intermediate_stops: List[str]  # POI IDs
    
    frequency: int  # How many times this pattern observed
    avg_distance_km: float
    avg_duration_hours: float
    
    # Timing
    typical_days_of_week: List[str]
    typical_time_windows: List[str]  # ['08:00-10:00', '14:00-16:00']
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TruckerProfile:
    """
    Behavioral profile for commercial truck driver
    Handles short-haul, medium-haul, and long-haul patterns
    """
    trucker_id: str
    profile_start_date: str
    profile_end_date: str
    days_tracked: int
    total_trips: int
    
    # Haul classification
    haul_type: str  # 'short_haul', 'medium_haul', 'long_haul', 'mixed'
    avg_trip_distance_km: float
    
    # Depot/terminal locations
    primary_depot: Optional[DepotCandidate] = None
    secondary_depots: List[DepotCandidate] = None
    
    # Operating territories
    delivery_territories: List[DeliveryTerritory] = None
    
    # Route patterns
    recurring_routes: List[RoutePattern] = None
    
    # Customer/delivery patterns
    frequent_delivery_locations: Dict[str, Dict] = None  # poi_id -> stats
    
    # Shift patterns
    typical_shift_start_times: List[str] = None
    typical_shift_end_times: List[str] = None
    avg_shift_duration_hours: float = 0.0
    
    # Vehicle/fleet info
    vehicle_assignments: Dict[str, int] = None  # vehicle_id -> trip_count
    
    # Temporal patterns
    working_days_distribution: Dict[str, int] = None  # day_of_week -> count
    
    # Metadata
    last_updated: str = None
    profile_maturity: str = None  # 'cold_start', 'warming', 'mature'
    
    def __post_init__(self):
        if self.secondary_depots is None:
            self.secondary_depots = []
        if self.delivery_territories is None:
            self.delivery_territories = []
        if self.recurring_routes is None:
            self.recurring_routes = []
        if self.frequent_delivery_locations is None:
            self.frequent_delivery_locations = {}
        if self.typical_shift_start_times is None:
            self.typical_shift_start_times = []
        if self.typical_shift_end_times is None:
            self.typical_shift_end_times = []
        if self.vehicle_assignments is None:
            self.vehicle_assignments = {}
        if self.working_days_distribution is None:
            self.working_days_distribution = {}
        if self.last_updated is None:
            self.last_updated = datetime.now().isoformat()
        if self.profile_maturity is None:
            if self.days_tracked < 7:
                self.profile_maturity = 'cold_start'
            elif self.days_tracked < 21:
                self.profile_maturity = 'warming'
            else:
                self.profile_maturity = 'mature'
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        # Convert complex objects to dicts
        if self.primary_depot:
            data['primary_depot'] = self.primary_depot.to_dict()
        data['secondary_depots'] = [d.to_dict() for d in self.secondary_depots]
        data['delivery_territories'] = [t.to_dict() for t in self.delivery_territories]
        data['recurring_routes'] = [r.to_dict() for r in self.recurring_routes]
        return data


class TruckerProfileManager:
    """
    Manages trucker profiles for fleet management use case
    Handles short-haul, medium-haul, and long-haul patterns
    """
    
    # Haul type thresholds (km)
    SHORT_HAUL_THRESHOLD = 100   # < 100km per trip
    MEDIUM_HAUL_THRESHOLD = 400  # 100-400km per trip
    # Long haul: > 400km per trip
    
    # Depot detection parameters
    MIN_DEPOT_VISITS = 8  # Minimum visits to qualify as depot
    MIN_SHIFT_START_RATIO = 0.3  # 30% of trips should start from depot
    DEPOT_DWELL_MAX = 120  # Max 2 hours at depot (loading/unloading)
    
    # Territory detection parameters
    TERRITORY_MIN_DELIVERIES = 5  # Minimum deliveries in area
    TERRITORY_RADIUS_KM = 25  # Cluster deliveries within 25km
    
    # Route pattern detection
    MIN_ROUTE_REPETITIONS = 3  # Minimum times to recognize pattern
    ROUTE_SIMILARITY_THRESHOLD = 0.8  # 80% similar to be same route
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize trucker profile manager
        
        Args:
            storage_dir: Directory for persistent profile storage (optional)
        """
        self.storage_dir = storage_dir
        self.profiles = {}  # In-memory cache
        
        if storage_dir and not os.path.exists(storage_dir):
            os.makedirs(storage_dir)
    
    def get_profile(self, trucker_id: str) -> Optional[TruckerProfile]:
        """Get profile for a trucker"""
        # Check memory cache
        if trucker_id in self.profiles:
            return self.profiles[trucker_id]
        
        # Try to load from disk
        if self.storage_dir:
            profile = self._load_profile(trucker_id)
            if profile:
                self.profiles[trucker_id] = profile
                return profile
        
        return None
    
    def build_profile(self, trucker_id: str, trips: List[Dict]) -> TruckerProfile:
        """
        Build a trucker profile from trip history
        
        Args:
            trucker_id: Trucker identifier (driver ID)
            trips: List of enhanced trips with POI data and routes
            
        Returns:
            TruckerProfile object
        """
        if not trips:
            return TruckerProfile(
                trucker_id=trucker_id,
                profile_start_date=datetime.now().isoformat(),
                profile_end_date=datetime.now().isoformat(),
                days_tracked=0,
                total_trips=0,
                haul_type='unknown',
                avg_trip_distance_km=0.0
            )
        
        # Sort trips by time
        trips = sorted(trips, key=lambda t: t.get('start_time', ''))
        
        # Calculate date range
        start_date = trips[0].get('start_time', '')
        end_date = trips[-1].get('start_time', '')
        
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date)
        
        days_tracked = (end_date - start_date).days + 1
        
        # Calculate average trip distance
        distances = [t.get('distance_meters', 0) / 1000 for t in trips]
        avg_distance = np.mean(distances) if distances else 0.0
        
        # Classify haul type
        haul_type = self._classify_haul_type(distances)
        
        # Initialize profile
        profile = TruckerProfile(
            trucker_id=trucker_id,
            profile_start_date=start_date.isoformat(),
            profile_end_date=end_date.isoformat(),
            days_tracked=days_tracked,
            total_trips=len(trips),
            haul_type=haul_type,
            avg_trip_distance_km=avg_distance
        )
        
        # Analyze patterns based on haul type
        self._detect_depots(profile, trips)
        self._analyze_delivery_locations(profile, trips)
        self._detect_territories(profile, trips)
        self._detect_route_patterns(profile, trips)
        self._analyze_shift_patterns(profile, trips)
        self._analyze_vehicle_assignments(profile, trips)
        self._analyze_working_days(profile, trips)
        
        # Cache profile
        self.profiles[trucker_id] = profile
        
        # Save to disk if storage enabled
        if self.storage_dir:
            self._save_profile(profile)
        
        return profile
    
    def _classify_haul_type(self, distances: List[float]) -> str:
        """
        Classify trucker as short-haul, medium-haul, or long-haul
        
        Args:
            distances: List of trip distances in km
        """
        if not distances:
            return 'unknown'
        
        avg_distance = np.mean(distances)
        
        # Check distribution
        short_trips = sum(1 for d in distances if d < self.SHORT_HAUL_THRESHOLD)
        medium_trips = sum(1 for d in distances if self.SHORT_HAUL_THRESHOLD <= d < self.MEDIUM_HAUL_THRESHOLD)
        long_trips = sum(1 for d in distances if d >= self.MEDIUM_HAUL_THRESHOLD)
        
        total = len(distances)
        
        # If mostly one type (>60%), classify as that type
        if short_trips / total > 0.6:
            return 'short_haul'
        elif long_trips / total > 0.6:
            return 'long_haul'
        elif medium_trips / total > 0.6:
            return 'medium_haul'
        else:
            return 'mixed'
    
    def _detect_depots(self, profile: TruckerProfile, trips: List[Dict]):
        """
        Detect depot/terminal locations
        Depots are where shifts start and end
        """
        location_patterns = defaultdict(lambda: {
            'shift_starts': 0,
            'shift_ends': 0,
            'visits': 0,
            'dwell_times': [],
            'weekday_visits': 0,
            'weekend_visits': 0,
            'start_times': [],
            'end_times': [],
            'poi_data': None,
            'coordinates': None
        })
        
        # Group trips by day to identify shift boundaries
        trips_by_day = defaultdict(list)
        for trip in trips:
            start_time = trip.get('start_time')
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            
            day_key = start_time.date().isoformat()
            trips_by_day[day_key].append(trip)
        
        # Analyze each day's trips
        for day, day_trips in trips_by_day.items():
            if not day_trips:
                continue
            
            # Sort by time
            day_trips = sorted(day_trips, key=lambda t: t.get('start_time', ''))
            
            # First trip of day (shift start)
            first_trip = day_trips[0]
            origin_poi = first_trip.get('origin_poi')
            if origin_poi and origin_poi.get('uri'):
                poi_id = origin_poi['uri']
                pattern = location_patterns[poi_id]
                pattern['shift_starts'] += 1
                pattern['visits'] += 1
                pattern['poi_data'] = origin_poi
                pattern['coordinates'] = origin_poi.get('coordinates', {})
                
                start_time = first_trip.get('start_time')
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time)
                pattern['start_times'].append(start_time)
                
                if start_time.weekday() < 5:
                    pattern['weekday_visits'] += 1
                else:
                    pattern['weekend_visits'] += 1
            
            # Last trip of day (shift end)
            last_trip = day_trips[-1]
            dest_poi = last_trip.get('destination_poi')
            if dest_poi and dest_poi.get('uri'):
                poi_id = dest_poi['uri']
                pattern = location_patterns[poi_id]
                pattern['shift_ends'] += 1
                if pattern['poi_data'] is None:
                    pattern['visits'] += 1
                    pattern['poi_data'] = dest_poi
                    pattern['coordinates'] = dest_poi.get('coordinates', {})
                
                end_time = last_trip.get('end_time')
                if isinstance(end_time, str):
                    end_time = datetime.fromisoformat(end_time)
                pattern['end_times'].append(end_time)
                
                # Dwell time until next day's first trip (if available)
                dwell_time = last_trip.get('dwell_time', 0)
                if dwell_time > 0 and dwell_time < 12 * 3600:  # Max 12 hours
                    pattern['dwell_times'].append(dwell_time)
        
        # Identify depot candidates
        depot_candidates = []
        
        for poi_id, pattern in location_patterns.items():
            # Must have minimum visits
            if pattern['visits'] < self.MIN_DEPOT_VISITS:
                continue
            
            # Must be shift start location for significant portion of trips
            total_shifts = len(trips_by_day)
            shift_start_ratio = pattern['shift_starts'] / total_shifts
            
            if shift_start_ratio < self.MIN_SHIFT_START_RATIO:
                continue
            
            # Calculate average times
            avg_start_time = self._calculate_avg_time(pattern['start_times']) if pattern['start_times'] else '00:00'
            avg_end_time = self._calculate_avg_time(pattern['end_times']) if pattern['end_times'] else '00:00'
            avg_dwell = np.mean(pattern['dwell_times']) / 60 if pattern['dwell_times'] else 0
            
            # Calculate confidence
            confidence = self._calculate_depot_confidence(
                pattern['shift_starts'],
                pattern['shift_ends'],
                total_shifts,
                pattern['weekday_visits'] / pattern['visits'] if pattern['visits'] > 0 else 0
            )
            
            poi_data = pattern['poi_data']
            coords = pattern['coordinates']
            
            depot = DepotCandidate(
                poi_id=poi_id,
                poi_name=poi_data.get('name', 'Unknown Depot'),
                poi_type=poi_data.get('type', 'Unknown'),
                coordinates=(coords.get('latitude'), coords.get('longitude')) if coords else (None, None),
                shift_start_count=pattern['shift_starts'],
                shift_end_count=pattern['shift_ends'],
                avg_shift_start_time=avg_start_time,
                avg_shift_end_time=avg_end_time,
                total_visits=pattern['visits'],
                weekday_visits=pattern['weekday_visits'],
                weekend_visits=pattern['weekend_visits'],
                avg_dwell_minutes=avg_dwell,
                confidence=confidence
            )
            
            depot_candidates.append(depot)
        
        # Sort by confidence
        depot_candidates.sort(key=lambda d: d.confidence, reverse=True)
        
        # Assign primary and secondary depots
        if depot_candidates:
            profile.primary_depot = depot_candidates[0]
            profile.secondary_depots = depot_candidates[1:3]  # Top 2 secondary
    
    def _calculate_depot_confidence(self,
                                    shift_starts: int,
                                    shift_ends: int,
                                    total_shifts: int,
                                    weekday_ratio: float) -> float:
        """Calculate confidence that a location is a depot"""
        confidence = 0.0
        
        # Shift start frequency (0-0.40)
        start_ratio = shift_starts / total_shifts if total_shifts > 0 else 0
        confidence += start_ratio * 0.40
        
        # Shift end frequency (0-0.30)
        end_ratio = shift_ends / total_shifts if total_shifts > 0 else 0
        confidence += end_ratio * 0.30
        
        # Weekday pattern (0-0.20) - depots are primarily weekday
        confidence += weekday_ratio * 0.20
        
        # Both starts and ends (bonus 0-0.10)
        if shift_starts > 0 and shift_ends > 0:
            confidence += min(shift_starts, shift_ends) / total_shifts * 0.10
        
        return min(confidence, 1.0)
    
    def _analyze_delivery_locations(self, profile: TruckerProfile, trips: List[Dict]):
        """Analyze frequent delivery/customer locations"""
        delivery_stats = defaultdict(lambda: {
            'visits': 0,
            'total_distance_km': 0,
            'dwell_times': [],
            'visit_times': [],
            'poi_data': None
        })
        
        for trip in trips:
            dest_poi = trip.get('destination_poi')
            if not dest_poi or not dest_poi.get('uri'):
                continue
            
            poi_id = dest_poi['uri']
            stats = delivery_stats[poi_id]
            
            stats['visits'] += 1
            stats['total_distance_km'] += trip.get('distance_meters', 0) / 1000
            stats['dwell_times'].append(trip.get('dwell_time', 0))
            stats['poi_data'] = dest_poi
            
            start_time = trip.get('start_time')
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            stats['visit_times'].append(start_time)
        
        # Filter to frequent locations (3+ visits)
        for poi_id, stats in delivery_stats.items():
            if stats['visits'] >= 3:
                profile.frequent_delivery_locations[poi_id] = {
                    'visits': stats['visits'],
                    'avg_dwell_minutes': np.mean(stats['dwell_times']) / 60 if stats['dwell_times'] else 0,
                    'avg_distance_km': stats['total_distance_km'] / stats['visits'],
                    'poi_name': stats['poi_data'].get('name', 'Unknown'),
                    'poi_type': stats['poi_data'].get('type', 'Unknown')
                }
    
    def _detect_territories(self, profile: TruckerProfile, trips: List[Dict]):
        """
        Detect geographic territories where trucker operates
        Uses clustering of delivery locations
        """
        # Collect all delivery coordinates
        delivery_coords = []
        
        for trip in trips:
            dest_poi = trip.get('destination_poi')
            if dest_poi and dest_poi.get('coordinates'):
                coords = dest_poi['coordinates']
                lat = coords.get('latitude')
                lon = coords.get('longitude')
                if lat and lon:
                    delivery_coords.append((lat, lon, dest_poi))
        
        if not delivery_coords:
            return
        
        # Simple geographic clustering
        territories = self._cluster_territories(delivery_coords)
        
        profile.delivery_territories = territories
    
    def _cluster_territories(self, coords_with_poi: List[Tuple]) -> List[DeliveryTerritory]:
        """Cluster delivery locations into territories"""
        if not coords_with_poi:
            return []
        
        territories = []
        unclustered = coords_with_poi.copy()
        territory_id = 0
        
        while unclustered and len(territories) < 10:  # Max 10 territories
            # Start new territory with first unclustered point
            seed = unclustered[0]
            seed_lat, seed_lon, _ = seed
            
            # Find all points within radius
            cluster = []
            remaining = []
            
            for coord in unclustered:
                lat, lon, poi = coord
                distance_km = haversine_distance(seed_lat, seed_lon, lat, lon) / 1000
                
                if distance_km <= self.TERRITORY_RADIUS_KM:
                    cluster.append(coord)
                else:
                    remaining.append(coord)
            
            # Only create territory if it has minimum deliveries
            if len(cluster) >= self.TERRITORY_MIN_DELIVERIES:
                # Calculate center
                lats = [c[0] for c in cluster]
                lons = [c[1] for c in cluster]
                center_lat = np.mean(lats)
                center_lon = np.mean(lons)
                
                # Calculate actual radius
                max_dist = max(haversine_distance(center_lat, center_lon, lat, lon) / 1000 
                              for lat, lon, _ in cluster)
                
                # Count POI types
                poi_types = defaultdict(int)
                for _, _, poi in cluster:
                    poi_type = poi.get('type', 'Unknown').split(':')[-1]
                    poi_types[poi_type] += 1
                
                territory = DeliveryTerritory(
                    territory_id=f"territory_{territory_id}",
                    territory_name=f"Territory {territory_id + 1}",
                    center_lat=center_lat,
                    center_lon=center_lon,
                    radius_km=max_dist,
                    unique_delivery_locations=len(set(poi['uri'] for _, _, poi in cluster)),
                    total_deliveries=len(cluster),
                    avg_deliveries_per_day=0,  # TODO: Calculate from date distribution
                    common_delivery_types=dict(poi_types)
                )
                
                territories.append(territory)
                territory_id += 1
            
            unclustered = remaining
        
        return territories
    
    def _detect_route_patterns(self, profile: TruckerProfile, trips: List[Dict]):
        """
        Detect recurring route patterns
        Useful for medium-haul milk runs and short-haul delivery routes
        """
        # Group consecutive trips into potential routes
        route_sequences = []
        
        # For short/medium haul, look at daily sequences
        if profile.haul_type in ['short_haul', 'medium_haul', 'mixed']:
            trips_by_day = defaultdict(list)
            for trip in trips:
                start_time = trip.get('start_time')
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time)
                day_key = start_time.date().isoformat()
                trips_by_day[day_key].append(trip)
            
            for day, day_trips in trips_by_day.items():
                if len(day_trips) >= 2:  # At least 2 stops
                    route_sequences.append(sorted(day_trips, key=lambda t: t.get('start_time', '')))
        
        # Look for recurring patterns
        # TODO: Implement sophisticated route pattern matching
        # For now, just identify fixed origin-destination pairs
        
        od_pairs = defaultdict(lambda: {
            'count': 0,
            'distances': [],
            'durations': [],
            'days_of_week': [],
            'times': []
        })
        
        for trip in trips:
            origin_poi = trip.get('origin_poi')
            dest_poi = trip.get('destination_poi')
            
            if origin_poi and dest_poi and origin_poi.get('uri') and dest_poi.get('uri'):
                od_key = (origin_poi['uri'], dest_poi['uri'])
                pattern = od_pairs[od_key]
                
                pattern['count'] += 1
                pattern['distances'].append(trip.get('distance_meters', 0) / 1000)
                pattern['durations'].append(trip.get('duration_seconds', 0) / 3600)
                
                start_time = trip.get('start_time')
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time)
                
                pattern['days_of_week'].append(start_time.strftime('%A'))
                pattern['times'].append(start_time.strftime('%H:%M'))
        
        # Create route patterns from frequent OD pairs
        pattern_id = 0
        for (origin_id, dest_id), data in od_pairs.items():
            if data['count'] >= self.MIN_ROUTE_REPETITIONS:
                # Determine pattern type
                if data['count'] > profile.total_trips * 0.5:
                    pattern_type = 'fixed_route'
                else:
                    pattern_type = 'point_to_point'
                
                route_pattern = RoutePattern(
                    pattern_id=f"pattern_{pattern_id}",
                    pattern_type=pattern_type,
                    origin_poi_id=origin_id,
                    destination_poi_id=dest_id,
                    intermediate_stops=[],  # TODO: Detect intermediate stops
                    frequency=data['count'],
                    avg_distance_km=np.mean(data['distances']),
                    avg_duration_hours=np.mean(data['durations']),
                    typical_days_of_week=list(set(data['days_of_week'])),
                    typical_time_windows=[]  # TODO: Calculate time windows
                )
                
                profile.recurring_routes.append(route_pattern)
                pattern_id += 1
    
    def _analyze_shift_patterns(self, profile: TruckerProfile, trips: List[Dict]):
        """Analyze shift start/end times and durations"""
        trips_by_day = defaultdict(list)
        for trip in trips:
            start_time = trip.get('start_time')
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            day_key = start_time.date().isoformat()
            trips_by_day[day_key].append(trip)
        
        shift_starts = []
        shift_ends = []
        shift_durations = []
        
        for day, day_trips in trips_by_day.items():
            if not day_trips:
                continue
            
            day_trips = sorted(day_trips, key=lambda t: t.get('start_time', ''))
            
            # Shift start
            first_start = day_trips[0].get('start_time')
            if isinstance(first_start, str):
                first_start = datetime.fromisoformat(first_start)
            shift_starts.append(first_start.strftime('%H:%M'))
            
            # Shift end
            last_end = day_trips[-1].get('end_time')
            if isinstance(last_end, str):
                last_end = datetime.fromisoformat(last_end)
            shift_ends.append(last_end.strftime('%H:%M'))
            
            # Shift duration
            duration = (last_end - first_start).total_seconds() / 3600
            shift_durations.append(duration)
        
        profile.typical_shift_start_times = shift_starts
        profile.typical_shift_end_times = shift_ends
        profile.avg_shift_duration_hours = np.mean(shift_durations) if shift_durations else 0.0
    
    def _analyze_vehicle_assignments(self, profile: TruckerProfile, trips: List[Dict]):
        """Track which vehicles/trucks the driver uses"""
        vehicle_counts = defaultdict(int)
        
        for trip in trips:
            vehicle_id = trip.get('vehicle_id')
            if vehicle_id:
                vehicle_counts[vehicle_id] += 1
        
        profile.vehicle_assignments = dict(vehicle_counts)
    
    def _analyze_working_days(self, profile: TruckerProfile, trips: List[Dict]):
        """Analyze which days of week trucker typically works"""
        day_counts = defaultdict(int)
        
        for trip in trips:
            start_time = trip.get('start_time')
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            
            day_name = start_time.strftime('%A')
            day_counts[day_name] += 1
        
        profile.working_days_distribution = dict(day_counts)
    
    def _calculate_avg_time(self, datetimes: List[datetime]) -> str:
        """Calculate average time from list of datetimes"""
        if not datetimes:
            return '00:00'
        
        # Convert to minutes since midnight
        minutes = [(dt.hour * 60 + dt.minute) for dt in datetimes]
        avg_minutes = np.mean(minutes)
        
        hours = int(avg_minutes // 60)
        mins = int(avg_minutes % 60)
        
        return f"{hours:02d}:{mins:02d}"
    
    def _save_profile(self, profile: TruckerProfile):
        """Save profile to disk"""
        if not self.storage_dir:
            return
        
        filepath = os.path.join(self.storage_dir, f"{profile.trucker_id}.json")
        
        with open(filepath, 'w') as f:
            json.dump(profile.to_dict(), f, indent=2)
    
    def _load_profile(self, trucker_id: str) -> Optional[TruckerProfile]:
        """Load profile from disk"""
        if not self.storage_dir:
            return None
        
        filepath = os.path.join(self.storage_dir, f"{trucker_id}.json")
        
        if not os.path.exists(filepath):
            return None
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Convert nested objects back
            if data.get('primary_depot'):
                data['primary_depot'] = DepotCandidate(**data['primary_depot'])
            
            if data.get('secondary_depots'):
                data['secondary_depots'] = [
                    DepotCandidate(**d) for d in data['secondary_depots']
                ]
            
            if data.get('delivery_territories'):
                data['delivery_territories'] = [
                    DeliveryTerritory(**t) for t in data['delivery_territories']
                ]
            
            if data.get('recurring_routes'):
                data['recurring_routes'] = [
                    RoutePattern(**r) for r in data['recurring_routes']
                ]
            
            return TruckerProfile(**data)
        except Exception as e:
            print(f"Error loading profile for {trucker_id}: {e}")
            return None
    
    def get_profile_summary(self, trucker_id: str) -> Optional[Dict]:
        """Get human-readable profile summary"""
        profile = self.get_profile(trucker_id)
        
        if not profile:
            return None
        
        summary = {
            'trucker_id': trucker_id,
            'haul_type': profile.haul_type,
            'profile_maturity': profile.profile_maturity,
            'days_tracked': profile.days_tracked,
            'total_trips': profile.total_trips,
            'avg_trip_distance_km': round(profile.avg_trip_distance_km, 1),
            'avg_shift_duration_hours': round(profile.avg_shift_duration_hours, 1),
            'depot_identified': profile.primary_depot is not None,
            'territories_identified': len(profile.delivery_territories),
            'recurring_routes': len(profile.recurring_routes),
            'frequent_delivery_locations': len(profile.frequent_delivery_locations)
        }
        
        if profile.primary_depot:
            summary['primary_depot'] = {
                'name': profile.primary_depot.poi_name,
                'confidence': round(profile.primary_depot.confidence, 2),
                'shift_starts': profile.primary_depot.shift_start_count,
                'avg_start_time': profile.primary_depot.avg_shift_start_time
            }
        
        if profile.vehicle_assignments:
            most_used_vehicle = max(profile.vehicle_assignments.items(), key=lambda x: x[1])
            summary['primary_vehicle'] = {
                'vehicle_id': most_used_vehicle[0],
                'trip_count': most_used_vehicle[1]
            }
        
        # Working schedule
        if profile.working_days_distribution:
            summary['working_schedule'] = profile.working_days_distribution
        
        return summary
    
    def get_haul_type_description(self, haul_type: str) -> str:
        """Get human-readable description of haul type"""
        descriptions = {
            'short_haul': 'Short-haul (<100km) - Local delivery driver (e.g., UPS, Instacart)',
            'medium_haul': 'Medium-haul (100-400km) - Regional distribution (e.g., Safeway distribution)',
            'long_haul': 'Long-haul (>400km) - Interstate trucking (e.g., Schneider, JB Hunt)',
            'mixed': 'Mixed haul types - Combination of short, medium, and long trips'
        }
        return descriptions.get(haul_type, 'Unknown haul type')
    
    def is_depot_delivery(self, 
                         trucker_id: str, 
                         poi_id: str, 
                         confidence_threshold: float = 0.70) -> Tuple[bool, float]:
        """
        Check if POI is a depot for this trucker
        
        Returns:
            (is_depot, confidence)
        """
        profile = self.get_profile(trucker_id)
        
        if not profile:
            return False, 0.0
        
        # Check primary depot
        if profile.primary_depot and profile.primary_depot.poi_id == poi_id:
            return profile.primary_depot.confidence >= confidence_threshold, profile.primary_depot.confidence
        
        # Check secondary depots
        for depot in profile.secondary_depots:
            if depot.poi_id == poi_id:
                return depot.confidence >= confidence_threshold, depot.confidence
        
        return False, 0.0
    
    def get_territory_for_location(self, 
                                   trucker_id: str, 
                                   lat: float, 
                                   lon: float) -> Optional[DeliveryTerritory]:
        """
        Determine which delivery territory a location belongs to
        
        Returns:
            DeliveryTerritory or None
        """
        profile = self.get_profile(trucker_id)
        
        if not profile or not profile.delivery_territories:
            return None
        
        # Find closest territory
        for territory in profile.delivery_territories:
            distance_km = haversine_distance(
                territory.center_lat, territory.center_lon, lat, lon
            ) / 1000
            
            if distance_km <= territory.radius_km:
                return territory
        
        return None
    
    def predict_next_destination(self, 
                                trucker_id: str, 
                                current_location_poi_id: str,
                                time_of_day: str) -> List[Tuple[str, float]]:
        """
        Predict likely next destinations based on patterns
        
        Returns:
            List of (poi_id, probability) tuples
        """
        profile = self.get_profile(trucker_id)
        
        if not profile:
            return []
        
        predictions = []
        
        # Check recurring route patterns
        for route in profile.recurring_routes:
            if route.origin_poi_id == current_location_poi_id:
                # Calculate probability based on frequency
                probability = route.frequency / profile.total_trips
                predictions.append((route.destination_poi_id, probability))
        
        # Sort by probability
        predictions.sort(key=lambda x: x[1], reverse=True)
        
        return predictions[:5]  # Top 5 predictions
    
    def compare_truckers(self, trucker_id_1: str, trucker_id_2: str) -> Dict:
        """
        Compare two trucker profiles
        Useful for understanding driver differences
        """
        profile1 = self.get_profile(trucker_id_1)
        profile2 = self.get_profile(trucker_id_2)
        
        if not profile1 or not profile2:
            return {'error': 'One or both profiles not found'}
        
        comparison = {
            'trucker_1': trucker_id_1,
            'trucker_2': trucker_id_2,
            'haul_types': {
                'trucker_1': profile1.haul_type,
                'trucker_2': profile2.haul_type
            },
            'avg_trip_distance_km': {
                'trucker_1': round(profile1.avg_trip_distance_km, 1),
                'trucker_2': round(profile2.avg_trip_distance_km, 1),
                'difference': round(profile1.avg_trip_distance_km - profile2.avg_trip_distance_km, 1)
            },
            'avg_shift_duration_hours': {
                'trucker_1': round(profile1.avg_shift_duration_hours, 1),
                'trucker_2': round(profile2.avg_shift_duration_hours, 1),
                'difference': round(profile1.avg_shift_duration_hours - profile2.avg_shift_duration_hours, 1)
            },
            'territories': {
                'trucker_1': len(profile1.delivery_territories),
                'trucker_2': len(profile2.delivery_territories)
            },
            'recurring_routes': {
                'trucker_1': len(profile1.recurring_routes),
                'trucker_2': len(profile2.recurring_routes)
            },
            'share_same_depot': False
        }
        
        # Check if they share the same depot
        if profile1.primary_depot and profile2.primary_depot:
            comparison['share_same_depot'] = (
                profile1.primary_depot.poi_id == profile2.primary_depot.poi_id
            )
        
        return comparison


# Example usage and testing
if __name__ == "__main__":
    print("="*60)
    print("TRUCKER PROFILE MANAGER - TEST")
    print("="*60)
    
    # Create manager
    manager = TruckerProfileManager(storage_dir="./trucker_profiles")
    
    # Example trips for SHORT-HAUL trucker (UPS driver)
    short_haul_trips = [
        {
            'trip_id': 'trip_001',
            'trucker_id': 'driver_ups_001',
            'vehicle_id': 'truck_123',
            'start_time': '2025-01-06T08:00:00',
            'end_time': '2025-01-06T08:15:00',
            'duration_seconds': 900,
            'distance_meters': 5000,
            'origin_poi': {
                'uri': 'depot_ups_walnut_creek',
                'name': 'UPS Distribution Center',
                'type': 'uko:DistributionCenter',
                'coordinates': {'latitude': 37.9101, 'longitude': -122.0652}
            },
            'destination_poi': {
                'uri': 'customer_001',
                'name': 'Residential Address',
                'type': 'uko:ResidentialBuilding',
                'coordinates': {'latitude': 37.9150, 'longitude': -122.0600}
            },
            'dwell_time': 300,  # 5 minutes
            'modality': 'driving'
        },
        {
            'trip_id': 'trip_002',
            'trucker_id': 'driver_ups_001',
            'vehicle_id': 'truck_123',
            'start_time': '2025-01-06T08:20:00',
            'end_time': '2025-01-06T08:35:00',
            'duration_seconds': 900,
            'distance_meters': 8000,
            'origin_poi': {
                'uri': 'customer_001',
                'name': 'Residential Address',
                'type': 'uko:ResidentialBuilding',
                'coordinates': {'latitude': 37.9150, 'longitude': -122.0600}
            },
            'destination_poi': {
                'uri': 'customer_002',
                'name': 'Office Building',
                'type': 'uko:OfficeBuilding',
                'coordinates': {'latitude': 37.9200, 'longitude': -122.0550}
            },
            'dwell_time': 240,
            'modality': 'driving'
        }
    ]
    
    # Example trips for LONG-HAUL trucker (Schneider driver)
    long_haul_trips = [
        {
            'trip_id': 'trip_101',
            'trucker_id': 'driver_schneider_001',
            'vehicle_id': 'truck_456',
            'start_time': '2025-01-06T06:00:00',
            'end_time': '2025-01-06T12:30:00',
            'duration_seconds': 23400,
            'distance_meters': 450000,  # 450km
            'origin_poi': {
                'uri': 'depot_phoenix',
                'name': 'Phoenix Distribution Center',
                'type': 'uko:DistributionCenter',
                'coordinates': {'latitude': 33.4484, 'longitude': -112.0740}
            },
            'destination_poi': {
                'uri': 'depot_dallas',
                'name': 'Dallas Distribution Center',
                'type': 'uko:DistributionCenter',
                'coordinates': {'latitude': 32.7767, 'longitude': -96.7970}
            },
            'dwell_time': 3600,  # 1 hour loading/unloading
            'modality': 'driving'
        }
    ]
    
    print("\n" + "-"*60)
    print("TESTING SHORT-HAUL PROFILE (UPS Driver)")
    print("-"*60)
    
    # Build short-haul profile
    short_profile = manager.build_profile('driver_ups_001', short_haul_trips)
    short_summary = manager.get_profile_summary('driver_ups_001')
    
    print("\nProfile Summary:")
    print(json.dumps(short_summary, indent=2))
    print(f"\nHaul Type: {manager.get_haul_type_description(short_profile.haul_type)}")
    
    print("\n" + "-"*60)
    print("TESTING LONG-HAUL PROFILE (Schneider Driver)")
    print("-"*60)
    
    # Build long-haul profile
    long_profile = manager.build_profile('driver_schneider_001', long_haul_trips)
    long_summary = manager.get_profile_summary('driver_schneider_001')
    
    print("\nProfile Summary:")
    print(json.dumps(long_summary, indent=2))
    print(f"\nHaul Type: {manager.get_haul_type_description(long_profile.haul_type)}")
    
    print("\n" + "="*60)
    print("DEPOT DETECTION TEST")
    print("="*60)
    
    # Test depot detection
    is_depot, confidence = manager.is_depot_delivery(
        'driver_ups_001',
        'depot_ups_walnut_creek'
    )
    print(f"\nIs 'UPS Distribution Center' a depot for driver_ups_001?")
    print(f"  Result: {is_depot}")
    print(f"  Confidence: {confidence:.2%}")
    
    print("\n" + "="*60)