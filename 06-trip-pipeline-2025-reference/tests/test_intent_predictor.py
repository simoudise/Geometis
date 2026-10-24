"""
Test script for Intent Predictor
Tests intent prediction with various trip scenarios
"""

import sys
from datetime import datetime
from intent_predictor import IntentPredictor
from POI_resolver import POIResolver
import pandas as pd


def test_intent_with_real_trip(trip_file: str, kg_file: str, tko_file: str = None):
    """Test intent prediction with actual trip data"""
    
    print("="*80)
    print("TEST 4: INTENT PREDICTION WITH REAL TRIP DATA")
    print("="*80)
    
    # Load trip data
    print(f"\n1. Loading trip data from {trip_file}...")
    if trip_file.endswith('.xlsx'):
        df = pd.read_excel(trip_file)
    else:
        df = pd.read_csv(trip_file)
    
    print(f"   ✓ Loaded {len(df)} segments")
    
    # Initialize modules
    print(f"\n2. Initializing POI resolver and intent predictor...")
    resolver = POIResolver(kg_file)
    predictor = IntentPredictor(tko_file)
    
    # Get trip endpoints
    first_seg = df.iloc[0]
    last_seg = df.iloc[-1]
    
    print(f"\n3. Resolving trip POIs...")
    print(f"   Origin: ({first_seg['origin_lat']:.6f}, {first_seg['origin_long']:.6f})")
    print(f"   Destination: ({last_seg['destination_lat']:.6f}, {last_seg['destination_long']:.6f})")
    
    origin_candidates, dest_candidates = resolver.resolve_trip_endpoints(
        first_seg['origin_lat'],
        first_seg['origin_long'],
        last_seg['destination_lat'],
        last_seg['destination_long']
    )
    
    # Calculate trip statistics
    total_duration = (pd.to_datetime(last_seg['end_timestamp']) - 
                     pd.to_datetime(first_seg['start_timestamp'])).total_seconds()
    
    # Estimate distance (crow-flies for now)
    from math import radians, sin, cos, sqrt, atan2
    R = 6371000
    lat1, lon1 = radians(first_seg['origin_lat']), radians(first_seg['origin_long'])
    lat2, lon2 = radians(last_seg['destination_lat']), radians(last_seg['destination_long'])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c
    
    # Create trip data for intent prediction
    trip_data = {
        'origin_poi': origin_candidates[0].to_dict() if origin_candidates else {},
        'destination_poi': dest_candidates[0].to_dict() if dest_candidates else {},
        'start_time': pd.to_datetime(first_seg['start_timestamp']),
        'end_time': pd.to_datetime(last_seg['end_timestamp']),
        'modality': 'walking',  # From the file name "monomodal"
        'distance_meters': distance,
        'duration_seconds': total_duration,
        'dwell_time': 0  # No intermediate stops in this example
    }
    
    print(f"\n4. Trip Summary:")
    print(f"   Start time: {trip_data['start_time'].strftime('%A, %B %d, %Y at %I:%M %p')}")
    print(f"   Duration: {total_duration/60:.1f} minutes")
    print(f"   Distance: {distance:.0f} meters ({distance/1000:.2f} km)")
    print(f"   Modality: {trip_data['modality']}")
    
    if origin_candidates:
        print(f"\n   Origin POI: {origin_candidates[0].name}")
        print(f"     Type: {origin_candidates[0].poi_type.split(':')[-1]}")
        print(f"     Confidence: {origin_candidates[0].confidence:.2f}")
    
    if dest_candidates:
        print(f"\n   Destination POI: {dest_candidates[0].name}")
        print(f"     Type: {dest_candidates[0].poi_type.split(':')[-1]}")
        print(f"     Confidence: {dest_candidates[0].confidence:.2f}")
    
    # Predict intent
    print(f"\n5. Predicting trip intent...")
    prediction = predictor.predict_intent(trip_data, use_case='consumer')
    
    print(f"\n" + "="*80)
    print("INTENT PREDICTION RESULTS")
    print("="*80)
    print(predictor.explain_prediction(prediction))
    
    return prediction


def test_synthetic_scenarios(tko_file: str = None):
    """Test intent prediction with synthetic scenarios"""
    
    print("\n" + "="*80)
    print("TEST 4B: SYNTHETIC SCENARIO TESTING")
    print("="*80)
    
    predictor = IntentPredictor(tko_file)
    
    scenarios = [
        {
            'name': 'Morning Commute (Weekday)',
            'trip': {
                'origin_poi': {
                    'name': 'Residential Building',
                    'type': 'urn:urban-kg:ResidentialBuilding'
                },
                'destination_poi': {
                    'name': 'Tech Office Campus',
                    'type': 'urn:urban-kg:OfficeBuilding'
                },
                'start_time': datetime(2025, 1, 15, 8, 0),  # Wednesday 8am
                'end_time': datetime(2025, 1, 15, 8, 30),
                'modality': 'driving',
                'distance_meters': 15000,
                'duration_seconds': 1800
            }
        },
        {
            'name': 'Evening Commute (Weekday)',
            'trip': {
                'origin_poi': {
                    'name': 'Tech Office Campus',
                    'type': 'urn:urban-kg:OfficeBuilding'
                },
                'destination_poi': {
                    'name': 'Residential Building',
                    'type': 'urn:urban-kg:ResidentialBuilding'
                },
                'start_time': datetime(2025, 1, 15, 17, 30),  # Wednesday 5:30pm
                'end_time': datetime(2025, 1, 15, 18, 0),
                'modality': 'driving',
                'distance_meters': 15000,
                'duration_seconds': 1800
            }
        },
        {
            'name': 'Weekend Grocery Shopping',
            'trip': {
                'origin_poi': {
                    'name': 'Home',
                    'type': 'urn:urban-kg:House'
                },
                'destination_poi': {
                    'name': 'Safeway',
                    'type': 'urn:urban-kg:Supermarket'
                },
                'start_time': datetime(2025, 1, 18, 15, 0),  # Saturday 3pm
                'end_time': datetime(2025, 1, 18, 15, 45),
                'modality': 'driving',
                'distance_meters': 3000,
                'duration_seconds': 2700,
                'dwell_time': 1800  # 30 minutes
            }
        },
        {
            'name': 'Doctor Visit (Weekday Afternoon)',
            'trip': {
                'origin_poi': {
                    'name': 'Workplace',
                    'type': 'urn:urban-kg:OfficeBuilding'
                },
                'destination_poi': {
                    'name': 'Medical Center',
                    'type': 'urn:urban-kg:DoctorsOffice'
                },
                'start_time': datetime(2025, 1, 16, 14, 0),  # Thursday 2pm
                'end_time': datetime(2025, 1, 16, 14, 20),
                'modality': 'driving',
                'distance_meters': 5000,
                'duration_seconds': 1200,
                'dwell_time': 2400  # 40 minutes
            }
        },
        {
            'name': 'Gym Visit (Evening)',
            'trip': {
                'origin_poi': {
                    'name': 'Home',
                    'type': 'urn:urban-kg:House'
                },
                'destination_poi': {
                    'name': '24 Hour Fitness',
                    'type': 'urn:urban-kg:Gym'
                },
                'start_time': datetime(2025, 1, 15, 18, 30),  # Wednesday 6:30pm
                'end_time': datetime(2025, 1, 15, 18, 45),
                'modality': 'driving',
                'distance_meters': 2500,
                'duration_seconds': 900,
                'dwell_time': 3600  # 1 hour
            }
        },
        {
            'name': 'School Drop-off (Morning)',
            'trip': {
                'origin_poi': {
                    'name': 'Home',
                    'type': 'urn:urban-kg:House'
                },
                'destination_poi': {
                    'name': 'Elementary School',
                    'type': 'urn:urban-kg:School'
                },
                'start_time': datetime(2025, 1, 17, 7, 45),  # Friday 7:45am
                'end_time': datetime(2025, 1, 17, 7, 55),
                'modality': 'driving',
                'distance_meters': 1500,
                'duration_seconds': 600
            }
        },
        {
            'name': 'Restaurant Dinner (Weekend Evening)',
            'trip': {
                'origin_poi': {
                    'name': 'Home',
                    'type': 'urn:urban-kg:House'
                },
                'destination_poi': {
                    'name': 'Italian Restaurant',
                    'type': 'urn:urban-kg:Restaurant'
                },
                'start_time': datetime(2025, 1, 18, 19, 0),  # Saturday 7pm
                'end_time': datetime(2025, 1, 18, 19, 15),
                'modality': 'driving',
                'distance_meters': 4000,
                'duration_seconds': 900,
                'dwell_time': 5400  # 90 minutes
            }
        },
        {
            'name': 'Park Visit (Weekend Afternoon)',
            'trip': {
                'origin_poi': {
                    'name': 'Home',
                    'type': 'urn:urban-kg:House'
                },
                'destination_poi': {
                    'name': 'Central Park',
                    'type': 'urn:urban-kg:Park'
                },
                'start_time': datetime(2025, 1, 19, 14, 0),  # Sunday 2pm
                'end_time': datetime(2025, 1, 19, 14, 10),
                'modality': 'walking',
                'distance_meters': 800,
                'duration_seconds': 600,
                'dwell_time': 7200  # 2 hours
            }
        }
    ]
    
    # Test each scenario
    results = []
    
    for scenario in scenarios:
        print(f"\n{'='*80}")
        print(f"Scenario: {scenario['name']}")
        print('='*80)
        
        trip = scenario['trip']
        
        print(f"\nTrip Details:")
        print(f"  Origin: {trip['origin_poi']['name']} ({trip['origin_poi']['type'].split(':')[-1]})")
        print(f"  Destination: {trip['destination_poi']['name']} ({trip['destination_poi']['type'].split(':')[-1]})")
        print(f"  Time: {trip['start_time'].strftime('%A, %B %d at %I:%M %p')}")
        print(f"  Modality: {trip['modality']}")
        print(f"  Distance: {trip['distance_meters']/1000:.1f} km")
        if trip.get('dwell_time'):
            print(f"  Dwell time: {trip['dwell_time']/60:.0f} minutes")
        
        # Predict intent
        prediction = predictor.predict_intent(trip, use_case='consumer')
        
        print(f"\n{predictor.explain_prediction(prediction)}")
        
        results.append({
            'scenario': scenario['name'],
            'predicted_intent': prediction.intent_subclass,
            'confidence': prediction.confidence,
            'method': prediction.inference_method
        })
    
    # Summary table
    print("\n" + "="*80)
    print("SUMMARY OF ALL SCENARIOS")
    print("="*80)
    print(f"\n{'Scenario':<40} {'Intent':<25} {'Confidence':<12} {'Method'}")
    print("-"*80)
    
    for result in results:
        conf_str = f"{result['confidence']:.1%}"
        print(f"{result['scenario']:<40} {result['predicted_intent']:<25} {conf_str:<12} {result['method']}")
    
    print("\n" + "="*80)


def test_pattern_analysis(tko_file: str = None):
    """Test pattern analysis across multiple trips"""
    
    print("\n" + "="*80)
    print("TEST 4C: TRIP PATTERN ANALYSIS")
    print("="*80)
    
    predictor = IntentPredictor(tko_file)
    
    # Simulate a week of trips for a commuter
    trips = []
    
    # Monday-Friday: Commute to work
    for day in range(5):  # Weekdays
        trips.append({
            'origin_poi': {'name': 'Home', 'type': 'urn:urban-kg:House'},
            'destination_poi': {'name': 'Office', 'type': 'urn:urban-kg:OfficeBuilding'},
            'start_time': datetime(2025, 1, 13 + day, 8, 0),
            'modality': 'driving',
            'distance_meters': 15000,
            'duration_seconds': 1800
        })
        
        # Commute back
        trips.append({
            'origin_poi': {'name': 'Office', 'type': 'urn:urban-kg:OfficeBuilding'},
            'destination_poi': {'name': 'Home', 'type': 'urn:urban-kg:House'},
            'start_time': datetime(2025, 1, 13 + day, 17, 30),
            'modality': 'driving',
            'distance_meters': 15000,
            'duration_seconds': 1800
        })
    
    # Wednesday: Gym after work
    trips.append({
        'origin_poi': {'name': 'Office', 'type': 'urn:urban-kg:OfficeBuilding'},
        'destination_poi': {'name': 'Gym', 'type': 'urn:urban-kg:Gym'},
        'start_time': datetime(2025, 1, 15, 17, 30),
        'modality': 'driving',
        'distance_meters': 3000,
        'duration_seconds': 900
    })
    
    # Saturday: Grocery shopping
    trips.append({
        'origin_poi': {'name': 'Home', 'type': 'urn:urban-kg:House'},
        'destination_poi': {'name': 'Safeway', 'type': 'urn:urban-kg:Supermarket'},
        'start_time': datetime(2025, 1, 18, 15, 0),
        'modality': 'driving',
        'distance_meters': 3000,
        'duration_seconds': 900,
        'dwell_time': 1800
    })
    
    # Sunday: Park visit
    trips.append({
        'origin_poi': {'name': 'Home', 'type': 'urn:urban-kg:House'},
        'destination_poi': {'name': 'Park', 'type': 'urn:urban-kg:Park'},
        'start_time': datetime(2025, 1, 19, 14, 0),
        'modality': 'walking',
        'distance_meters': 800,
        'duration_seconds': 600
    })
    
    print(f"\nAnalyzing {len(trips)} trips over one week...\n")
    
    # Analyze patterns
    patterns = predictor.analyze_trip_pattern(trips)
    
    print("Recurring Intents:")
    for intent, count in sorted(patterns['recurring_intents'].items(), 
                                key=lambda x: x[1], reverse=True):
        intent_name = intent.split(':')[-1]
        percentage = (count / len(trips)) * 100
        print(f"  {intent_name:<25} {count:>3} trips ({percentage:.1f}%)")
    
    print("\nTime of Day Distribution:")
    for time_cat, count in sorted(patterns['time_of_day_distribution'].items(), 
                                  key=lambda x: x[1], reverse=True):
        percentage = (count / len(trips)) * 100
        print(f"  {time_cat:<20} {count:>3} trips ({percentage:.1f}%)")
    
    print("\nDay of Week Distribution:")
    for day, count in patterns['day_of_week_distribution'].items():
        percentage = (count / len(trips)) * 100
        print(f"  {day:<10} {count:>3} trips ({percentage:.1f}%)")
    
    print("\nModality Distribution:")
    for modality, count in patterns['modality_distribution'].items():
        percentage = (count / len(trips)) * 100
        print(f"  {modality:<15} {count:>3} trips ({percentage:.1f}%)")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_intent_predictor.py <trip_file> <kg_file> [tko_file]")
        print("\nExample:")
        print("  python test_intent_predictor.py \\")
        print("    'Monomodal base trip 1 records.xlsx' \\")
        print("    'contracosta_kg_with_transit.ttl' \\")
        print("    'tko_ontology_v2.ttl'")
        sys.exit(1)
    
    trip_file = sys.argv[1]
    kg_file = sys.argv[2]
    tko_file = sys.argv[3] if len(sys.argv) > 3 else None
    
    print("\n" + "="*80)
    print("INTENT PREDICTOR COMPREHENSIVE TEST SUITE")
    print("="*80)
    
    # Test A: Real trip data
    real_trip_prediction = test_intent_with_real_trip(trip_file, kg_file, tko_file)
    
    # Test B: Synthetic scenarios
    test_synthetic_scenarios(tko_file)
    
    # Test C: Pattern analysis
    test_pattern_analysis(tko_file)
    
    print("\n" + "="*80)
    print("✓ ALL INTENT PREDICTION TESTS COMPLETE")
    print("="*80)