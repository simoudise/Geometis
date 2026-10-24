"""
Trip Enhancer - Main Orchestrator Module (COMPLETE VERSION)
Coordinates Stages 1-5 of trip enhancement pipeline:
- Stage 1: Validation and Ingestion
- Stage 2: Geospatial and Route Enrichment
- Stage 3: Contextual Data Enrichment  
- Stage 4: Multimodal Data Integration & Intent Prediction
- Stage 5: Label Generation (use-case specific)

Produces Enhanced Trip JSON ready for analysis
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import json
import logging
import requests

# Import our validated components
from base_trip_validator import BaseTripValidator, ValidationResult
from POI_resolver import POIResolver, POICandidate
from intent_predictor import IntentPredictor, IntentPrediction
from route_analyzer import RouteAnalyzer, RouteAnalysis

from modality_predictor import ModalityPredictor, Segment

# Import profile managers (conditional based on use case)
from traveler_profile_manager import TravelerProfileManager
from trucker_profile_manager import TruckerProfileManager

# Import label generators (conditional based on use case)
from transportation_planner_labels import TransportationPlannerLabelGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TripEnhancer:
    """
    Main orchestrator for complete trip enhancement pipeline (Stages 1-5)
    Transforms validated base trips into fully enhanced and labeled trips with:
    - Resolved POIs for all endpoints
    - Reconstructed routes with OSRM
    - Alternative route analysis
    - Predicted trip intent
    - Contextual enrichment (weather, traffic, etc.)
    - Use-case specific labels
    """
    
    def __init__(self,
                 kg_file: str,
                 tko_file: str,
                 embeddings_file: Optional[str] = None,
                 osrm_server: str = "http://localhost:5001",
                 profile_storage_dir: Optional[str] = "./profiles",
                 use_case: str = 'consumer'):
        """
        Initialize Trip Enhancer
        
        Args:
            kg_file: Path to location knowledge graph (TTL)
            tko_file: Path to trip ontology (TTL)
            embeddings_file: Path to entity embeddings (CSV, optional)
            osrm_server: OSRM server URL
            profile_storage_dir: Directory for traveler/trucker profiles
            use_case: 'consumer' or 'fleet_management'
        """
        print("="*60)
        print("INITIALIZING TRIP ENHANCEMENT PIPELINE")
        print(f"Use Case: {use_case.upper()}")
        print("="*60)
        
        # Store configuration
        self.use_case = use_case
        self.osrm_server = osrm_server
        
        # Initialize all components
        print("\n[1/7] Loading POI Resolver...")
        self.poi_resolver = POIResolver(kg_file, embeddings_file)
        
        print("\n[2/7] Loading Intent Predictor...")
        self.intent_predictor = IntentPredictor(tko_file)
        
        print("\n[3/7] Loading Route Analyzer...")
        self.route_analyzer = RouteAnalyzer()
        
        print("\n[4/7] Loading Profile Manager...")
        if use_case == 'consumer':
            self.profile_manager = TravelerProfileManager(storage_dir=profile_storage_dir)
            print("    → Using TravelerProfileManager for consumer trips")
        elif use_case == 'fleet_management':
            self.profile_manager = TruckerProfileManager(storage_dir=profile_storage_dir)
            print("    → Using TruckerProfileManager for fleet trips")
        else:
            raise ValueError(f"Unknown use case: {use_case}. Must be 'consumer' or 'fleet_management'")
        
        print("\n[5/7] Loading Trip Validator...")
        self.validator = BaseTripValidator(strict_mode=False)
        
        print("\n[6/7] Loading Label Generators...")
        if use_case == 'consumer':
            self.label_generator = TransportationPlannerLabelGenerator()
            print("    → Using TransportationPlannerLabelGenerator")
        elif use_case == 'fleet_management':
            # TODO: Create FleetManagementLabelGenerator
            self.label_generator = None
            print("    → Fleet labels not yet implemented")
        
        print("\n[7/7] Loading Modality Predictor...")
        self.modality_predictor = ModalityPredictor()
        print("    → Ready to predict walking, bicycling, transit, and driving")
        
        print("\n✓ Trip Enhancement Pipeline Ready")
        print("="*60)
    
    def enhance_trip_file(self, 
                         input_file: str,
                         output_file: str) -> Tuple[List[Dict], Dict]:
        """
        Enhance an entire trip file through all 5 stages
        
        Args:
            input_file: Path to base trip Excel/CSV file
            output_file: Path to save enhanced trips JSON
            
        Returns:
            (enhanced_trips, statistics)
        """
        print("\n" + "="*60)
        print(f"ENHANCING TRIP FILE: {input_file}")
        print(f"Use Case: {self.use_case}")
        print("="*60)
        
        # Stage 1: Validation (already done, but verify)
        print("\n[STAGE 1] Validating base trips...")
        valid_trips_df, validation_results = self.validator.validate_trip_file(input_file)
        
        if len(valid_trips_df) == 0:
            print("\n✗ No valid trips found after validation")
            return [], {'error': 'No valid trips'}
        
        print(f"\n✓ {len(valid_trips_df)} valid trip segments to enhance")
        
        # Group segments into trips
        trips = self._group_segments(valid_trips_df)
        print(f"✓ Grouped into {len(trips)} complete trips")
        
        # Enhance each trip
        enhanced_trips = []
        stats = {
            'total_trips': len(trips),
            'successfully_enhanced': 0,
            'failed_enhancement': 0,
            'poi_resolution_successes': 0,
            'poi_resolution_failures': 0,
            'route_reconstruction_successes': 0,
            'route_reconstruction_failures': 0,
            'intent_predictions': 0,
            'labels_generated': 0
        }
        
        for i, (trip_id, trip_segments) in enumerate(trips.items(), 1):
            print(f"\n--- Enhancing Trip {i}/{len(trips)}: {trip_id} ---")
            
            try:
                enhanced_trip = self.enhance_trip(trip_segments)
                
                if enhanced_trip:
                    enhanced_trips.append(enhanced_trip)
                    stats['successfully_enhanced'] += 1
                    
                    # Update detailed stats
                    if enhanced_trip.get('origin_poi'):
                        stats['poi_resolution_successes'] += 1
                    if enhanced_trip.get('route_analysis'):
                        stats['route_reconstruction_successes'] += 1
                    if enhanced_trip.get('primary_intent'):
                        stats['intent_predictions'] += 1
                    if enhanced_trip.get('labels'):
                        stats['labels_generated'] += 1
                else:
                    stats['failed_enhancement'] += 1
                    
            except Exception as e:
                logger.error(f"Error enhancing trip {trip_id}: {e}")
                stats['failed_enhancement'] += 1
        
        # Save enhanced trips
        print(f"\n{'='*60}")
        print("SAVING ENHANCED TRIPS")
        print(f"{'='*60}")
        
        with open(output_file, 'w') as f:
            json.dump(enhanced_trips, f, indent=2, default=str)
        
        print(f"\n✓ Saved {len(enhanced_trips)} enhanced trips to {output_file}")
        
        # Print summary statistics
        self._print_enhancement_summary(stats)
        
        return enhanced_trips, stats
    
    def enhance_trip(self, trip_segments: pd.DataFrame) -> Optional[Dict]:
        """
        Enhance a single trip through all 5 stages
        
        Args:
            trip_segments: DataFrame of trip segments (from validator)
            
        Returns:
            Enhanced trip dictionary ready for analysis
        """
        # Extract trip metadata
        first_seg = trip_segments.iloc[0]
        last_seg = trip_segments.iloc[-1]
        
        trip_id = first_seg.get('trip_id', f"trip_{hash(str(first_seg))}")
        traveler_id = first_seg.get('traveler_id', 'unknown')
        
        # Initialize enhanced trip structure
        enhanced_trip = {
            'trip_id': trip_id,
            'traveler_id': traveler_id,
            'use_case': self.use_case,
            'processing_metadata': {
                'pipeline_version': '2.0.0',
                'enhancement_timestamp': datetime.now().isoformat(),
                'stages_completed': ['stage1_validation']
            },
            'base_trip_metadata': {
                'segment_count': len(trip_segments),
                'total_duration_sec': trip_segments['trip_duration_sec'].sum(),
                'total_distance_m': getattr(trip_segments.attrs, 'trip_distance_m', None)
            }
        }
        
        # ============================================================
        # STAGE 2: GEOSPATIAL AND ROUTE ENRICHMENT
        # ============================================================
        print("\n  [STAGE 2] Geospatial and Route Enrichment")
        
        # 2.0: Predict modality if not provided
        print("    → Predicting modality...")
        segments_for_prediction = []
        for idx, seg in trip_segments.iterrows():
            segment = Segment(
                segment_id=str(idx),
                start_lat=seg['origin_lat'],
                start_lon=seg['origin_long'],
                end_lat=seg['destination_lat'],
                end_lon=seg['destination_long'],
                start_time=pd.to_datetime(seg['start_timestamp']),
                end_time=pd.to_datetime(seg['end_timestamp']),
                distance_meters=self._calculate_segment_distance(
                    seg['origin_lat'], seg['origin_long'],
                    seg['destination_lat'], seg['destination_long']
                ),
                modality=seg.get('modality')
            )
            segments_for_prediction.append(segment)

        modality_segments = self.modality_predictor.predict_trip_modalities(segments_for_prediction)

        if modality_segments:
            primary_modality = modality_segments[0].modality
            primary_confidence = modality_segments[0].confidence
            print(f"    ✓ Predicted modality: {primary_modality} (confidence: {primary_confidence:.2%})")
    
            enhanced_trip['modality_segments'] = [
                {
                    'modality': ms.modality,
                    'confidence': ms.confidence,
                    'start_time': ms.start_time.isoformat(),
                    'end_time': ms.end_time.isoformat(),
                    'segment_count': len(ms.raw_segments)
                }
                for ms in modality_segments
            ]
            trip_modality = primary_modality
        else:
            trip_modality = first_seg.get('modality', 'unknown')
            print(f"    ⚠ Could not predict modality, using: {trip_modality}")
            enhanced_trip['modality_segments'] = []
        
        # 2.1: Resolve Origin and Destination POIs
        print("    → Resolving origin and destination POIs...")
        origin_lat = first_seg['origin_lat']
        origin_lon = first_seg['origin_long']
        dest_lat = last_seg['destination_lat']
        dest_lon = last_seg['destination_long']
        
        origin_candidates, dest_candidates = self.poi_resolver.resolve_trip_endpoints(
            origin_lat, origin_lon,
            dest_lat, dest_lon,
            context={
                'time_of_day': self._categorize_time(first_seg['start_timestamp']),
                'day_of_week': 'weekday' if pd.to_datetime(first_seg['start_timestamp']).weekday() < 5 else 'weekend'
            }
        )
        
        if origin_candidates:
            enhanced_trip['origin_poi'] = origin_candidates[0].to_dict()
            enhanced_trip['origin_poi_candidates'] = [c.to_dict() for c in origin_candidates[:3]]
        else:
            print("    ⚠ No origin POI candidates found")
            enhanced_trip['origin_poi'] = None
        
        if dest_candidates:
            enhanced_trip['destination_poi'] = dest_candidates[0].to_dict()
            enhanced_trip['destination_poi_candidates'] = [c.to_dict() for c in dest_candidates[:3]]
        else:
            print("    ⚠ No destination POI candidates found")
            enhanced_trip['destination_poi'] = None
        
        # 2.2: Detect intermediate stops
        print("    → Detecting intermediate stops...")
        intermediate_stops = self.poi_resolver.find_intermediate_stops(
            trip_segments.to_dict('records'),
            min_dwell_time=60.0
        )
        
        if intermediate_stops:
            enhanced_trip['intermediate_stops'] = [
                {
                    'latitude': lat,
                    'longitude': lon,
                    'dwell_time_sec': dwell,
                    'poi_candidates': [c.to_dict() for c in candidates]
                }
                for lat, lon, dwell, candidates in intermediate_stops
            ]
            print(f"    ✓ Found {len(intermediate_stops)} intermediate stops")
        else:
            enhanced_trip['intermediate_stops'] = []
        
        # 2.3: Route reconstruction with OSRM
        print("    → Reconstructing route with OSRM...")
        route_analysis = self.route_analyzer.analyze_trip_route(
            trip_segments=trip_segments,
            origin_poi=enhanced_trip.get('origin_poi'),
            dest_poi=enhanced_trip.get('destination_poi'),
            modality=trip_modality  # Use predicted modality
        )
        
        if route_analysis:
            enhanced_trip['route_analysis'] = route_analysis.to_dict()
            print(f"    ✓ Route reconstructed: {route_analysis.actual_route_distance_m:.0f}m")
            
            # Add alternative routes
            if route_analysis.alternative_routes:
                print(f"    ✓ Found {len(route_analysis.alternative_routes)} alternative routes")
        else:
            print("    ⚠ Route reconstruction failed")
            enhanced_trip['route_analysis'] = None
        
        enhanced_trip['processing_metadata']['stages_completed'].append('stage2_geospatial')
        
        # ============================================================
        # STAGE 3: CONTEXTUAL DATA ENRICHMENT
        # ============================================================
        print("\n  [STAGE 3] Contextual Data Enrichment")
        
        # 3.1: Add temporal context
        start_time = pd.to_datetime(first_seg['start_timestamp'])
        end_time = pd.to_datetime(last_seg['end_timestamp'])
        
        enhanced_trip['temporal_context'] = {
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'duration_sec': (end_time - start_time).total_seconds(),
            'time_of_day': self._categorize_time(start_time),
            'day_of_week': start_time.strftime('%A'),
            'is_weekend': start_time.weekday() >= 5,
            'is_rush_hour': self._is_rush_hour(start_time)
        }
        
        # 3.2: Add weather conditions
        print("    → Fetching weather data...")
        weather = self._get_weather_data(origin_lat, origin_lon, start_time)
        enhanced_trip['weather_conditions'] = weather
        
        # 3.3: Add traffic/congestion
        print("    → Estimating traffic conditions...")
        traffic = self._estimate_traffic(start_time)
        enhanced_trip['traffic_conditions'] = traffic
        
        # 3.4: Get profile (for disambiguation and patterns)
        print("    → Loading profile...")
        profile = self.profile_manager.get_profile(traveler_id)
        if profile:
            print(f"    ✓ Profile loaded: {profile.profile_maturity}")
            enhanced_trip['profile_summary'] = self.profile_manager.get_profile_summary(traveler_id)
        else:
            print("    ⚠ No profile available")
            enhanced_trip['profile_summary'] = None
        
        enhanced_trip['processing_metadata']['stages_completed'].append('stage3_contextual')
        
        # ============================================================
        # STAGE 4: MULTIMODAL INTEGRATION & INTENT PREDICTION
        # ============================================================
        print("\n  [STAGE 4] Intent Prediction")
        
        # 4.1: Predict trip intent
        print("    → Predicting trip intent...")
        
        # Calculate distance safely
        if enhanced_trip.get('route_analysis'):
            distance_meters = enhanced_trip['route_analysis'].get('actual_route_distance_m', 0)
        else:
            # Calculate from coordinates
            from math import radians, sin, cos, sqrt, atan2
            R = 6371000
            lat1, lon1 = radians(origin_lat), radians(origin_lon)
            lat2, lon2 = radians(dest_lat), radians(dest_lon)
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            distance_meters = R * c

        # Prepare trip data for intent prediction
        trip_data = {
            'origin_poi': enhanced_trip.get('origin_poi', {}),
            'destination_poi': enhanced_trip.get('destination_poi', {}),
            'start_time': start_time,
            'end_time': end_time,
            'modality': first_seg.get('modality', 'unknown'),
            'distance_meters': float(distance_meters) if distance_meters else 0.0,
            'duration_seconds': enhanced_trip['base_trip_metadata']['total_duration_sec'],
            'dwell_time': 0
    }
        
        intent_prediction = self.intent_predictor.predict_intent(trip_data, use_case=self.use_case)
        
        enhanced_trip['primary_intent'] = intent_prediction.to_dict()
        
        print(f"    ✓ Intent: {intent_prediction.intent_subclass} (confidence: {intent_prediction.confidence:.2%})")
        
        # 4.2: Check employee/depot disambiguation
        if profile and enhanced_trip.get('destination_poi'):
            dest_poi_id = enhanced_trip['destination_poi'].get('uri')
            
            if self.use_case == 'consumer':
                is_employee, confidence = self.profile_manager.is_employee_at_location(
                    traveler_id, dest_poi_id
                )
                if is_employee:
                    print(f"    ℹ Traveler is likely employee at destination (confidence: {confidence:.2%})")
                    enhanced_trip['employee_disambiguation'] = {
                        'is_employee_at_destination': True,
                        'confidence': confidence
                    }
            elif self.use_case == 'fleet_management':
                is_depot, confidence = self.profile_manager.is_depot_delivery(
                    traveler_id, dest_poi_id
                )
                if is_depot:
                    print(f"    ℹ This is a depot location (confidence: {confidence:.2%})")
                    enhanced_trip['depot_identification'] = {
                        'is_depot': True,
                        'confidence': confidence
                    }
        
        enhanced_trip['processing_metadata']['stages_completed'].append('stage4_intent')
        
        # ============================================================
        # STAGE 5: LABEL GENERATION (USE CASE SPECIFIC)
        # ============================================================
        print("\n  [STAGE 5] Label Generation")
        
        if self.label_generator:
            print("    → Generating use-case specific labels...")
            
            # Prepare stage data for label generation
            stage2_data = {
                'modality_segments': enhanced_trip.get('modality_segments', []),
                'route_used': enhanced_trip.get('route_analysis', {}),
                'alternative_routes': enhanced_trip.get('route_analysis', {}).get('alternative_routes', [])
            }
            
            stage3_data = {
                'traffic_data': enhanced_trip.get('traffic_conditions', {}),
                'weather_data': enhanced_trip.get('weather_conditions', {})
            }
            
            # Get traveler history (if available)
            # TODO: Implement history retrieval
            traveler_history = None
            
            # Generate labels
            labels = self.label_generator.generate_labels(
                trip_data=trip_data,
                stage2_data=stage2_data,
                stage3_data=stage3_data,
                traveler_history=traveler_history
            )
            
            enhanced_trip['labels'] = labels.to_dict()
            
            print(f"    ✓ Generated labels for {self.use_case}")
            if self.use_case == 'consumer':
                print(f"      - Shortest route: {labels.shortest_route}")
                print(f"      - Fastest route: {labels.fastest_route}")
                print(f"      - Active mobility: {labels.active_mobility_route}")
                print(f"      - Carbon neutral: {labels.carbon_neutral}")
        else:
            print("    ⚠ No label generator available for this use case")
            enhanced_trip['labels'] = None
        
        enhanced_trip['processing_metadata']['stages_completed'].append('stage5_labels')
        
        print("\n  ✓ Trip enhancement complete (all 5 stages)")
        
        return enhanced_trip
    
    def _group_segments(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Group segments into complete trips"""
        # If trip_id exists, use it
        if 'trip_id' in df.columns:
            return {trip_id: group for trip_id, group in df.groupby('trip_id')}
        
        # Otherwise, infer trips from temporal gaps
        trips = {}
        current_trip = []
        trip_counter = 0
        
        for idx, row in df.iterrows():
            if current_trip:
                last_end = pd.to_datetime(current_trip[-1]['end_timestamp'])
                current_start = pd.to_datetime(row['start_timestamp'])
                gap = (current_start - last_end).total_seconds()
                
                if gap > 300:  # 5 minute gap = new trip
                    trips[f"trip_{trip_counter}"] = pd.DataFrame(current_trip)
                    trip_counter += 1
                    current_trip = []
            
            current_trip.append(row)
        
        if current_trip:
            trips[f"trip_{trip_counter}"] = pd.DataFrame(current_trip)
        
        return trips
    
    def _extract_modality_segments(self, trip_segments: pd.DataFrame) -> List[Dict]:
        """Extract modality segments from trip data"""
        segments = []
        for idx, seg in trip_segments.iterrows():
            segments.append({
                'modality': seg.get('modality', 'unknown'),
                'duration_seconds': seg.get('trip_duration_sec', 0),
                'distance_meters': getattr(seg, 'trip_distance_m', 0)
            })
        return segments
    
    def _categorize_time(self, timestamp) -> str:
        """Categorize time of day"""
        if isinstance(timestamp, str):
            timestamp = pd.to_datetime(timestamp)
        
        hour = timestamp.hour
        
        if 5 <= hour < 7:
            return 'early_morning'
        elif 7 <= hour < 9:
            return 'morning'
        elif 9 <= hour < 12:
            return 'mid_morning'
        elif 12 <= hour < 14:
            return 'midday'
        elif 14 <= hour < 17:
            return 'afternoon'
        elif 17 <= hour < 20:
            return 'evening'
        elif 20 <= hour < 23:
            return 'night'
        else:
            return 'late_night'
    
    def _is_rush_hour(self, timestamp) -> bool:
        """Determine if time is during rush hour"""
        if isinstance(timestamp, str):
            timestamp = pd.to_datetime(timestamp)
        
        hour = timestamp.hour
        is_weekday = timestamp.weekday() < 5
        
        return is_weekday and ((7 <= hour < 10) or (16 <= hour < 19))
    
    def _get_weather_data(self, lat: float, lon: float, timestamp: datetime) -> Dict:
        """Fetch weather data from Open-Meteo API"""
        date_str = timestamp.strftime('%Y-%m-%d')
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            'latitude': lat,
            'longitude': lon,
            'start_date': date_str,
            'end_date': date_str,
            'hourly': 'temperature_2m,precipitation,windspeed_10m,relativehumidity_2m'
        }
        
        try:
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            hour = timestamp.hour
            hourly = data.get('hourly', {})
            
            temp = hourly.get('temperature_2m', [None] * 24)[hour] if hour < len(hourly.get('temperature_2m', [])) else None
            precip = hourly.get('precipitation', [None] * 24)[hour] if hour < len(hourly.get('precipitation', [])) else None
            wind = hourly.get('windspeed_10m', [None] * 24)[hour] if hour < len(hourly.get('windspeed_10m', [])) else None
            humidity = hourly.get('relativehumidity_2m', [None] * 24)[hour] if hour < len(hourly.get('relativehumidity_2m', [])) else None
            
            return {
                'temperature_celsius': temp,
                'precipitation_mm': precip,
                'wind_speed_kmh': wind,
                'humidity_percent': humidity,
                'data_source': 'open-meteo'
            }
        except Exception as e:
            logger.warning(f"Could not fetch weather data: {e}")
            return {'data_source': 'unavailable'}
    
    def _estimate_traffic(self, timestamp: datetime) -> Dict:
        """Estimate traffic based on time of day (heuristic)"""
        hour = timestamp.hour
        day = timestamp.weekday()
        
        is_rush_hour = (7 <= hour <= 9 or 16 <= hour <= 18) and day < 5
        
        if is_rush_hour:
            congestion = 0.7
            description = 'heavy'
        elif 6 <= hour <= 20:
            congestion = 0.4
            description = 'moderate'
        else:
            congestion = 0.1
            description = 'light'
        
        return {
            'average_congestion': congestion,
            'congestion_description': description,
            'data_source': 'time_based_heuristic'
        }
    
    def _calculate_segment_distance(self, lat1: float, lon1: float, 
                                    lat2: float, lon2: float) -> float:
        """Calculate distance between two points in meters"""
        from math import radians, sin, cos, sqrt, atan2
    
        R = 6371000  # Earth radius in meters
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
    
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
    
        return R * c

    def _print_enhancement_summary(self, stats: Dict):
        """Print summary statistics"""
        print("\n" + "="*60)
        print("ENHANCEMENT SUMMARY")
        print("="*60)
        print(f"Total trips: {stats['total_trips']}")
        print(f"Successfully enhanced: {stats['successfully_enhanced']}")
        print(f"Failed enhancement: {stats['failed_enhancement']}")
        print(f"\nComponent Success Rates:")
        print(f"  POI Resolution: {stats['poi_resolution_successes']}/{stats['total_trips']}")
        print(f"  Route Reconstruction: {stats['route_reconstruction_successes']}/{stats['total_trips']}")
        print(f"  Intent Prediction: {stats['intent_predictions']}/{stats['total_trips']}")
        print(f"  Labels Generated: {stats['labels_generated']}/{stats['total_trips']}")
        print("="*60)


# Main execution
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python trip_enhancer.py <input_file> <output_file> [use_case]")
        print("  input_file: Base trip Excel/CSV file")
        print("  output_file: Output JSON file for enhanced trips")
        print("  use_case: 'consumer' or 'fleet_management' (default: consumer)")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    use_case = sys.argv[3] if len(sys.argv) > 3 else 'consumer'
    
    # Initialize enhancer
    enhancer = TripEnhancer(
        kg_file="contracosta_kg_with_transit.ttl",
        tko_file="tko_ontology_v2.ttl",
        embeddings_file="embedding_training_data/entity_embeddings.csv",
        use_case=use_case
    )
    
    # Enhance trips
    enhanced_trips, stats = enhancer.enhance_trip_file(
        input_file=input_file,
        output_file=output_file
    )
    
    print(f"\n✓ Enhanced {len(enhanced_trips)} trips successfully")
    print(f"✓ Results saved to: {output_file}")