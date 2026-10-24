#################################################################
#
#    Purpose: Generate the knowledge graph based on the UKO ontology
#    for five Contra Costa County cities using OSM data.
#    
#    VERSION 2.0: Enhanced with:
#    - Vulnerable population analysis
#    - Safety infrastructure relationships
#    - Cycling distance relationships
#    - Optional LLM-based neighborhood/district discovery
#
#    Synapse Partners, LLC 
#################################################################

import argparse
import os
import sys
import json
import time
from datetime import datetime
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS, OWL, XSD

# Import utilities
from utils import get_city_bounding_box, download_pbf, validate_bounding_boxes

# Import v2 OSM handler (with new relationship types)
try:
    from osm_handler_v2 import EnhancedOSMHandler
    print("✓ Using osm_handler_v2 with enhanced relationship types")
except ImportError:
    from osm_handler import EnhancedOSMHandler
    print("⚠ Falling back to osm_handler (v1)")

# Optional: Import LLM area discovery
try:
    from multi_llm_area_discovery_fixed import enhance_kg_with_areas, MultiLLMAreaDiscovery
    LLM_DISCOVERY_AVAILABLE = True
except ImportError:
    LLM_DISCOVERY_AVAILABLE = False
    print("Note: LLM area discovery not available (multi_llm_area_discovery_fixed.py not found)")

# Optional: Import Census tract loader (fast version - appends without loading full graph)
try:
    from census_tract_loader_fast import main as load_census_tracts
    CENSUS_LOADER_AVAILABLE = True
except ImportError:
    CENSUS_LOADER_AVAILABLE = False

# Optional: Import Overture POI loader (fast version - appends without loading full graph)
try:
    from overture_poi_loader_fast import main as load_overture_pois
    OVERTURE_LOADER_AVAILABLE = True
except ImportError:
    OVERTURE_LOADER_AVAILABLE = False

# Optional: Import SWITRS safety data loader (fast version - appends without loading full graph)
try:
    from switrs_safety_loader import main as load_switrs_safety
    SAFETY_LOADER_AVAILABLE = True
except ImportError:
    SAFETY_LOADER_AVAILABLE = False

# Define namespaces
UKO = Namespace("urn:urban-kg:")

# Define the target cities for the knowledge graph
TARGET_CITIES = [
    {"city": "Antioch", "state": "CA"},
    {"city": "Pittsburg", "state": "CA"},
    {"city": "Walnut Creek", "state": "CA"},
    {"city": "Pleasant Hill", "state": "CA"},
    {"city": "Richmond", "state": "CA"}
]

# Use Northern California extract instead of entire state for better performance
PBF_URL = "https://download.geofabrik.de/north-america/us/california/norcal-latest.osm.pbf"

# Ontology files in order of priority
ONTOLOGY_FILES = [
    "uko_ontology_v7.ttl",       # Latest combined version
    "uko_ontology_v6.1.ttl",     # Previous version
    "uko_ontology_v6.ttl",
    "uko_ontology_v5.1.ttl",
    "uko_ontology_v5.ttl",
]

# Extension ontologies to load
EXTENSION_ONTOLOGIES = [
    "uko_districts_neighborhoods_extension.ttl",
    "uko_safety_extension.ttl",
    "uko_adas_extension.ttl",
    "uko_census_extension.ttl",
    "uko_collision_extension.ttl",
]


class CheckpointManager:
    """Manages checkpoints for resumable processing."""
    
    def __init__(self, checkpoint_file: str):
        self.checkpoint_file = checkpoint_file
        self.checkpoint_data = self._load_checkpoint()
    
    def _load_checkpoint(self) -> dict:
        """Load existing checkpoint or create new one."""
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load checkpoint file: {e}")
        
        return {'completed_phases': [], 'start_time': datetime.now().isoformat()}
    
    def save_checkpoint(self):
        """Save current checkpoint state."""
        self.checkpoint_data['last_update'] = datetime.now().isoformat()
        try:
            with open(self.checkpoint_file, 'w') as f:
                json.dump(self.checkpoint_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save checkpoint: {e}")
    
    def mark_phase_complete(self, phase_name: str):
        """Mark a processing phase as complete."""
        if phase_name not in self.checkpoint_data['completed_phases']:
            self.checkpoint_data['completed_phases'].append(phase_name)
            self.save_checkpoint()
    
    def is_phase_complete(self, phase_name: str) -> bool:
        """Check if a phase has been completed."""
        return phase_name in self.checkpoint_data['completed_phases']
    
    def reset(self):
        """Reset checkpoint to start fresh."""
        self.checkpoint_data = {'completed_phases': [], 'start_time': datetime.now().isoformat()}
        self.save_checkpoint()


def debug_bounding_box(combined_bbox: list):
    """Debug function to analyze the bounding box."""
    print("\n" + "="*60)
    print("BOUNDING BOX ANALYSIS")
    print("="*60)
    lat_min, lat_max, lon_min, lon_max = combined_bbox
    print(f"Combined bounding box: {combined_bbox}")
    lat_span_km = (lat_max - lat_min) * 111
    lon_span_km = (lon_max - lon_min) * 111 * 0.8
    area_km2 = lat_span_km * lon_span_km
    print(f"Approximate coverage: {lat_span_km:.1f} km × {lon_span_km:.1f} km = {area_km2:.1f} km²")
    print("="*60)


def load_ontologies(graph: Graph) -> bool:
    """
    Load the UKO ontology and extensions.
    
    Tries multiple ontology versions in order of preference.
    Also loads extension ontologies if available.
    """
    print("\n" + "="*60)
    print("LOADING ONTOLOGIES")
    print("="*60)
    
    # Load main ontology
    main_loaded = False
    for ontology_file in ONTOLOGY_FILES:
        if os.path.exists(ontology_file):
            try:
                graph.parse(ontology_file, format="turtle")
                print(f"✓ Loaded main ontology: {ontology_file}")
                main_loaded = True
                break
            except Exception as e:
                print(f"  Warning: Could not load {ontology_file}: {e}")
    
    if not main_loaded:
        print("ERROR: No main ontology file found!")
        print(f"  Looked for: {ONTOLOGY_FILES}")
        return False
    
    # Load extension ontologies
    extensions_loaded = 0
    for ext_file in EXTENSION_ONTOLOGIES:
        if os.path.exists(ext_file):
            try:
                graph.parse(ext_file, format="turtle")
                print(f"✓ Loaded extension: {ext_file}")
                extensions_loaded += 1
            except Exception as e:
                print(f"  Warning: Could not load extension {ext_file}: {e}")
    
    # Print statistics
    class_count = len(list(graph.subjects(RDF.type, OWL.Class)))
    obj_prop_count = len(list(graph.subjects(RDF.type, OWL.ObjectProperty)))
    data_prop_count = len(list(graph.subjects(RDF.type, OWL.DatatypeProperty)))
    
    print(f"\nOntology Statistics:")
    print(f"  Classes: {class_count}")
    print(f"  Object Properties: {obj_prop_count}")
    print(f"  Datatype Properties: {data_prop_count}")
    print(f"  Extensions loaded: {extensions_loaded}")
    
    return True


def print_graph_statistics(graph: Graph, title: str = "KNOWLEDGE GRAPH STATISTICS"):
    """Print detailed statistics about the knowledge graph."""
    print("\n" + "="*60)
    print(title)
    print("="*60)
    
    print(f"Total RDF triples: {len(graph):,}")
    
    # Count entities by namespace
    osm_entities = len(list(graph.subjects(predicate=RDF.type, object=None)))
    
    # Count key relationship types
    relationship_counts = {}
    key_relations = [
        ('adjacentTo', UKO.adjacentTo),
        ('near', UKO.near),
        ('withinWalkingDistanceOf', UKO.withinWalkingDistanceOf),
        ('withinCyclingDistanceOf', UKO.withinCyclingDistanceOf),
        ('accessibleVia', UKO.accessibleVia),
        ('transitAccessible', UKO.transitAccessible),
        ('partOf', UKO.partOf),
        ('hasSidewalk', UKO.hasSidewalk),
        ('hasBikeLane', UKO.hasBikeLane),
        ('nearVulnerablePopulation', UKO.nearVulnerablePopulation),
        ('servesVulnerablePopulation', UKO.servesVulnerablePopulation),
        ('hasCrossing', UKO.hasCrossing),
        ('hasTrafficCalming', UKO.hasTrafficCalming),
        ('hasTrafficSignal', UKO.hasTrafficSignal),
    ]
    
    print("\nRelationship Counts:")
    for name, predicate in key_relations:
        count = len(list(graph.triples((None, predicate, None))))
        if count > 0:
            relationship_counts[name] = count
            print(f"  {name}: {count:,}")
    
    # Count key entity types
    print("\nKey Entity Types:")
    entity_types = [
        ('Cities', UKO.City),
        ('Neighborhoods', UKO.Neighborhood),
        ('Districts', UKO.District),
        ('Roads', UKO.Road),
        ('Schools', UKO.School),
        ('Hospitals', UKO.Hospital),
        ('Parks', UKO.Park),
        ('Bus Stops', UKO.BusStop),
        ('Nursing Homes', UKO.NursingHome),
        ('Senior Centers', UKO.SeniorCenter),
    ]
    
    for name, rdf_type in entity_types:
        count = len(list(graph.subjects(RDF.type, rdf_type)))
        if count > 0:
            print(f"  {name}: {count:,}")
    
    print("="*60)


def create_knowledge_graph(
    output_file: str, 
    data_dir: str, 
    force_download: bool,
    checkpoint_file: str = "kg_checkpoint.json",
    debug_mode: bool = True,
    run_llm_discovery: bool = False,
    output_format: str = "turtle"
):
    """
    Main function to generate the knowledge graph.
    
    Args:
        output_file: Output file path for the knowledge graph
        data_dir: Directory for data files (PBF downloads, etc.)
        force_download: Force re-download of PBF file
        checkpoint_file: File to track processing progress
        debug_mode: Enable verbose output
        run_llm_discovery: Run LLM-based neighborhood/district discovery
        output_format: Output format ('turtle' or 'nt' for N-Triples)
    """
    checkpoint_manager = CheckpointManager(checkpoint_file)
    
    print("=" * 80)
    print("URBAN KNOWLEDGE GRAPH BUILDER v2.0")
    print("=" * 80)
    print(f"Debug mode: {'ENABLED' if debug_mode else 'DISABLED'}")
    print(f"LLM Discovery: {'ENABLED' if run_llm_discovery else 'DISABLED'}")
    print(f"Output format: {output_format}")
    print("=" * 80)
    
    # =========================================================================
    # PHASE 1: Download PBF
    # =========================================================================
    if not checkpoint_manager.is_phase_complete("pbf_download") or force_download:
        pbf_filepath = download_pbf(PBF_URL, data_dir, force=force_download)
        if not pbf_filepath:
            sys.exit(1)
        checkpoint_manager.mark_phase_complete("pbf_download")
    else:
        print("✓ PBF download already completed (according to checkpoint)")
        pbf_filepath = os.path.join(data_dir, PBF_URL.split('/')[-1])
        if not os.path.exists(pbf_filepath):
            print(f"WARNING: File not found at '{pbf_filepath}'. Forcing re-download.")
            pbf_filepath = download_pbf(PBF_URL, data_dir, force=True)
            if not pbf_filepath:
                sys.exit(1)

    # =========================================================================
    # PHASE 2: Initialize RDF Graph
    # =========================================================================
    print("\n" + "="*60)
    print("INITIALIZING RDF GRAPH")
    print("="*60)
    
    g = Graph()
    g.bind("uko", UKO)
    g.bind("uko_entity", Namespace("urn:urban-kg:entity/osm/"))
    g.bind("geo", Namespace("http://www.opengis.net/ont/geosparql#"))
    
    if not load_ontologies(g):
        print("ERROR: Failed to load ontology. Aborting.")
        sys.exit(1)

    # =========================================================================
    # PHASE 3: Create Bounding Box
    # =========================================================================
    if not checkpoint_manager.is_phase_complete("bbox_creation"):
        print("\n" + "="*60)
        print("CREATING GEOGRAPHIC BOUNDING BOX")
        print("="*60)
        
        all_bboxes = []
        for t in TARGET_CITIES:
            bbox = get_city_bounding_box(t["city"], t["state"])
            if bbox:
                all_bboxes.append(bbox)
        
        if not all_bboxes:
            print("No valid bounding boxes found. Aborting.")
            sys.exit(1)
        
        # Validate bounding boxes
        validate_bounding_boxes(all_bboxes)
        
        lat_mins, lat_maxs, lon_mins, lon_maxs = zip(*all_bboxes)
        combined_bbox = [min(lat_mins), max(lat_maxs), min(lon_mins), max(lon_maxs)]
        
        checkpoint_manager.checkpoint_data['combined_bbox'] = combined_bbox
        checkpoint_manager.mark_phase_complete("bbox_creation")
    else:
        print("✓ Bounding box already created")
        combined_bbox = checkpoint_manager.checkpoint_data.get('combined_bbox')
        if not combined_bbox:
            print("Error loading bbox from checkpoint. Aborting.")
            sys.exit(1)
    
    if debug_mode:
        debug_bounding_box(combined_bbox)

    # Prepare city geofences
    print("Preparing individual city geofences...")
    city_geofences = {}
    for t in TARGET_CITIES:
        bbox = get_city_bounding_box(t["city"], t["state"])
        if bbox:
            city_geofences[t["city"]] = bbox

    # =========================================================================
    # PHASE 4: Process OSM data
    # =========================================================================
    print("\n" + "="*60)
    print("PHASE 4: OSM DATA PROCESSING")
    print("="*60)
    
    handler = EnhancedOSMHandler(
        graph=g, 
        bounding_box=combined_bbox,
        city_geofences=city_geofences,
        debug_mode=debug_mode
    )
    
    if not checkpoint_manager.is_phase_complete("osm_processing"):
        print("Processing OSM entities...")
        start_time = time.time()
        
        handler.apply_file(pbf_filepath, locations=True, idx='dense_file_array')
        
        processing_time = time.time() - start_time
        
        print(f"\n--- OSM Processing Complete ---")
        print(f"Processing time: {processing_time:.2f} seconds ({processing_time/60:.1f} minutes)")
        print(f"Nodes processed: {handler.node_count:,}")
        print(f"Ways processed: {handler.way_count:,}")
        print(f"Areas processed: {handler.area_count:,}")
        print(f"Entities stored: {handler.stored_entity_count:,}")
        
        checkpoint_manager.mark_phase_complete("osm_processing")
    else:
        print("✓ OSM processing already completed")

    # =========================================================================
    # PHASE 5: Finalize (spatial relationships)
    # =========================================================================
    if not checkpoint_manager.is_phase_complete("finalization"):
        print("\n" + "="*60)
        print("PHASE 5: FINALIZING RELATIONSHIPS")
        print("="*60)
        
        complex_entities = handler.finalize()
        print(f"✓ Created {len(complex_entities)} complex entities")
        
        checkpoint_manager.mark_phase_complete("finalization")
    else:
        print("✓ Finalization already completed")

    # =========================================================================
    # PHASE 6: LLM-based Area Discovery (Optional)
    # =========================================================================
    if run_llm_discovery and LLM_DISCOVERY_AVAILABLE:
        if not checkpoint_manager.is_phase_complete("llm_discovery"):
            print("\n" + "="*60)
            print("PHASE 6: LLM-BASED AREA DISCOVERY")
            print("="*60)
            
            try:
                # Prepare city list
                cities = [(t["city"], t["state"]) for t in TARGET_CITIES]
                
                # Initialize discovery
                discovery = MultiLLMAreaDiscovery()
                
                # Discover neighborhoods and districts
                results = discovery.discover_all(cities)
                
                # Import KG integrator
                from multi_llm_area_discovery_fixed import KGIntegrator
                
                # Note: We're working directly with the graph object
                # The KGIntegrator expects a file path, so we need to save first
                # or modify the integrator. For now, we'll add directly.
                
                print(f"\nDiscovered {len(results['neighborhoods'])} neighborhoods")
                print(f"Discovered {len(results['districts'])} districts")
                
                # Add neighborhoods
                for area in results['neighborhoods']:
                    uri = URIRef(area.to_uri())
                    if (uri, RDF.type, None) not in g:
                        g.add((uri, RDF.type, UKO[area.uko_class]))
                        g.add((uri, RDFS.label, Literal(area.name)))
                        if area.boundaries:
                            g.add((uri, UKO.approximateBoundary, Literal(area.boundaries)))
                        if area.characteristics:
                            g.add((uri, UKO.neighborhoodCharacter, Literal(area.characteristics)))
                        g.add((uri, UKO.hasConfidenceLevel, Literal(area.confidence, datatype=XSD.decimal)))
                        
                        # Find and link to city
                        for city_name in city_geofences.keys():
                            if city_name.lower() in area.city.lower():
                                city_uri = Namespace("urn:urban-kg:entity/osm/")[f"city/{city_name.replace(' ', '_')}"]
                                g.add((uri, UKO.partOf, city_uri))
                                break
                
                # Add districts
                for area in results['districts']:
                    uri = URIRef(area.to_uri())
                    if (uri, RDF.type, None) not in g:
                        g.add((uri, RDF.type, UKO[area.uko_class]))
                        g.add((uri, RDFS.label, Literal(area.name)))
                        if area.boundaries:
                            g.add((uri, UKO.approximateBoundary, Literal(area.boundaries)))
                        if area.characteristics:
                            g.add((uri, UKO.neighborhoodCharacter, Literal(area.characteristics)))
                        g.add((uri, UKO.hasConfidenceLevel, Literal(area.confidence, datatype=XSD.decimal)))
                        
                        for city_name in city_geofences.keys():
                            if city_name.lower() in area.city.lower():
                                city_uri = Namespace("urn:urban-kg:entity/osm/")[f"city/{city_name.replace(' ', '_')}"]
                                g.add((uri, UKO.partOf, city_uri))
                                break
                
                print(f"✓ Added LLM-discovered areas to graph")
                checkpoint_manager.mark_phase_complete("llm_discovery")
                
            except Exception as e:
                print(f"Warning: LLM discovery failed: {e}")
                print("Continuing without LLM-discovered areas...")
        else:
            print("✓ LLM discovery already completed")
    elif run_llm_discovery and not LLM_DISCOVERY_AVAILABLE:
        print("\n⚠ LLM discovery requested but not available")
        print("  Install: pip install anthropic google-genai")
        print("  And ensure multi_llm_area_discovery_fixed.py is present")

    # =========================================================================
    # PHASE 7: Save Knowledge Graph
    # =========================================================================
    print("\n" + "="*60)
    print("SAVING KNOWLEDGE GRAPH")
    print("="*60)
    
    # Determine format and adjust filename if needed
    if output_format == 'nt':
        if not output_file.endswith('.nt'):
            output_file = output_file.rsplit('.', 1)[0] + '.nt'
        g.serialize(destination=output_file, format='nt')
    else:
        g.serialize(destination=output_file, format='turtle')
    
    print(f"✓ Knowledge graph saved to {output_file}")
    
    # Print final statistics
    print_graph_statistics(g, "FINAL KNOWLEDGE GRAPH STATISTICS")
    
    # Return the output file path for potential enrichment
    return output_file


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate an enhanced Urban Knowledge Graph for Contra Costa County."
    )
    parser.add_argument(
        "--output_file", 
        default="contracosta_kg_enhanced.ttl",
        help="Output file path for the knowledge graph"
    )
    parser.add_argument(
        "--data_dir", 
        default="data",
        help="Directory for data files"
    )
    parser.add_argument(
        "--force_download", 
        action="store_true",
        help="Force re-download of PBF file"
    )
    parser.add_argument(
        "--checkpoint_file", 
        default="kg_checkpoint.json",
        help="Checkpoint file for resumable processing"
    )
    parser.add_argument(
        "--no_debug", 
        action="store_true",
        help="Disable debug output"
    )
    parser.add_argument(
        "--llm_discovery",
        action="store_true",
        help="Run LLM-based neighborhood/district discovery"
    )
    parser.add_argument(
        "--output_format",
        choices=['turtle', 'nt'],
        default='turtle',
        help="Output format: 'turtle' (.ttl) or 'nt' (N-Triples, faster for large graphs)"
    )
    parser.add_argument(
        "--reset_checkpoint",
        action="store_true",
        help="Reset checkpoint and start fresh"
    )
    parser.add_argument(
        "--add_census",
        action="store_true",
        help="Add Census tract data with demographics (FREE - no API key required)"
    )
    parser.add_argument(
        "--add_pois",
        action="store_true",
        help="Add Overture Maps POI data (FREE - no API key required)"
    )
    parser.add_argument(
        "--add_safety",
        action="store_true",
        help="Add SWITRS/TIMS crash data and compute HIN (FREE - no API key required)"
    )
    parser.add_argument(
        "--census_data_dir",
        default="data/census",
        help="Directory for Census data files"
    )
    parser.add_argument(
        "--overture_data_dir",
        default="data/overture",
        help="Directory for Overture data files"
    )
    parser.add_argument(
        "--safety_years",
        nargs="+",
        type=int,
        default=[2019, 2020, 2021, 2022, 2023],
        help="Years of crash data to include (default: 2019-2023)"
    )
    parser.add_argument(
        "--switrs_csv",
        help="Path to local SWITRS CSV file (optional, otherwise uses sample data)"
    )
    
    args = parser.parse_args()
    
    # Reset checkpoint if requested
    if args.reset_checkpoint:
        if os.path.exists(args.checkpoint_file):
            os.remove(args.checkpoint_file)
            print("✓ Checkpoint reset")
    
    # Run the knowledge graph creation
    output_file = create_knowledge_graph(
        output_file=args.output_file,
        data_dir=args.data_dir,
        force_download=args.force_download,
        checkpoint_file=args.checkpoint_file,
        debug_mode=not args.no_debug,
        run_llm_discovery=args.llm_discovery,
        output_format=args.output_format
    )
    
    # =========================================================================
    # POST-PROCESSING: Data Enrichment (uses fast append, not full graph load)
    # =========================================================================
    
    current_kg = output_file
    
    # Add Census tract data
    if args.add_census:
        if CENSUS_LOADER_AVAILABLE:
            print("\n" + "="*60)
            print("ENRICHMENT: Adding Census Tract Data (FREE)")
            print("="*60)
            try:
                enriched_kg = load_census_tracts(
                    input_kg_path=current_kg,
                    output_kg_path=None,  # Auto-generates name with _with_census suffix
                    data_dir=args.census_data_dir
                )
                if enriched_kg:
                    current_kg = enriched_kg
                    print(f"✓ Census data added: {current_kg}")
            except Exception as e:
                print(f"Warning: Census enrichment failed: {e}")
        else:
            print("\n⚠ Census enrichment requested but loader not available")
            print("  Ensure census_tract_loader_fast.py is in the same directory")
    
    # Add Overture POI data
    if args.add_pois:
        if OVERTURE_LOADER_AVAILABLE:
            print("\n" + "="*60)
            print("ENRICHMENT: Adding Overture Maps POI Data (FREE)")
            print("="*60)
            try:
                enriched_kg = load_overture_pois(
                    input_kg_path=current_kg,
                    output_kg_path=None,  # Auto-generates name with _with_pois suffix
                    data_dir=args.overture_data_dir
                )
                if enriched_kg:
                    current_kg = enriched_kg
                    print(f"✓ POI data added: {current_kg}")
            except Exception as e:
                print(f"Warning: POI enrichment failed: {e}")
        else:
            print("\n⚠ POI enrichment requested but loader not available")
            print("  Ensure overture_poi_loader_fast.py is in the same directory")
            print("  Also install: pip install duckdb")
    
    # Add SWITRS Safety Data
    if args.add_safety:
        if SAFETY_LOADER_AVAILABLE:
            print("\n" + "="*60)
            print("ENRICHMENT: Adding SWITRS/TIMS Safety Data (FREE)")
            print("="*60)
            try:
                enriched_kg = load_switrs_safety(
                    input_file=current_kg,
                    output_file=None,  # Auto-generates name with _with_safety suffix
                    years=args.safety_years,
                    csv_file=args.switrs_csv,
                    use_sample_data=(args.switrs_csv is None)  # Use sample if no CSV provided
                )
                if enriched_kg:
                    current_kg = enriched_kg
                    print(f"✓ Safety data added: {current_kg}")
            except Exception as e:
                print(f"Warning: Safety enrichment failed: {e}")
        else:
            print("\n⚠ Safety enrichment requested but loader not available")
            print("  Ensure switrs_safety_loader.py is in the same directory")
            print("  Also install: pip install pandas geopandas shapely scipy")
    
    print("\n" + "="*60)
    print("ALL PROCESSING COMPLETE")
    print("="*60)
    print(f"Final knowledge graph: {current_kg}")
