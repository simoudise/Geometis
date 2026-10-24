"""
Enhanced Modality Predictor
Predicts transportation modality and segments trips by modality changes
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
from datetime import datetime, timedelta
from scipy.signal import find_peaks
import warnings

@dataclass
class Segment:
    """Raw segment from base trip data"""
    segment_id: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    start_time: datetime
    end_time: datetime
    distance_meters: float = None
    modality: Optional[str] = None  # If provided by source
    
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()
    
    def speed_ms(self) -> float:
        """Calculate speed in m/s"""
        duration = self.duration_seconds()
        if duration > 0 and self.distance_meters:
            return self.distance_meters / duration
        return 0.0

@dataclass
class ModalitySegment:
    """Trip segment with unified modality"""
    segment_id: str
    modality: str
    confidence: float
    start_time: datetime
    end_time: datetime
    raw_segments: List[Segment]  # Original micro-segments
    road_segments: List[Dict] = None  # Will be filled after OSRM processing
    
    def total_distance(self) -> float:
        if self.road_segments:
            return sum(rs['distance_meters'] for rs in self.road_segments)
        return sum(s.distance_meters or 0 for s in self.raw_segments)


class ModalityPredictor:
    """
    Predicts transportation modality from raw GPS segments
    Handles all modality types and segments trips by modality changes
    """
    
    # Modality definitions with characteristic signatures
    MODALITY_PROFILES = {
        'walking': {
            'speed_range': (0.5, 2.5),
            'typical_speed': 1.4,
            'speed_variance_max': 0.5,
            'stop_frequency_range': (0, 0.3),
            'osrm_profile': 'foot',
            'category': 'active_mobility'
        },
        'bicycling': {
            'speed_range': (3.0, 8.5),
            'typical_speed': 5.5,
            'speed_variance_max': 1.2,
            'stop_frequency_range': (0, 0.2),
            'osrm_profile': 'bicycle',
            'category': 'micromobility'
        },
        'scootering': {
            'speed_range': (3.5, 7.0),
            'typical_speed': 5.0,
            'speed_variance_max': 0.8,
            'stop_frequency_range': (0, 0.2),
            'osrm_profile': 'bicycle',
            'category': 'micromobility'
        },
        'bus': {
            'speed_range': (3.0, 15.0),
            'typical_speed': 8.0,
            'speed_variance_max': 3.0,
            'stop_frequency_range': (0.4, 1.0),  # Key: frequent stops
            'osrm_profile': 'car',
            'category': 'public_transit'
        },
        'light_rail': {
            'speed_range': (8.0, 20.0),
            'typical_speed': 14.0,
            'speed_variance_max': 2.5,
            'stop_frequency_range': (0.3, 0.7),
            'osrm_profile': 'car',
            'category': 'public_transit'
        },
        'train': {
            'speed_range': (10.0, 35.0),
            'typical_speed': 22.0,
            'speed_variance_max': 4.0,
            'stop_frequency_range': (0.1, 0.4),
            'osrm_profile': 'car',
            'category': 'public_transit'
        },
        'subway': {
            'speed_range': (10.0, 25.0),
            'typical_speed': 17.0,
            'speed_variance_max': 3.0,
            'stop_frequency_range': (0.3, 0.6),
            'osrm_profile': 'car',
            'category': 'public_transit'
        },
        'private_vehicle': {
            'speed_range': (5.0, 35.0),
            'typical_speed': 15.0,
            'speed_variance_max': 5.0,
            'stop_frequency_range': (0, 0.3),
            'osrm_profile': 'car',
            'category': 'private'
        },
        'ridehailing': {
            'speed_range': (5.0, 35.0),
            'typical_speed': 15.0,
            'speed_variance_max': 5.0,
            'stop_frequency_range': (0, 0.3),
            'osrm_profile': 'car',
            'category': 'commercial'
        }
    }
    
    def __init__(self):
        self.speed_threshold_stopped = 0.5  # m/s
        self.min_stop_duration = 10  # seconds
        
    def predict_trip_modalities(self, segments: List[Segment]) -> List[ModalitySegment]:
        """
        Main entry point: segments entire trip by modality changes
        
        Args:
            segments: Raw GPS segments from base trip
            
        Returns:
            List of ModalitySegments, each with unified modality
        """
        # Step 1: If modalities are provided, use them
        if segments[0].modality is not None:
            return self._segment_by_provided_modality(segments)
        
        # Step 2: Detect modality change points
        change_points = self._detect_modality_changes(segments)
        
        # Step 3: Create modality segments
        modality_segments = []
        for i in range(len(change_points) - 1):
            start_idx = change_points[i]
            end_idx = change_points[i + 1]
            segment_group = segments[start_idx:end_idx]
            
            # Predict modality for this group
            modality_result = self._predict_modality_for_segment_group(segment_group)
            
            modality_seg = ModalitySegment(
                segment_id=f"MODAL_SEG_{i+1:03d}",
                modality=modality_result['modality'],
                confidence=modality_result['confidence'],
                start_time=segment_group[0].start_time,
                end_time=segment_group[-1].end_time,
                raw_segments=segment_group
            )
            modality_segments.append(modality_seg)
        
        return modality_segments
    
    def _segment_by_provided_modality(self, segments: List[Segment]) -> List[ModalitySegment]:
        """Handle case where modality is already provided in source data"""
        modality_segments = []
        current_modality = segments[0].modality
        current_group = [segments[0]]
        
        for seg in segments[1:]:
            if seg.modality == current_modality:
                current_group.append(seg)
            else:
                # Modality changed - create segment
                modality_segments.append(ModalitySegment(
                    segment_id=f"MODAL_SEG_{len(modality_segments)+1:03d}",
                    modality=current_modality,
                    confidence=1.0,  # Provided by source
                    start_time=current_group[0].start_time,
                    end_time=current_group[-1].end_time,
                    raw_segments=current_group
                ))
                current_modality = seg.modality
                current_group = [seg]
        
        # Add final segment
        if current_group:
            modality_segments.append(ModalitySegment(
                segment_id=f"MODAL_SEG_{len(modality_segments)+1:03d}",
                modality=current_modality,
                confidence=1.0,
                start_time=current_group[0].start_time,
                end_time=current_group[-1].end_time,
                raw_segments=current_group
            ))
        
        return modality_segments
    
    def _detect_modality_changes(self, segments: List[Segment]) -> List[int]:
        """
        Detect points where modality likely changed
        Uses speed changes, stop patterns, and trajectory changes
        
        Returns:
            List of segment indices where modality changes occur
        """
        if len(segments) < 3:
            return [0, len(segments)]
        
        # Calculate features for each segment
        speeds = np.array([seg.speed_ms() for seg in segments])
        
        # Smooth speeds to reduce noise
        window_size = min(5, len(speeds) // 2)
        if window_size >= 3:
            speeds_smoothed = np.convolve(speeds, np.ones(window_size)/window_size, mode='same')
        else:
            speeds_smoothed = speeds
        
        # Detect significant speed changes (potential modality changes)
        speed_gradient = np.gradient(speeds_smoothed)
        speed_changes = np.abs(speed_gradient)
        
        # Find peaks in speed changes
        change_threshold = np.percentile(speed_changes, 80)
        peaks, _ = find_peaks(speed_changes, height=change_threshold, distance=10)
        
        # Detect long stops (>5 min) which often indicate modality changes
        long_stops = []
        for i, seg in enumerate(segments):
            if seg.speed_ms() < self.speed_threshold_stopped:
                if i > 0 and segments[i-1].speed_ms() < self.speed_threshold_stopped:
                    continue  # Part of same stop
                # Check duration of stop
                stop_duration = 0
                j = i
                while j < len(segments) and segments[j].speed_ms() < self.speed_threshold_stopped:
                    stop_duration += segments[j].duration_seconds()
                    j += 1
                if stop_duration > 300:  # 5 minutes
                    long_stops.append(i)
        
        # Combine change points
        change_points = sorted(set([0] + list(peaks) + long_stops + [len(segments)]))
        
        return change_points
    
    def _predict_modality_for_segment_group(self, segments: List[Segment]) -> Dict:
        """
        Predict modality for a group of segments (single modality)
        
        Returns:
            Dict with 'modality', 'confidence', 'method', 'features'
        """
        features = self._extract_features(segments)
        
        # Try rule-based classification first
        rule_result = self._apply_rules(features)
        if rule_result['confidence'] > 0.80:
            return rule_result
        
        # Fall back to profile matching
        profile_result = self._match_to_profile(features)
        return profile_result
    
    def _extract_features(self, segments: List[Segment]) -> Dict:
        """Extract comprehensive features from segment group"""
        
        speeds = [seg.speed_ms() for seg in segments]
        speeds_array = np.array(speeds)
        
        # Stop analysis
        stops = self._analyze_stops(segments)
        
        # GPS signal quality
        gps_gaps = self._detect_gps_gaps(segments)
        
        # Trajectory analysis
        trajectory = self._analyze_trajectory(segments)
        
        total_distance = sum(seg.distance_meters or 0 for seg in segments)
        total_duration = sum(seg.duration_seconds() for seg in segments)
        
        return {
            'avg_speed': np.mean(speeds_array),
            'max_speed': np.max(speeds_array),
            'speed_variance': np.var(speeds_array),
            'speed_percentiles': np.percentile(speeds_array, [25, 50, 75, 95]).tolist(),
            'stop_count': stops['count'],
            'stop_frequency': stops['frequency'],  # stops per km
            'stop_regularity': stops['regularity'],
            'avg_stop_duration': stops['avg_duration'],
            'trajectory_smoothness': trajectory['smoothness'],
            'direction_changes': trajectory['direction_changes'],
            'gps_signal_gaps': gps_gaps['gap_count'],
            'max_gps_gap': gps_gaps['max_gap'],
            'suggests_tunnel': gps_gaps['suggests_tunnel'],
            'total_distance': total_distance,
            'total_duration': total_duration,
            'has_parking_behavior': self._detect_parking(segments)
        }
    
    def _analyze_stops(self, segments: List[Segment]) -> Dict:
        """Analyze stop patterns - critical for transit detection"""
        
        stops = []
        in_stop = False
        stop_start_idx = None
        stop_start_time = None
        
        for i, seg in enumerate(segments):
            if seg.speed_ms() < self.speed_threshold_stopped:
                if not in_stop:
                    in_stop = True
                    stop_start_idx = i
                    stop_start_time = seg.start_time
            else:
                if in_stop:
                    stop_duration = (seg.start_time - stop_start_time).total_seconds()
                    if stop_duration >= self.min_stop_duration:
                        stops.append({
                            'index': stop_start_idx,
                            'duration': stop_duration,
                            'location': (segments[stop_start_idx].start_lat, 
                                       segments[stop_start_idx].start_lon)
                        })
                    in_stop = False
        
        # Calculate stop regularity
        regularity = 'unknown'
        if len(stops) >= 3:
            distances_between_stops = []
            for i in range(len(stops) - 1):
                dist = self._haversine(
                    stops[i]['location'],
                    stops[i+1]['location']
                )
                distances_between_stops.append(dist)
            
            if distances_between_stops:
                cv = np.std(distances_between_stops) / np.mean(distances_between_stops)
                if cv < 0.3:
                    regularity = 'very_regular'
                elif cv < 0.6:
                    regularity = 'somewhat_regular'
                else:
                    regularity = 'irregular'
        
        total_distance = sum(seg.distance_meters or 0 for seg in segments) / 1000  # km
        frequency = len(stops) / total_distance if total_distance > 0 else 0
        avg_duration = np.mean([s['duration'] for s in stops]) if stops else 0
        
        return {
            'count': len(stops),
            'frequency': frequency,
            'regularity': regularity,
            'avg_duration': avg_duration,
            'stops': stops
        }
    
    def _detect_gps_gaps(self, segments: List[Segment], gap_threshold: int = 60) -> Dict:
        """Detect GPS signal gaps (indicates subway/tunnel)"""
        
        gaps = []
        for i in range(len(segments) - 1):
            time_gap = (segments[i+1].start_time - segments[i].end_time).total_seconds()
            if time_gap > gap_threshold:
                gaps.append(time_gap)
        
        max_gap = max(gaps) if gaps else 0
        suggests_tunnel = max_gap > 120  # >2 min gap suggests tunnel/subway
        
        return {
            'gap_count': len(gaps),
            'max_gap': max_gap,
            'total_gap_duration': sum(gaps),
            'suggests_tunnel': suggests_tunnel
        }
    
    def _analyze_trajectory(self, segments: List[Segment]) -> Dict:
        """Analyze trajectory characteristics"""
        
        if len(segments) < 3:
            return {'smoothness': 0.5, 'direction_changes': 0}
        
        # Calculate bearing changes
        bearings = []
        for i in range(len(segments) - 1):
            bearing = self._calculate_bearing(
                segments[i].start_lat, segments[i].start_lon,
                segments[i+1].start_lat, segments[i+1].start_lon
            )
            bearings.append(bearing)
        
        # Count significant direction changes (>45 degrees)
        direction_changes = 0
        for i in range(len(bearings) - 1):
            angle_diff = abs(bearings[i+1] - bearings[i])
            # Normalize to 0-180
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            if angle_diff > 45:
                direction_changes += 1
        
        # Smoothness: inverse of variance in bearings
        bearing_variance = np.var(bearings) if bearings else 0
        smoothness = 1 / (1 + bearing_variance / 100)  # Normalize
        
        return {
            'smoothness': smoothness,
            'direction_changes': direction_changes
        }
    
    def _detect_parking(self, segments: List[Segment]) -> bool:
        """Detect if segment ends with parking behavior"""
        
        if len(segments) < 5:
            return False
        
        final_segments = segments[-5:]
        speeds = [seg.speed_ms() for seg in final_segments]
        
        # Parking: very low speeds with direction changes
        slow_speed = all(s < 2.0 for s in speeds)
        trajectory = self._analyze_trajectory(final_segments)
        
        return slow_speed and trajectory['direction_changes'] > 2
    
    def _apply_rules(self, features: Dict) -> Dict:
        """Apply rule-based classification"""
        
        avg_speed = features['avg_speed']
        max_speed = features['max_speed']
        stop_freq = features['stop_frequency']
        stop_reg = features['stop_regularity']
        
        # Rule 1: Very low speed → Walking
        if max_speed < 3.0 and avg_speed < 2.0:
            return {
                'modality': 'walking',
                'confidence': 0.92,
                'method': 'rule_based',
                'reasoning': 'consistently_low_speed'
            }
        
        # Rule 2: GPS gaps + moderate/high speed → Subway
        if features['suggests_tunnel'] and avg_speed > 10:
            return {
                'modality': 'subway',
                'confidence': 0.88,
                'method': 'rule_based',
                'reasoning': 'tunnel_segments_with_speed'
            }
        
        # Rule 3: Very regular stops + medium speed → Bus
        if stop_reg == 'very_regular' and stop_freq > 0.4 and 5 < avg_speed < 15:
            return {
                'modality': 'bus',
                'confidence': 0.85,
                'method': 'rule_based',
                'reasoning': 'regular_frequent_stops'
            }
        
        # Rule 4: High speed + regular stops → Train
        if stop_reg in ['very_regular', 'somewhat_regular'] and avg_speed > 15:
            if features['stop_count'] > 3:
                return {
                    'modality': 'train',
                    'confidence': 0.83,
                    'method': 'rule_based',
                    'reasoning': 'high_speed_with_stops'
                }
        
        # Rule 5: Very high speed → Private vehicle
        if max_speed > 30:
            if features['has_parking_behavior']:
                return {
                    'modality': 'private_vehicle',
                    'confidence': 0.87,
                    'method': 'rule_based',
                    'reasoning': 'highway_speed_with_parking'
                }
            else:
                return {
                    'modality': 'ridehailing',
                    'confidence': 0.75,
                    'method': 'rule_based',
                    'reasoning': 'highway_speed_no_parking'
                }
        
        # Rule 6: Bike/scooter range
        if 3 < avg_speed < 8 and features['trajectory_smoothness'] > 0.7:
            if features['speed_variance'] < 1.5 and features['total_distance'] < 3000:
                return {
                    'modality': 'scootering',
                    'confidence': 0.70,
                    'method': 'rule_based',
                    'reasoning': 'consistent_moderate_speed_short_distance'
                }
            else:
                return {
                    'modality': 'bicycling',
                    'confidence': 0.78,
                    'method': 'rule_based',
                    'reasoning': 'cycling_speed_range'
                }
        
        # Low confidence - use profile matching
        return {
            'modality': None,
            'confidence': 0.0,
            'method': 'rule_based',
            'reasoning': 'no_confident_match'
        }
    
    def _match_to_profile(self, features: Dict) -> Dict:
        """Match features to modality profiles"""
        
        scores = {}
        
        for modality, profile in self.MODALITY_PROFILES.items():
            score = 0.0
            
            # Speed match
            speed_min, speed_max = profile['speed_range']
            if speed_min <= features['avg_speed'] <= speed_max:
                score += 0.3
            
            # Speed variance match
            if features['speed_variance'] <= profile['speed_variance_max']:
                score += 0.2
            
            # Stop frequency match
            freq_min, freq_max = profile['stop_frequency_range']
            if freq_min <= features['stop_frequency'] <= freq_max:
                score += 0.3
            
            # Category-specific bonuses
            if profile['category'] == 'public_transit':
                if features['stop_regularity'] in ['very_regular', 'somewhat_regular']:
                    score += 0.2
            
            scores[modality] = score
        
        # Get best match
        best_modality = max(scores.items(), key=lambda x: x[1])
        
        # Normalize confidence
        confidence = min(0.95, best_modality[1])
        
        return {
            'modality': best_modality[0],
            'confidence': confidence,
            'method': 'profile_matching',
            'all_scores': scores
        }
    
    def _haversine(self, coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
        """Calculate distance between two coordinates in meters"""
        lat1, lon1 = coord1
        lat2, lon2 = coord2
        
        R = 6371000  # Earth radius in meters
        phi1, phi2 = np.radians(lat1), np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlambda = np.radians(lon2 - lon1)
        
        a = np.sin(dphi/2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda/2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
        
        return R * c
    
    def _calculate_bearing(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate bearing between two points"""
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        
        dlon = lon2 - lon1
        x = np.sin(dlon) * np.cos(lat2)
        y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
        
        bearing = np.arctan2(x, y)
        return (np.degrees(bearing) + 360) % 360