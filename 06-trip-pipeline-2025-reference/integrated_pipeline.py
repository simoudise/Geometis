"""
Updated Integrated Pipeline
Now includes:
1. Embedding-enhanced POI resolution
2. Transportation Planner label taxonomy
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Import all modules
from base_trip_validator import BaseTripValidator, GeofenceConfig
from embedding_enhanced_resolver import EmbeddingEnhancedPOIResolver
from route_reconstructor import RouteReconstructor
from intent_predictor import IntentPredictor
from transportation_planner_labels import TransportationPlannerLabelGenerator
from trip_enhancement_pipeline import TripEnhancementPipeline, EnhancedTrip


def setup_enhanced_pipeline(config: dict) -> TripEnhancementPipeline:
    """
    Initialize pipeline with ALL enhancements:
    - Embedding-based POI resolution
    - Transportation Planner labels
    - Full intent prediction
    """
    print("\n" + "="*70)
    print("INITIALIZING ENHANCED TRIP PIPELINE")
    print("="*70)
    
    # Check files
    kg_file = config.get('kg_file', 'contracosta_kg_with_transit.ttl')
    embeddings_file = config.get('embeddings_file', 'embedding_training_data/entity_embeddings.csv')
    tko_file = config.get('tko_file', 'tko_ontology_v2.ttl')
    
    # Validate files exist
    files_status = {
        'Knowledge Graph': (kg_file, Path(kg_file).exists()),
        'Embeddings': (embeddings_file, Path(embeddings_file).exists()),
        'TKO Ontology': (tko_file, Path(tko_file).exists())
    }
    
    print("\nFile Status:")
    for name, (path, exists) in files_status.items():
        status = "✓" if exists else "✗"
        print(f"  {status} {name}: {path}")
    
    # Initialize base pipeline
    pipeline = TripEnhancementPipeline(
        kg_file=kg_file,
        embeddings_file=embeddings_file if Path(embeddings_file).exists() else None,
        osrm_host=config.get('osrm_host', 'http://localhost:5000'),
        weather_api=config.get('weather_api', 'open-meteo'),
        config=config
    )
    
    print("\n" + "="*70)
    print("COMPONENT INITIALIZATION")
    print("="*70)
    
    # 1. POI Resolver - Use embedding-enhanced version if embeddings available
    embeddings_available = Path(embeddings_file).exists()
    
    if embeddings_available:
        try:
            print("\n[1/4] Initializing Embedding-Enhanced POI Resolver...")
            pipeline.poi_resolver = EmbeddingEnhancedPOIResolver(
                kg_file=kg_file,
                embeddings_file=embeddings_file,
                embedding_weight=config.get('embedding_weight', 0.5)
            )
            print("      ✓ Using embedding-enhanced POI resolution")
            print(f"      ✓ Embedding weight: {config.get('embedding_weight', 0.5):.1%}")
        except Exception as e:
            print(f"      ✗ Failed: {e}")
            print("      ↳ Falling back to standard POI resolver")
            from poi_resolver import POIResolver
            pipeline.poi_resolver = POIResolver(kg_file, None)
    else:
        print("\n[1/4] Initializing Standard POI Resolver...")
        print("      ⚠ No embeddings file - using spatial-only resolution")
        from poi_resolver import POIResolver
        pipeline.poi_resolver = POIResolver(kg_file, None)
    
    # 2. Route Reconstructor
    print("\n[2/4] Initializing Route Reconstructor...")
    try:
        pipeline.route_reconstructor = RouteReconstructor(
            osrm_host=config.get('osrm_host', 'http://localhost:5000'),
            kg_file=kg_file
        )
        print("      ✓ Route reconstruction ready")
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        pipeline.route_reconstructor = None
    
    # 3. Intent Predictor
    print("\n[3/4] Initializing Intent Predictor...")
    try:
        pipeline.intent_predictor = IntentPredictor(
            tko_file if Path(tko_file).exists() else None
        )
        print("      ✓ Intent prediction ready")
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        pipeline.intent_predictor = None
    
    # 4. Transportation Planner Label Generator
    print("\n[4/4] Initializing Transportation Planner Label Generator...")
    try:
        pipeline.tp_label_generator = TransportationPlannerLabelGenerator(
            kg_accessor=None  # TODO: Add KG accessor for infrastructure queries
        )
        print("      ✓ Transportation Planner labels ready")
        print("      ✓ Includes: Active mobility metrics, infrastructure scores")
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        pipeline.tp_label_generator = None
    
    print("\n" + "="*70)
    print("✓ PIPELINE INITIALIZATION COMPLETE")
    print("="*70)
    
    return pipeline


def enhance_stage5_with_tp_labels(pipeline, base_trip, stage2_data, stage3_data, use_case):
    """
    Enhanced Stage 5 that includes Transportation Planner labels
    """
    print("  Stage 5: Label Generation (Enhanced)...")
    
    # Original intent prediction
    intent_prediction = None
    if pipeline.intent_predictor:
        trip_data = {
            'origin_poi': stage2_data.get('origin_poi'),
            'destination_poi': stage2_data.get('destination_poi'),
            'start_time': base_trip.origin_timestamp,
            'end_time': base_trip.destination_timestamp,
            'modality': stage2_data.get('modality_segments', [{}])[0].get('modality', 'unknown'),
            'distance_meters': stage2_data.get('trip_distance_meters', 0),
            'duration_seconds': stage2_data.get('trip_duration_seconds', 0)
        }
        intent_prediction = pipeline.intent_predictor.predict_intent(trip_data, use_case)
    
    # Transportation Planner labels (for consumer/transportation_planning use cases)
    tp_labels = None
    if pipeline.tp_label_generator and use_case in ['consumer', 'transportation_planning']:
        print("    - Generating Transportation Planner labels...")
        tp_labels = pipeline.tp_label_generator.generate_labels(
            trip_data={},
            stage2_data=stage2_data,
            stage3_data=stage3_data,
            traveler_history=None  # TODO: Load traveler history if available
        )
        print(f"    ✓ Generated {len(tp_labels.to_dict())} label categories")
    
    # Combine all labels
    stage5_result = {
        'trip_intent': intent_prediction.to_dict() if intent_prediction else None,
        'transportation_planner_labels': tp_labels.to_dict() if tp_labels else None,
        'use_case': use_case
    }
    
    return stage5_result


# Monkey-patch the pipeline's stage 5 method
def patch_pipeline_stage5(pipeline):
    """Replace stage 5 method with enhanced version"""
    original_stage5 = pipeline._stage5_label_generation
    
    def enhanced_stage5(base_trip, stage2_data, stage3_data, use_case):
        return enhance_stage5_with_tp_labels(
            pipeline, base_trip, stage2_data, stage3_data, use_case
        )
    
    pipeline._stage5_label_generation = enhanced_stage5
    return pipeline


def save_enhanced_results(enhanced_trips: list, output_dir: str, config: dict):
    """
    Save results with enhanced labels
    """
    print("\n" + "="*70)
    print("SAVING ENHANCED RESULTS")
    print("="*70)
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save individual trips
    for trip in enhanced_trips:
        trip_file = output_path / f"{trip.trip_id}_enhanced.json"
        with open(trip_file, 'w') as f:
            # Convert to dict, handling dataclasses
            trip_dict = {}
            for key, value in trip.__dict__.items():
                if hasattr(value, '__dict__'):
                    trip_dict[key] = value.__dict__
                else:
                    trip_dict[key] = value
            json.dump(trip_dict, f, indent=2, default=str)
        print(f"  ✓ {trip_file.name}")
    
    # Enhanced summary with TP labels
    summary = {
        'processing_timestamp': datetime.now().isoformat(),
        'pipeline_version': '2.0.0-enhanced',
        'enhancements': {
            'embedding_poi_resolution': config.get('embeddings_file') is not None,
            'transportation_planner_labels': True,
            'embedding_weight': config.get('embedding_weight', 0.5)
        },
        'total_trips': len(enhanced_trips),
        'configuration': config,
        'trips_summary': []
    }
    
    for trip in enhanced_trips:
        trip_summary = {
            'trip_id': trip.trip_id,
            'traveler_id': trip.traveler_id,
            'use_case': trip.processing_metadata.get('use_case')
        }
        
        # Add TP label summary if available
        if trip.stage5_labels and trip.stage5_labels.get('transportation_planner_labels'):
            tp_labels = trip.stage5_labels['transportation_planner_labels']
            trip_summary['active_mobility'] = tp_labels.get('active_mobility', {})
            trip_summary['route_characteristics'] = tp_labels.get('route_characteristics', {})
        
        summary['trips_summary'].append(trip_summary)
    
    summary_file = output_path / "enhanced_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"  ✓ {summary_file.name}")
    
    # Human-readable report with TP labels
    report_file = output_path / "enhanced_report.txt"
    with open(report_file, 'w') as f:
        f.write("="*70 + "\n")
        f.write("ENHANCED TRIP PROCESSING REPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"Pipeline Version: 2.0.0 (Enhanced)\n")
        f.write(f"Processing Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Trips: {len(enhanced_trips)}\n\n")
        
        f.write("Enhancements:\n")
        f.write(f"  ✓ Embedding-based POI resolution: {summary['enhancements']['embedding_poi_resolution']}\n")
        f.write(f"  ✓ Transportation Planner labels: {summary['enhancements']['transportation_planner_labels']}\n")
        if summary['enhancements']['embedding_poi_resolution']:
            f.write(f"  ✓ Embedding weight: {summary['enhancements']['embedding_weight']:.1%}\n")
        f.write("\n")
        
        for i, trip in enumerate(enhanced_trips, 1):
            f.write("="*70 + "\n")
            f.write(f"TRIP {i}: {trip.trip_id}\n")
            f.write("="*70 + "\n\n")
            
            # Stage 2
            if trip.stage2_geospatial_enrichment:
                stage2 = trip.stage2_geospatial_enrichment
                f.write("Geospatial Enrichment:\n")
                f.write(f"  Distance: {stage2.get('trip_distance_meters', 0):.1f}m\n")
                f.write(f"  Duration: {stage2.get('trip_duration_seconds', 0):.1f}s\n")
                
                if stage2.get('origin_poi'):
                    origin = stage2['origin_poi']
                    f.write(f"  Origin: {origin.get('name')} (conf: {origin.get('confidence', 0):.2f})\n")
                    if origin.get('embedding_similarity'):
                        f.write(f"    └─ Embedding similarity: {origin['embedding_similarity']:.3f}\n")
                
                if stage2.get('destination_poi'):
                    dest = stage2['destination_poi']
                    f.write(f"  Destination: {dest.get('name')} (conf: {dest.get('confidence', 0):.2f})\n")
                    if dest.get('embedding_similarity'):
                        f.write(f"    └─ Embedding similarity: {dest['embedding_similarity']:.3f}\n")
                
                modality_segs = stage2.get('modality_segments', [])
                if modality_segs:
                    modalities = ', '.join(set(seg['modality'] for seg in modality_segs))
                    f.write(f"  Modalities: {modalities}\n")
                f.write("\n")
            
            # Stage 5 - Enhanced Labels
            if trip.stage5_labels:
                stage5 = trip.stage5_labels
                
                # Intent
                if stage5.get('trip_intent'):
                    intent = stage5['trip_intent']
                    if 'primary_intent' in intent:
                        pi = intent['primary_intent']
                        f.write("Predicted Intent:\n")
                        f.write(f"  {pi.get('intent_subclass', 'Unknown')}\n")
                        f.write(f"  Confidence: {pi.get('confidence', 0):.1%}\n")
                        f.write(f"  Method: {pi.get('inference_method', 'unknown')}\n\n")
                
                # Transportation Planner Labels
                if stage5.get('transportation_planner_labels'):
                    tp = stage5['transportation_planner_labels']
                    f.write("Transportation Planner Labels:\n\n")
                    
                    # Route characteristics
                    if 'route_characteristics' in tp:
                        rc = tp['route_characteristics']
                        f.write("  Route Characteristics:\n")
                        for key, value in rc.items():
                            status = "✓" if value else "✗"
                            label = key.replace('_', ' ').title()
                            f.write(f"    {status} {label}\n")
                        f.write("\n")
                    
                    # Active mobility
                    if 'active_mobility' in tp:
                        am = tp['active_mobility']
                        f.write("  Active Mobility:\n")
                        for key, value in am.items():
                            status = "✓" if value else "✗"
                            label = key.replace('_', ' ').title()
                            f.write(f"    {status} {label}\n")
                        f.write("\n")
                    
                    # Infrastructure quality
                    if 'infrastructure_quality' in tp:
                        iq = tp['infrastructure_quality']
                        f.write("  Infrastructure Quality (0=excellent, 1=poor):\n")
                        for key, value in iq.items():
                            if value is not None:
                                label = key.replace('_score', '').replace('_', ' ').title()
                                # Convert to quality rating
                                if value < 0.3:
                                    rating = "Excellent"
                                elif value < 0.5:
                                    rating = "Good"
                                elif value < 0.7:
                                    rating = "Fair"
                                else:
                                    rating = "Poor"
                                f.write(f"    {label}: {value:.2f} ({rating})\n")
                        f.write("\n")
                    
                    # Traveler patterns
                    if 'traveler_patterns' in tp:
                        tpat = tp['traveler_patterns']
                        if any(v is not None for v in tpat.values()):
                            f.write("  Traveler Patterns:\n")
                            if tpat.get('active_mobility_ratio') is not None:
                                f.write(f"    Active Mobility Ratio: {tpat['active_mobility_ratio']:.1%}\n")
                            if tpat.get('active_mobility_temporal_profile'):
                                f.write(f"    Temporal Profile: {tpat['active_mobility_temporal_profile']}\n")
            
            f.write("\n\n")
    
    print(f"  ✓ {report_file.name}")
    print(f"\n✓ All results saved to: {output_path}/")


def main():
    """Enhanced main function"""
    parser = argparse.ArgumentParser(
        description="Enhanced Trip Enhancement Pipeline with Embeddings & TP Labels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Enhanced Features:
  • Embedding-based POI resolution (semantic + spatial)
  • Transportation Planner label taxonomy
  • Active mobility metrics
  • Infrastructure quality scores
  
Examples:
  # Process with embeddings (recommended)
  python updated_integrated_pipeline.py trip_data.xlsx \\
      --embeddings embedding_training_data/entity_embeddings.csv
  
  # Process without embeddings (spatial-only)
  python updated_integrated_pipeline.py trip_data.xlsx --no-embeddings
  
  # Adjust embedding weight (default 0.5)
  python updated_integrated_pipeline.py trip_data.xlsx --embedding-weight 0.7
        """
    )
    
    parser.add_argument('excel_file', help='Excel file with base trip data')
    parser.add_argument('--kg', default='contracosta_kg_with_transit.ttl')
    parser.add_argument('--embeddings', default='embedding_training_data/entity_embeddings.csv')
    parser.add_argument('--no-embeddings', action='store_true', 
                       help='Disable embedding-based resolution')
    parser.add_argument('--embedding-weight', type=float, default=0.5,
                       help='Weight for embeddings (0-1, default 0.5)')
    parser.add_argument('--tko', default='tko_ontology_v2.ttl')
    parser.add_argument('--osrm', default='http://localhost:5000')
    parser.add_argument('--use-case', default='consumer',
                       choices=['consumer', 'fleet_management', 'transportation_planning'])
    parser.add_argument('--output', default='output')
    parser.add_argument('--geofence', nargs=4, type=float)
    parser.add_argument('--validate-only', action='store_true')
    
    args = parser.parse_args()
    
    # Build config
    config = {
        'kg_file': args.kg,
        'embeddings_file': None if args.no_embeddings else args.embeddings,
        'embedding_weight': args.embedding_weight,
        'tko_file': args.tko,
        'osrm_host': args.osrm,
        'use_case': args.use_case,
        'output_dir': args.output,
        'geofence': {
            'name': 'Custom' if args.geofence else 'Contra Costa County',
            'bounds': args.geofence or [37.88, 38.10, -122.35, -121.70]
        }
    }
    
    print("\n" + "="*70)
    print("ENHANCED TRIP PIPELINE v2.0")
    print("="*70)
    print(f"Input: {args.excel_file}")
    print(f"Use case: {config['use_case']}")
    print(f"Embeddings: {'Enabled' if not args.no_embeddings else 'Disabled'}")
    if not args.no_embeddings:
        print(f"Embedding weight: {config['embedding_weight']:.1%}")
    print("="*70)
    
    # Validate
    from base_trip_validator import BaseTripValidator, GeofenceConfig
    geofence = GeofenceConfig(name=config['geofence']['name'], 
                              bounds=config['geofence']['bounds'])
    validator = BaseTripValidator(geofence=geofence)
    validated_df, validation_result = validator.validate_excel_file(args.excel_file, auto_fix=True)
    
    if not validation_result.is_valid:
        print("\n❌ Validation failed")
        sys.exit(1)
    
    if args.validate_only:
        print("\n✓ Validation complete")
        sys.exit(0)
    
    # Setup enhanced pipeline
    pipeline = setup_enhanced_pipeline(config)
    pipeline = patch_pipeline_stage5(pipeline)
    
    # Process trips
    try:
        enhanced_trips = pipeline.process_excel_file(args.excel_file, use_case=config['use_case'])
    except Exception as e:
        print(f"\n❌ Enhancement failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Save results
    save_enhanced_results(enhanced_trips, config['output_dir'], config)
    
    print("\n" + "="*70)
    print("✓ ENHANCED PIPELINE COMPLETE!")
    print("="*70)
    print(f"Processed {len(enhanced_trips)} trips")
    print(f"Results: {config['output_dir']}/")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()