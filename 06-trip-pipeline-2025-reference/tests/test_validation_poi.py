"""
Test script to validate both base_trip_validator and POI_resolver
"""

import sys
from base_trip_validator import BaseTripValidator
from POI_resolver import POIResolver

def test_validation(trip_file: str):
    """Test trip validation with geographic checks"""
    print("="*60)
    print("STEP 1: VALIDATING BASE TRIP DATA")
    print("="*60)
    
    validator = BaseTripValidator(strict_mode=False)
    valid_trips, results = validator.validate_trip_file(trip_file)
    
    # Show detailed results for first trip
    if results:
        first_result = results[0]
        print(f"\nDetailed validation for first trip:")
        print(f"  Valid: {first_result.is_valid}")
        print(f"  Errors: {len(first_result.errors)}")
        print(f"  Warnings: {len(first_result.warnings)}")
        
        if first_result.errors:
            print(f"\n  Errors:")
            for error in first_result.errors:
                print(f"    - {error}")
        
        if first_result.warnings:
            print(f"\n  Warnings:")
            for warning in first_result.warnings:
                print(f"    - {warning}")
    
    return valid_trips, results


def test_poi_resolution(kg_file: str, embeddings_file: str = None):
    """Test POI resolver"""
    print("\n" + "="*60)
    print("STEP 2: TESTING POI RESOLVER")
    print("="*60)
    
    resolver = POIResolver(kg_file, embeddings_file)
    
    # Test locations from the trip
    test_cases = [
        (37.988989, -121.803045, "Trip Origin"),
        (37.982589, -121.805582, "Trip Destination"),
        (37.9101, -122.0652, "Downtown Walnut Creek"),
        (37.9298, -122.0574, "Pleasant Hill BART")
    ]
    
    for lat, lon, description in test_cases:
        print(f"\n--- {description} ---")
        print(f"Coordinates: ({lat:.6f}, {lon:.6f})")
        
        candidates = resolver.resolve_location(
            lat, lon,
            max_candidates=3,
            min_confidence=0.10,
            debug=False
        )
        
        if candidates:
            print(f"Found {len(candidates)} candidates:")
            for i, c in enumerate(candidates, 1):
                print(f"  {i}. {c.name}")
                print(f"     Type: {c.poi_type.split(':')[-1]}")
                print(f"     Distance: {c.distance_meters:.1f}m")
                print(f"     Confidence: {c.confidence:.3f}")
        else:
            print("No candidates found")


def test_integrated(trip_file: str, kg_file: str, embeddings_file: str = None):
    """Test both modules together"""
    print("\n" + "="*60)
    print("INTEGRATED TEST: VALIDATION + POI RESOLUTION")
    print("="*60)
    
    # Step 1: Validate
    validator = BaseTripValidator(strict_mode=False)
    valid_trips, results = validator.validate_trip_file(trip_file)
    
    if len(valid_trips) == 0:
        print("⚠ No valid trips to process")
        return
    
    # Step 2: Resolve POIs for first valid trip
    resolver = POIResolver(kg_file, embeddings_file)
    
    # Get the COMPLETE trip (all segments) not just first segment
    trip_segments = valid_trips
    
    # Use FIRST segment's origin and LAST segment's destination
    first_segment = trip_segments.iloc[0]
    last_segment = trip_segments.iloc[-1]
    
    print(f"\nResolving POIs for complete trip:")
    print(f"  Trip has {len(trip_segments)} segments")
    print(f"  Origin (first segment): ({first_segment['origin_lat']:.6f}, {first_segment['origin_long']:.6f})")
    print(f"  Destination (last segment): ({last_segment['destination_lat']:.6f}, {last_segment['destination_long']:.6f})")
    
    origin_candidates, dest_candidates = resolver.resolve_trip_endpoints(
        first_segment['origin_lat'],
        first_segment['origin_long'],
        last_segment['destination_lat'],
        last_segment['destination_long']
    )
    
    print(f"\n✓ Complete!")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_validation_poi.py <trip_file> <kg_file> [embeddings_file]")
        print("\nExample:")
        print("  python test_validation_poi.py \\")
        print("    'Monomodal base trip 1 records.xlsx' \\")
        print("    'contracosta_kg_with_transit.ttl' \\")
        print("    'embedding_training_data/entity_embeddings.csv'")
        sys.exit(1)
    
    trip_file = sys.argv[1]
    kg_file = sys.argv[2]
    embeddings_file = sys.argv[3] if len(sys.argv) > 3 else None
    
    # Run all tests
    print("RUNNING COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    # Test 1: Validation only
    valid_trips, results = test_validation(trip_file)
    
    # Test 2: POI resolution only
    test_poi_resolution(kg_file, embeddings_file)
    
    # Test 3: Integrated
    test_integrated(trip_file, kg_file, embeddings_file)
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETE")
    print("="*60)