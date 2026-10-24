"""
Base Trip Validator Module
Validates raw trip data from Excel/CSV before enhancement
Includes geographic validation for modality-distance consistency
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from math import radians, sin, cos, sqrt, atan2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of trip validation"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    trip_id: Optional[str] = None
    
    def add_error(self, message: str):
        self.errors.append(message)
        self.is_valid = False
    
    def add_warning(self, message: str):
        self.warnings.append(message)


class CityBoundary:
    """Represents a city boundary for geographic validation"""
    def __init__(self, name: str, center: Tuple[float, float], radius_km: float = 10):
        self.name = name
        self.center = center  # (lat, lon)
        self.radius_km = radius_km
    
    def contains_point(self, lat: float, lon: float) -> bool:
        """Check if a point is within the city boundary (simplified circle)"""
        distance_km = haversine_distance(self.center[0], self.center[1], lat, lon) / 1000
        return distance_km <= self.radius_km
    
    def distance_to(self, other: 'CityBoundary') -> float:
        """Distance in km to another city center"""
        return haversine_distance(
            self.center[0], self.center[1],
            other.center[0], other.center[1]
        ) / 1000


# Contra Costa County Cities
CITY_BOUNDARIES = {
    'Walnut Creek': CityBoundary('Walnut Creek', (37.9101, -122.0652), radius_km=5),
    'Pleasant Hill': CityBoundary('Pleasant Hill', (37.9480, -122.0608), radius_km=4),
    'Antioch': CityBoundary('Antioch', (38.0049, -121.8058), radius_km=8),
    'Pittsburg': CityBoundary('Pittsburg', (38.0280, -121.8847), radius_km=6),
    'Richmond': CityBoundary('Richmond', (37.9358, -122.3477), radius_km=7)
}

# Adjacent city pairs (cities you can reasonably walk between)
ADJACENT_CITIES = {
    ('Walnut Creek', 'Pleasant Hill'),
    ('Pleasant Hill', 'Walnut Creek'),
    ('Antioch', 'Pittsburg'),
    ('Pittsburg', 'Antioch')
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two coordinates"""
    R = 6371000  # Earth radius in meters
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    return R * c


def get_city_for_point(lat: float, lon: float) -> Optional[str]:
    """Determine which city a point belongs to"""
    for city_name, boundary in CITY_BOUNDARIES.items():
        if boundary.contains_point(lat, lon):
            return city_name
    return None


class BaseTripValidator:
    """
    Validates base trip data for quality and consistency
    """
    
    # Maximum reasonable distances by modality (meters)
    MAX_DISTANCES = {
        'walking': 8000,           # 8 km - very long but possible walk
        'bicycling': 30000,        # 30 km - long bike ride
        'scooter': 15000,          # 15 km - typical e-scooter range
        'scootering': 15000,       # Alternative name
        'private_vehicle': 500000, # 500 km - very long drive but possible
        'driving': 500000,         # 500 km - generic driving
        'ridehailing': 100000,     # 100 km - long ridehail
        'bus': 100000,             # 100 km - long bus route
        'light_rail': 100000,      # 100 km - long light rail
        'train': 200000,           # 200 km - long train trip
        'subway': 100000,          # 100 km - long subway (unlikely but possible)
        'unknown': 100000          # Default for unknown modality
    }
    
    # Minimum reasonable speeds by modality (km/h)
    MIN_SPEEDS = {
        'walking': 1.0,
        'bicycling': 5.0,
        'scooter': 5.0,
        'scootering': 5.0,
        'private_vehicle': 10.0,
        'driving': 10.0,
        'ridehailing': 10.0,
        'bus': 5.0,
        'light_rail': 15.0,
        'train': 20.0,
        'subway': 15.0
    }
    
    # Maximum reasonable speeds by modality (km/h)
    MAX_SPEEDS = {
        'walking': 8.0,
        'bicycling': 40.0,
        'scooter': 30.0,
        'scootering': 30.0,
        'private_vehicle': 150.0,
        'driving': 150.0,
        'ridehailing': 150.0,
        'bus': 100.0,
        'light_rail': 120.0,
        'train': 200.0,
        'subway': 120.0
    }
    
    def __init__(self, strict_mode: bool = False):
        """
        Initialize validator
        
        Args:
            strict_mode: If True, warnings become errors
        """
        self.strict_mode = strict_mode
        self.validation_stats = {
            'total_trips': 0,
            'valid_trips': 0,
            'invalid_trips': 0,
            'trips_with_warnings': 0
        }
    
    def validate_trip_file(self, file_path: str) -> Tuple[pd.DataFrame, List[ValidationResult]]:
        """
        Validate an entire trip file
        
        Returns:
            (valid_trips_df, validation_results)
        """
        logger.info(f"Loading trip file: {file_path}")
        
        # Load file
        if file_path.endswith('.xlsx'):
            df = pd.read_excel(file_path)
        elif file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            raise ValueError("File must be .xlsx or .csv")
        
        logger.info(f"Loaded {len(df)} trip segments")
        
        # Group by trip (assumes consecutive segments belong to same trip)
        trips = self._group_segments_into_trips(df)
        
        logger.info(f"Identified {len(trips)} trips")
        
        # Validate each trip
        validation_results = []
        valid_trips = []
        
        for trip_id, trip_segments in trips.items():
            result = self.validate_trip(trip_segments, trip_id)
            validation_results.append(result)
            
            self.validation_stats['total_trips'] += 1
            
            if result.is_valid:
                self.validation_stats['valid_trips'] += 1
                valid_trips.extend(trip_segments.to_dict('records'))
            else:
                self.validation_stats['invalid_trips'] += 1
            
            if result.warnings:
                self.validation_stats['trips_with_warnings'] += 1
        
        # Create DataFrame of valid trips
        valid_df = pd.DataFrame(valid_trips)
        
        # Print summary
        self._print_validation_summary(validation_results)
        
        return valid_df, validation_results
    
    def validate_trip(self, trip_df: pd.DataFrame, trip_id: str = None) -> ValidationResult:
        """
        Validate a single trip (one or more segments)
        
        Args:
            trip_df: DataFrame containing trip segments
            trip_id: Optional trip identifier
        """
        result = ValidationResult(is_valid=True, errors=[], warnings=[], trip_id=trip_id)
        
        # Check 1: Required columns
        self._check_required_columns(trip_df, result)
        if not result.is_valid:
            return result
        
        # Check 2: Coordinate validity
        self._check_coordinates(trip_df, result)
        
        # Check 3: Timestamp validity and ordering
        self._check_timestamps(trip_df, result)
        
        # Check 4: Duration validity
        self._check_durations(trip_df, result)
        
        # Check 5: Geographic validity (NEW)
        self._check_geographic_validity(trip_df, result)
        
        # Check 6: Speed validity (if modality provided)
        if 'modality' in trip_df.columns or 'predicted_modality' in trip_df.columns:
            self._check_speed_validity(trip_df, result)
        
        # Check 7: GPS jitter/noise
        self._check_gps_jitter(trip_df, result)
        
        # Convert warnings to errors in strict mode
        if self.strict_mode and result.warnings:
            result.errors.extend(result.warnings)
            result.warnings = []
            result.is_valid = False
        
        return result
    
    def _group_segments_into_trips(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Group segments into trips based on temporal gaps"""
        # If there's already a trip_id column, use it
        if 'trip_id' in df.columns:
            return {trip_id: group for trip_id, group in df.groupby('trip_id')}
        
        # Otherwise, infer trips based on temporal gaps
        # Segments more than 5 minutes apart are different trips
        trips = {}
        current_trip_id = 0
        current_segments = []
        
        for idx, row in df.iterrows():
            if current_segments:
                # Check time gap from last segment
                last_end = pd.to_datetime(current_segments[-1]['end_timestamp'])
                current_start = pd.to_datetime(row['start_timestamp'])
                gap = (current_start - last_end).total_seconds()
                
                if gap > 300:  # 5 minute gap = new trip
                    trips[f"trip_{current_trip_id}"] = pd.DataFrame(current_segments)
                    current_trip_id += 1
                    current_segments = []
            
            current_segments.append(row)
        
        # Add last trip
        if current_segments:
            trips[f"trip_{current_trip_id}"] = pd.DataFrame(current_segments)
        
        return trips
    
    def _check_required_columns(self, trip_df: pd.DataFrame, result: ValidationResult):
        """Check for required columns"""
        required = [
            'origin_lat', 'origin_long', 'destination_lat', 'destination_long',
            'start_timestamp', 'end_timestamp'
        ]
        
        missing = [col for col in required if col not in trip_df.columns]
        if missing:
            result.add_error(f"Missing required columns: {missing}")
    
    def _check_coordinates(self, trip_df: pd.DataFrame, result: ValidationResult):
        """Validate coordinate ranges"""
        # Check latitude range (-90 to 90)
        for col in ['origin_lat', 'destination_lat']:
            if col in trip_df.columns:
                invalid = trip_df[(trip_df[col] < -90) | (trip_df[col] > 90)]
                if not invalid.empty:
                    result.add_error(f"Invalid latitude values in {col}: {invalid[col].tolist()}")
        
        # Check longitude range (-180 to 180)
        for col in ['origin_long', 'destination_long']:
            if col in trip_df.columns:
                invalid = trip_df[(trip_df[col] < -180) | (trip_df[col] > 180)]
                if not invalid.empty:
                    result.add_error(f"Invalid longitude values in {col}: {invalid[col].tolist()}")
        
        # Check for null coordinates
        coord_cols = ['origin_lat', 'origin_long', 'destination_lat', 'destination_long']
        for col in coord_cols:
            if col in trip_df.columns:
                nulls = trip_df[col].isnull().sum()
                if nulls > 0:
                    result.add_error(f"Found {nulls} null values in {col}")
    
    def _check_timestamps(self, trip_df: pd.DataFrame, result: ValidationResult):
        """Validate timestamps"""
        try:
            # Convert to datetime if not already
            trip_df['start_timestamp'] = pd.to_datetime(trip_df['start_timestamp'])
            trip_df['end_timestamp'] = pd.to_datetime(trip_df['end_timestamp'])
            
            # Check that end > start for each segment
            invalid = trip_df[trip_df['end_timestamp'] <= trip_df['start_timestamp']]
            if not invalid.empty:
                result.add_error(f"Found {len(invalid)} segments where end_timestamp <= start_timestamp")
            
            # Check temporal ordering of segments
            for i in range(len(trip_df) - 1):
                current_end = trip_df.iloc[i]['end_timestamp']
                next_start = trip_df.iloc[i + 1]['start_timestamp']
                
                if next_start < current_end:
                    result.add_warning(f"Segment {i+1} starts before segment {i} ends (overlap)")
                
                # Check for unreasonable gaps between segments
                gap_seconds = (next_start - current_end).total_seconds()
                if gap_seconds > 1800:  # 30 minutes
                    result.add_warning(f"Large time gap ({gap_seconds/60:.1f} min) between segments {i} and {i+1}")
        
        except Exception as e:
            result.add_error(f"Error parsing timestamps: {str(e)}")
    
    def _check_durations(self, trip_df: pd.DataFrame, result: ValidationResult):
        """Validate trip durations"""
        # Check for unreasonably short segments (< 1 second)
        short_segments = trip_df[trip_df['trip_duration_sec'] < 1]
        if not short_segments.empty:
            result.add_warning(f"Found {len(short_segments)} segments with duration < 1 second")
        
        # Check for unreasonably long segments (> 4 hours)
        long_segments = trip_df[trip_df['trip_duration_sec'] > 14400]
        if not long_segments.empty:
            result.add_warning(f"Found {len(long_segments)} segments with duration > 4 hours")
        
        # Check total trip duration
        total_duration = trip_df['trip_duration_sec'].sum()
        if total_duration > 28800:  # 8 hours
            result.add_warning(f"Total trip duration is very long: {total_duration/3600:.1f} hours")
    
    def _check_geographic_validity(self, trip_df: pd.DataFrame, result: ValidationResult):
        """
        NEW: Check geographic validity including city boundaries and modality constraints
        """
        # Get origin and destination coordinates
        origin_lat = trip_df.iloc[0]['origin_lat']
        origin_lon = trip_df.iloc[0]['origin_long']
        dest_lat = trip_df.iloc[-1]['destination_lat']
        dest_lon = trip_df.iloc[-1]['destination_long']
        
        # Calculate trip distance
        trip_distance_m = haversine_distance(origin_lat, origin_lon, dest_lat, dest_lon)
        trip_distance_km = trip_distance_m / 1000
        
        # Determine cities
        origin_city = get_city_for_point(origin_lat, origin_lon)
        dest_city = get_city_for_point(dest_lat, dest_lon)
        
        # Check if trip is within our geofence
        if origin_city is None:
            result.add_error(f"Origin ({origin_lat:.4f}, {origin_lon:.4f}) is outside all city boundaries")
        
        if dest_city is None:
            result.add_error(f"Destination ({dest_lat:.4f}, {dest_lon:.4f}) is outside all city boundaries")
        
        # If both are outside our cities, this trip is invalid
        if origin_city is None and dest_city is None:
            result.add_error("Trip is completely outside the Contra Costa County coverage area")
            return
        
        # Check modality-specific constraints
        modality = trip_df.iloc[0].get('modality', 'unknown')
        if modality == 'unknown' and 'predicted_modality' in trip_df.columns:
            modality = trip_df.iloc[0]['predicted_modality']
        
        # Geographic validation by modality
        # Use DISTANCE as primary criterion, city boundaries as secondary check
        
        if modality == 'walking':
            # Walking trips should be reasonable distance
            max_distance = self.MAX_DISTANCES['walking']  # 8000m = 8km
            
            if trip_distance_m > max_distance:
                # Distance exceeds maximum - this is an error
                result.add_error(
                    f"Walking trip distance ({trip_distance_km:.1f} km) exceeds "
                    f"reasonable maximum ({max_distance/1000:.1f} km). "
                    f"Likely wrong modality or data corruption."
                )
            elif trip_distance_m > 5000:
                # Long but possible - just a warning
                result.add_warning(
                    f"Long walking trip: {trip_distance_km:.1f} km. "
                    f"Verify this is actually a walking trip."
                )
            
            # Additional check: non-adjacent cities with reasonable distance
            if origin_city and dest_city and origin_city != dest_city:
                city_pair = (origin_city, dest_city)
                if city_pair not in ADJACENT_CITIES:
                    # Non-adjacent cities - check if distance makes sense
                    # e.g., Walnut Creek → Antioch is ~25km - impossible to walk
                    if trip_distance_m > 3000:  # 3km threshold for non-adjacent
                        result.add_error(
                            f"Walking trip between non-adjacent cities "
                            f"{origin_city} → {dest_city} ({trip_distance_km:.1f} km) "
                            f"is not feasible. Likely wrong modality."
                        )
        
        elif modality == 'bicycling':
            # Bicycling has wider range
            max_distance = self.MAX_DISTANCES['bicycling']  # 30000m = 30km
            
            if trip_distance_m > max_distance:
                result.add_error(
                    f"Bicycling trip distance ({trip_distance_km:.1f} km) exceeds "
                    f"reasonable maximum ({max_distance/1000:.1f} km). "
                    f"Likely wrong modality or data corruption."
                )
            elif trip_distance_m > 20000:
                # Long but possible - just a warning
                result.add_warning(
                    f"Long bicycling trip: {trip_distance_km:.1f} km. "
                    f"This is an unusually long bike ride."
                )
            
            # Bicycles can reasonably travel between adjacent cities
            if origin_city and dest_city and origin_city != dest_city:
                city_pair = (origin_city, dest_city)
                if city_pair not in ADJACENT_CITIES and trip_distance_m > 15000:
                    result.add_warning(
                        f"Bicycling trip between non-adjacent cities "
                        f"{origin_city} → {dest_city} ({trip_distance_km:.1f} km). "
                        f"This is unusual but possible for experienced cyclists."
                    )
        
        elif modality == 'scooter':
            # E-scooters have limited range
            max_distance = self.MAX_DISTANCES['scooter']  # 15000m = 15km
            
            if trip_distance_m > max_distance:
                result.add_error(
                    f"Scooter trip distance ({trip_distance_km:.1f} km) exceeds "
                    f"typical scooter range ({max_distance/1000:.1f} km). "
                    f"Likely wrong modality."
                )
            elif trip_distance_m > 10000:
                result.add_warning(
                    f"Long scooter trip: {trip_distance_km:.1f} km. "
                    f"Approaching typical scooter battery limits."
                )
        
        elif modality in ['driving', 'private_vehicle', 'ridehailing']:
            # Driving has very wide range - only flag extremely long trips
            if trip_distance_m > 200000:  # 200km
                result.add_warning(
                    f"Very long {modality} trip: {trip_distance_km:.1f} km."
                )
        
        elif modality in ['bus', 'train', 'light_rail', 'subway']:
            # Public transit can cover long distances
            # But subway/light_rail typically more localized
            if modality in ['subway', 'light_rail']:
                if trip_distance_m > 50000:  # 50km
                    result.add_warning(
                        f"Unusually long {modality} trip: {trip_distance_km:.1f} km. "
                        f"Most {modality} systems cover shorter distances."
                    )
            elif trip_distance_m > 100000:  # 100km for bus/train
                result.add_warning(
                    f"Very long {modality} trip: {trip_distance_km:.1f} km."
                )
        
        # Add trip metadata for later use
        trip_df.attrs['origin_city'] = origin_city
        trip_df.attrs['dest_city'] = dest_city
        trip_df.attrs['trip_distance_m'] = trip_distance_m
        trip_df.attrs['crosses_cities'] = (origin_city != dest_city) if (origin_city and dest_city) else False
    
    def _check_speed_validity(self, trip_df: pd.DataFrame, result: ValidationResult):
        """Check if speeds are reasonable for the modality"""
        modality = trip_df.iloc[0].get('modality', 'unknown')
        if modality == 'unknown' and 'predicted_modality' in trip_df.columns:
            modality = trip_df.iloc[0]['predicted_modality']
        
        for idx, row in trip_df.iterrows():
            # Calculate segment distance
            distance_m = haversine_distance(
                row['origin_lat'], row['origin_long'],
                row['destination_lat'], row['destination_long']
            )
            
            # Calculate speed (km/h)
            duration_hours = row['trip_duration_sec'] / 3600
            if duration_hours > 0:
                speed_kmh = (distance_m / 1000) / duration_hours
                
                # Check against reasonable bounds
                min_speed = self.MIN_SPEEDS.get(modality, 0)
                max_speed = self.MAX_SPEEDS.get(modality, 200)
                
                if speed_kmh < min_speed:
                    result.add_warning(
                        f"Segment {idx}: Speed ({speed_kmh:.1f} km/h) is too slow for {modality}"
                    )
                elif speed_kmh > max_speed:
                    result.add_error(
                        f"Segment {idx}: Speed ({speed_kmh:.1f} km/h) exceeds reasonable maximum "
                        f"for {modality} ({max_speed} km/h)"
                    )
    
    def _check_gps_jitter(self, trip_df: pd.DataFrame, result: ValidationResult):
        """Check for GPS noise/jitter"""
        # Look for segments with very small distances but longer durations
        # This indicates GPS jitter (device not moving but coordinates jumping)
        
        jitter_count = 0
        for idx, row in trip_df.iterrows():
            distance_m = haversine_distance(
                row['origin_lat'], row['origin_long'],
                row['destination_lat'], row['destination_long']
            )
            
            # If distance < 10m but duration > 10 seconds, likely jitter
            if distance_m < 10 and row['trip_duration_sec'] > 10:
                jitter_count += 1
        
        if jitter_count > 0:
            result.add_warning(f"Found {jitter_count} segments with possible GPS jitter")
    
    def _print_validation_summary(self, results: List[ValidationResult]):
        """Print validation summary statistics"""
        print("\n" + "="*60)
        print("VALIDATION SUMMARY")
        print("="*60)
        print(f"Total trips processed: {self.validation_stats['total_trips']}")
        print(f"Valid trips: {self.validation_stats['valid_trips']}")
        print(f"Invalid trips: {self.validation_stats['invalid_trips']}")
        print(f"Trips with warnings: {self.validation_stats['trips_with_warnings']}")
        
        # Print details of invalid trips
        invalid_results = [r for r in results if not r.is_valid]
        if invalid_results:
            print(f"\n{len(invalid_results)} INVALID TRIPS:")
            for r in invalid_results[:10]:  # Show first 10
                print(f"\nTrip {r.trip_id}:")
                for error in r.errors:
                    print(f"  ✗ {error}")
        
        # Print warnings
        warning_results = [r for r in results if r.warnings]
        if warning_results:
            print(f"\n{len(warning_results)} TRIPS WITH WARNINGS:")
            for r in warning_results[:5]:  # Show first 5
                print(f"\nTrip {r.trip_id}:")
                for warning in r.warnings:
                    print(f"  ⚠ {warning}")
        
        print("="*60)


# Main execution
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python base_trip_validator.py <trip_file.xlsx>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    
    # Create validator
    validator = BaseTripValidator(strict_mode=False)
    
    # Validate file
    valid_trips, validation_results = validator.validate_trip_file(file_path)
    
    print(f"\n✓ Validation complete. {len(valid_trips)} valid trip segments.")
    
    # Optionally save valid trips
    if len(valid_trips) > 0:
        output_file = file_path.replace('.xlsx', '_validated.xlsx').replace('.csv', '_validated.csv')
        if output_file.endswith('.xlsx'):
            valid_trips.to_excel(output_file, index=False)
        else:
            valid_trips.to_csv(output_file, index=False)
        print(f"✓ Valid trips saved to: {output_file}")