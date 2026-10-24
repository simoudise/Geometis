"""
Traveler Profile Manager
Builds and maintains behavioral profiles for travelers
Critical for employee/user disambiguation in consumer trips
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, asdict
import numpy as np
from math import radians, sin, cos, sqrt, atan2


@dataclass
class WorkplaceCandidate:
    """Candidate workplace for a traveler"""
    poi_id: str
    poi_name: str
    poi_type: str
    coordinates: Tuple[float, float]
    visit_count: int
    avg_arrival_time: str  # HH:MM format
    arrival_std_minutes: float
    avg_departure_time: str
    departure_std_minutes: float
    avg_dwell_hours: float
    weekday_visits: int
    weekend_visits: int
    confidence: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TravelerProfile:
    """
    Behavioral profile for a traveler
    Used for employee/user disambiguation and intent prediction
    """
    traveler_id: str
    profile_start_date: str
    profile_end_date: str
    days_tracked: int
    total_trips: int
    
    # Identified locations
    home_location: Optional[Dict] = None  # {coords, confidence}
    workplace_candidates: List[WorkplaceCandidate] = None
    
    # Visit patterns
    regular_destinations: Dict[str, Dict] = None  # poi_id -> {visits, avg_dwell, temporal_pattern}
    
    # Temporal patterns
    typical_commute_times: Dict[str, List[str]] = None  # 'morning', 'evening' -> [times]
    
    # Modality preferences
    modality_distribution: Dict[str, int] = None
    
    # Metadata
    last_updated: str = None
    profile_maturity: str = None  # 'cold_start', 'warming', 'mature'
    
    def __post_init__(self):
        if self.workplace_candidates is None:
            self.workplace_candidates = []
        if self.regular_destinations is None:
            self.regular_destinations = {}
        if self.typical_commute_times is None:
            self.typical_commute_times = {'morning': [], 'evening': []}
        if self.modality_distribution is None:
            self.modality_distribution = {}
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
        # Convert WorkplaceCandidate objects to dicts
        data['workplace_candidates'] = [wc.to_dict() for wc in self.workplace_candidates]
        return data


class TravelerProfileManager:
    """
    Manages traveler profiles for disambiguation and pattern analysis
    Supports both persistent storage and in-memory operation
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize profile manager
        
        Args:
            storage_dir: Directory for persistent profile storage (optional)
        """
        self.storage_dir = storage_dir
        self.profiles = {}  # In-memory cache
        
        # Parameters for workplace detection
        self.min_visits_for_workplace = 4  # Minimum visits per week
        self.max_arrival_std = 30  # Max arrival time std deviation (minutes)
        self.min_dwell_time = 4 * 3600  # Minimum dwell time (4 hours)
        self.weekday_ratio_threshold = 0.7  # 70%+ visits on weekdays
        
        if storage_dir and not os.path.exists(storage_dir):
            os.makedirs(storage_dir)
    
    def get_profile(self, traveler_id: str) -> Optional[TravelerProfile]:
        """Get profile for a traveler"""
        # Check memory cache
        if traveler_id in self.profiles:
            return self.profiles[traveler_id]
        
        # Try to load from disk
        if self.storage_dir:
            profile = self._load_profile(traveler_id)
            if profile:
                self.profiles[traveler_id] = profile
                return profile
        
        return None
    
    def build_profile(self, traveler_id: str, trips: List[Dict]) -> TravelerProfile:
        """
        Build a profile from trip history
        
        Args:
            traveler_id: Traveler identifier
            trips: List of enhanced trips with POI data
            
        Returns:
            TravelerProfile object
        """
        if not trips:
            return TravelerProfile(
                traveler_id=traveler_id,
                profile_start_date=datetime.now().isoformat(),
                profile_end_date=datetime.now().isoformat(),
                days_tracked=0,
                total_trips=0
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
        
        # Initialize profile
        profile = TravelerProfile(
            traveler_id=traveler_id,
            profile_start_date=start_date.isoformat(),
            profile_end_date=end_date.isoformat(),
            days_tracked=days_tracked,
            total_trips=len(trips)
        )
        
        # Analyze trips
        self._analyze_destinations(profile, trips)
        self._detect_home(profile, trips)
        self._detect_workplaces(profile, trips)
        self._analyze_temporal_patterns(profile, trips)
        self._analyze_modality_preferences(profile, trips)
        
        # Cache profile
        self.profiles[traveler_id] = profile
        
        # Save to disk if storage enabled
        if self.storage_dir:
            self._save_profile(profile)
        
        return profile
    
    def update_profile(self, traveler_id: str, new_trips: List[Dict]) -> TravelerProfile:
        """Update existing profile with new trips"""
        # Get existing profile or create new
        profile = self.get_profile(traveler_id)
        
        if profile:
            # Merge new trips with existing data
            # For now, rebuild from scratch - optimization possible
            all_trips = self._get_all_trips_for_profile(traveler_id) + new_trips
            return self.build_profile(traveler_id, all_trips)
        else:
            return self.build_profile(traveler_id, new_trips)
    
    def _analyze_destinations(self, profile: TravelerProfile, trips: List[Dict]):
        """Analyze frequently visited destinations"""
        destination_visits = defaultdict(lambda: {
            'visits': 0,
            'dwell_times': [],
            'visit_times': [],
            'weekday_visits': 0,
            'weekend_visits': 0
        })
        
        for trip in trips:
            dest_poi = trip.get('destination_poi')
            if not dest_poi or not dest_poi.get('uri'):
                continue
            
            poi_id = dest_poi['uri']
            dwell_time = trip.get('dwell_time', 0)
            start_time = trip.get('start_time')
            
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            
            dest_visits = destination_visits[poi_id]
            dest_visits['visits'] += 1
            dest_visits['dwell_times'].append(dwell_time)
            dest_visits['visit_times'].append(start_time)
            
            if start_time.weekday() < 5:
                dest_visits['weekday_visits'] += 1
            else:
                dest_visits['weekend_visits'] += 1
            
            # Store POI metadata
            if 'poi_data' not in dest_visits:
                dest_visits['poi_data'] = dest_poi
        
        # Convert to profile format
        for poi_id, data in destination_visits.items():
            if data['visits'] >= 2:  # At least 2 visits
                profile.regular_destinations[poi_id] = {
                    'visits': data['visits'],
                    'avg_dwell_minutes': np.mean(data['dwell_times']) / 60 if data['dwell_times'] else 0,
                    'weekday_ratio': data['weekday_visits'] / data['visits'],
                    'poi_name': data['poi_data'].get('name', 'Unknown'),
                    'poi_type': data['poi_data'].get('type', 'Unknown')
                }
    
    def _detect_home(self, profile: TravelerProfile, trips: List[Dict]):
        """
        Detect home location
        Home is typically where trips originate in early morning and end in evening
        """
        origin_locations = defaultdict(lambda: {
            'count': 0,
            'early_morning': 0,  # 5am-7am
            'late_evening': 0,   # 8pm-midnight
            'coordinates': None
        })
        
        for trip in trips:
            start_time = trip.get('start_time')
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            
            hour = start_time.hour
            
            # Check origin for early morning trips
            origin_poi = trip.get('origin_poi')
            if origin_poi and origin_poi.get('uri'):
                poi_id = origin_poi['uri']
                origin_locations[poi_id]['count'] += 1
                origin_locations[poi_id]['coordinates'] = origin_poi.get('coordinates')
                
                if 5 <= hour < 7:
                    origin_locations[poi_id]['early_morning'] += 1
            
            # Check destination for late evening trips
            dest_poi = trip.get('destination_poi')
            if dest_poi and dest_poi.get('uri'):
                poi_id = dest_poi['uri']
                if poi_id not in origin_locations:
                    origin_locations[poi_id]['count'] = 0
                    origin_locations[poi_id]['coordinates'] = dest_poi.get('coordinates')
                
                if 20 <= hour < 24:
                    origin_locations[poi_id]['late_evening'] += 1
        
        # Find best home candidate
        best_home = None
        best_score = 0
        
        for poi_id, data in origin_locations.items():
            # Score based on early morning origins and late evening destinations
            score = data['early_morning'] * 2 + data['late_evening']
            
            if score > best_score and data['count'] >= 3:
                best_score = score
                best_home = {
                    'poi_id': poi_id,
                    'coordinates': data['coordinates'],
                    'confidence': min(score / (profile.total_trips * 0.5), 1.0)
                }
        
        if best_home and best_home['confidence'] > 0.3:
            profile.home_location = best_home
    
    def _detect_workplaces(self, profile: TravelerProfile, trips: List[Dict]):
        """
        Detect workplace(s)
        Workplace characteristics:
        - Regular visits (4+ times per week)
        - Consistent arrival time (within 30 min window)
        - Long dwell time (4+ hours)
        - Primarily weekdays (70%+ of visits)
        """
        destination_patterns = defaultdict(lambda: {
            'visits': 0,
            'arrival_times': [],
            'departure_times': [],
            'dwell_times': [],
            'weekday_visits': 0,
            'weekend_visits': 0,
            'poi_data': None,
            'direct_from_home': 0
        })
        
        for trip in trips:
            dest_poi = trip.get('destination_poi')
            if not dest_poi or not dest_poi.get('uri'):
                continue
            
            poi_id = dest_poi['uri']
            start_time = trip.get('start_time')
            end_time = trip.get('end_time')
            dwell_time = trip.get('dwell_time', 0)
            
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            if isinstance(end_time, str):
                end_time = datetime.fromisoformat(end_time)
            
            pattern = destination_patterns[poi_id]
            pattern['visits'] += 1
            pattern['arrival_times'].append(start_time)
            pattern['departure_times'].append(end_time)
            pattern['dwell_times'].append(dwell_time)
            pattern['poi_data'] = dest_poi
            
            if start_time.weekday() < 5:
                pattern['weekday_visits'] += 1
            else:
                pattern['weekend_visits'] += 1
            
            # Check if trip originated from home
            origin_poi = trip.get('origin_poi')
            if (profile.home_location and origin_poi and 
                origin_poi.get('uri') == profile.home_location.get('poi_id')):
                pattern['direct_from_home'] += 1
        
        # Evaluate workplace candidates
        weeks_tracked = max(profile.days_tracked / 7, 1)
        
        for poi_id, pattern in destination_patterns.items():
            visits_per_week = pattern['visits'] / weeks_tracked
            
            # Must have minimum visits per week
            if visits_per_week < self.min_visits_for_workplace:
                continue
            
            # Calculate arrival time consistency
            if len(pattern['arrival_times']) < 2:
                continue
            
            arrival_minutes = [(t.hour * 60 + t.minute) for t in pattern['arrival_times']]
            arrival_std = np.std(arrival_minutes)
            
            # Calculate departure time consistency
            departure_minutes = [(t.hour * 60 + t.minute) for t in pattern['departure_times']]
            departure_std = np.std(departure_minutes)
            
            # Average dwell time
            avg_dwell = np.mean(pattern['dwell_times'])
            
            # Weekday ratio
            weekday_ratio = pattern['weekday_visits'] / pattern['visits']
            
            # Check workplace criteria
            if (arrival_std <= self.max_arrival_std and
                avg_dwell >= self.min_dwell_time and
                weekday_ratio >= self.weekday_ratio_threshold):
                
                # Calculate confidence
                confidence = self._calculate_workplace_confidence(
                    visits_per_week,
                    arrival_std,
                    avg_dwell,
                    weekday_ratio,
                    pattern['direct_from_home'] / pattern['visits']
                )
                
                # Format times
                avg_arrival = self._minutes_to_time(np.mean(arrival_minutes))
                avg_departure = self._minutes_to_time(np.mean(departure_minutes))
                
                poi_data = pattern['poi_data']
                coords = poi_data.get('coordinates', {})
                
                workplace = WorkplaceCandidate(
                    poi_id=poi_id,
                    poi_name=poi_data.get('name', 'Unknown'),
                    poi_type=poi_data.get('type', 'Unknown'),
                    coordinates=(coords.get('latitude'), coords.get('longitude')) if coords else (None, None),
                    visit_count=pattern['visits'],
                    avg_arrival_time=avg_arrival,
                    arrival_std_minutes=arrival_std,
                    avg_departure_time=avg_departure,
                    departure_std_minutes=departure_std,
                    avg_dwell_hours=avg_dwell / 3600,
                    weekday_visits=pattern['weekday_visits'],
                    weekend_visits=pattern['weekend_visits'],
                    confidence=confidence
                )
                
                profile.workplace_candidates.append(workplace)
        
        # Sort by confidence
        profile.workplace_candidates.sort(key=lambda w: w.confidence, reverse=True)
    
    def _calculate_workplace_confidence(self,
                                       visits_per_week: float,
                                       arrival_std: float,
                                       avg_dwell: float,
                                       weekday_ratio: float,
                                       from_home_ratio: float) -> float:
        """Calculate confidence that a location is a workplace"""
        # Start with base confidence
        confidence = 0.0
        
        # Visit frequency (0-0.30)
        confidence += min(visits_per_week / 5, 1.0) * 0.30
        
        # Arrival consistency (0-0.25)
        confidence += max(0, (1 - arrival_std / 60)) * 0.25
        
        # Dwell time (0-0.20)
        target_dwell = 8 * 3600  # 8 hours
        confidence += min(avg_dwell / target_dwell, 1.0) * 0.20
        
        # Weekday pattern (0-0.15)
        confidence += weekday_ratio * 0.15
        
        # Direct from home (0-0.10)
        confidence += from_home_ratio * 0.10
        
        return min(confidence, 1.0)
    
    def _analyze_temporal_patterns(self, profile: TravelerProfile, trips: List[Dict]):
        """Analyze typical travel times"""
        morning_times = []
        evening_times = []
        
        for trip in trips:
            start_time = trip.get('start_time')
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            
            hour = start_time.hour
            time_str = start_time.strftime('%H:%M')
            
            if 5 <= hour < 10:
                morning_times.append(time_str)
            elif 15 <= hour < 20:
                evening_times.append(time_str)
        
        profile.typical_commute_times = {
            'morning': morning_times,
            'evening': evening_times
        }
    
    def _analyze_modality_preferences(self, profile: TravelerProfile, trips: List[Dict]):
        """Analyze modality usage patterns"""
        modality_counts = defaultdict(int)
        
        for trip in trips:
            modality = trip.get('modality', 'unknown')
            modality_counts[modality] += 1
        
        profile.modality_distribution = dict(modality_counts)
    
    def _minutes_to_time(self, minutes: float) -> str:
        """Convert minutes since midnight to HH:MM format"""
        hours = int(minutes // 60)
        mins = int(minutes % 60)
        return f"{hours:02d}:{mins:02d}"
    
    def _save_profile(self, profile: TravelerProfile):
        """Save profile to disk"""
        if not self.storage_dir:
            return
        
        filepath = os.path.join(self.storage_dir, f"{profile.traveler_id}.json")
        
        with open(filepath, 'w') as f:
            json.dump(profile.to_dict(), f, indent=2)
    
    def _load_profile(self, traveler_id: str) -> Optional[TravelerProfile]:
        """Load profile from disk"""
        if not self.storage_dir:
            return None
        
        filepath = os.path.join(self.storage_dir, f"{traveler_id}.json")
        
        if not os.path.exists(filepath):
            return None
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Convert workplace candidates back to objects
            if 'workplace_candidates' in data:
                data['workplace_candidates'] = [
                    WorkplaceCandidate(**wc) for wc in data['workplace_candidates']
                ]
            
            return TravelerProfile(**data)
        except Exception as e:
            print(f"Error loading profile for {traveler_id}: {e}")
            return None
    
    def _get_all_trips_for_profile(self, traveler_id: str) -> List[Dict]:
        """
        Get all historical trips for a traveler
        In production, this would query a database
        For now, returns empty list (rebuild from scratch)
        """
        # TODO: Implement trip history retrieval
        return []
    
    def is_employee_at_location(self,
                               traveler_id: str,
                               poi_id: str,
                               confidence_threshold: float = 0.70) -> Tuple[bool, float]:
        """
        Check if traveler is likely an employee at a given location
        
        Returns:
            (is_employee, confidence)
        """
        profile = self.get_profile(traveler_id)
        
        if not profile:
            return False, 0.0
        
        # Check workplace candidates
        for workplace in profile.workplace_candidates:
            if workplace.poi_id == poi_id:
                return workplace.confidence >= confidence_threshold, workplace.confidence
        
        return False, 0.0
    
    def get_profile_summary(self, traveler_id: str) -> Optional[Dict]:
        """Get human-readable profile summary"""
        profile = self.get_profile(traveler_id)
        
        if not profile:
            return None
        
        summary = {
            'traveler_id': traveler_id,
            'profile_maturity': profile.profile_maturity,
            'days_tracked': profile.days_tracked,
            'total_trips': profile.total_trips,
            'home_identified': profile.home_location is not None,
            'workplaces_identified': len(profile.workplace_candidates),
            'regular_destinations': len(profile.regular_destinations),
            'primary_modality': max(profile.modality_distribution.items(), 
                                   key=lambda x: x[1])[0] if profile.modality_distribution else None
        }
        
        if profile.workplace_candidates:
            summary['primary_workplace'] = {
                'name': profile.workplace_candidates[0].poi_name,
                'confidence': round(profile.workplace_candidates[0].confidence, 2),
                'visits_per_week': round(profile.workplace_candidates[0].visit_count / max(profile.days_tracked / 7, 1), 1)
            }
        
        return summary


# Example usage
if __name__ == "__main__":
    print("="*60)
    print("TRAVELER PROFILE MANAGER - TEST")
    print("="*60)
    
    # Create manager
    manager = TravelerProfileManager(storage_dir="./test_profiles")
    
    # Example trips for testing
    test_trips = [
        {
            'trip_id': 'trip_001',
            'start_time': '2025-01-06T08:15:00',
            'end_time': '2025-01-06T08:45:00',
            'origin_poi': {
                'uri': 'home_poi_1',
                'name': 'Home',
                'type': 'ResidentialBuilding',
                'coordinates': {'latitude': 37.9, 'longitude': -122.0}
            },
            'destination_poi': {
                'uri': 'work_poi_1',
                'name': 'Tech Campus',
                'type': 'OfficeBuilding',
                'coordinates': {'latitude': 37.91, 'longitude': -122.06}
            },
            'dwell_time': 28800,  # 8 hours
            'modality': 'driving'
        },
        # Add more trips...
    ]
    
    # Build profile
    profile = manager.build_profile('test_traveler_001', test_trips)
    
    # Get summary
    summary = manager.get_profile_summary('test_traveler_001')
    print("\nProfile Summary:")
    print(json.dumps(summary, indent=2))
    
    # Check employee status
    is_employee, confidence = manager.is_employee_at_location(
        'test_traveler_001',
        'work_poi_1'
    )
    print(f"\nIs employee at Tech Campus: {is_employee} (confidence: {confidence:.2%})")
    
    print("\n" + "="*60)