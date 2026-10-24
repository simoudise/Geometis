"""
Debug script to identify duplicate POIs in the knowledge graph
"""

from rdflib import Graph, Namespace
from collections import defaultdict
import sys

UKO = Namespace("urn:urban-kg:")

def analyze_duplicates(kg_file: str):
    """Analyze duplicate POIs in the knowledge graph"""
    
    print(f"Loading knowledge graph from {kg_file}...")
    graph = Graph()
    graph.parse(kg_file, format="turtle")
    print(f"✓ Loaded {len(graph):,} triples")
    
    # Query for all POIs with coordinates
    query = """
    PREFIX uko: <urn:urban-kg:>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?poi ?name ?type ?lat ?lon
    WHERE {
        ?poi a ?type ;
             uko:latitude ?lat ;
             uko:longitude ?lon .
        OPTIONAL { ?poi rdfs:label ?name }
        FILTER (CONTAINS(STR(?type), "Park") || CONTAINS(STR(?type), "BART"))
    }
    """
    
    results = list(graph.query(query))
    print(f"\nFound {len(results)} POIs matching 'Park' or 'BART'\n")
    
    # Group by name
    by_name = defaultdict(list)
    
    for row in results:
        name = str(row.name) if row.name else "Unnamed"
        by_name[name].append({
            'uri': str(row.poi),
            'type': str(row.type),
            'lat': float(row.lat),
            'lon': float(row.lon)
        })
    
    # Find duplicates
    print("="*80)
    print("DUPLICATE ANALYSIS")
    print("="*80)
    
    duplicates = {name: pois for name, pois in by_name.items() if len(pois) > 1}
    
    if not duplicates:
        print("No duplicates found!")
    else:
        print(f"Found {len(duplicates)} POI names with multiple entries:\n")
        
        for name, pois in sorted(duplicates.items()):
            print(f"\n{name} ({len(pois)} entries):")
            for i, poi in enumerate(pois, 1):
                print(f"  {i}. URI: {poi['uri']}")
                print(f"     Type: {poi['type'].split(':')[-1]}")
                print(f"     Coordinates: ({poi['lat']:.6f}, {poi['lon']:.6f})")
            
            # Check if coordinates are identical
            coords = [(p['lat'], p['lon']) for p in pois]
            unique_coords = set(coords)
            if len(unique_coords) == 1:
                print(f"     → IDENTICAL coordinates (true duplicate)")
            else:
                print(f"     → Different coordinates:")
                for coord in unique_coords:
                    count = coords.count(coord)
                    print(f"        • {coord}: {count} instance(s)")
    
    print("\n" + "="*80)
    
    # Also check Fox Creek Park specifically
    print("\nSPECIFIC: Fox Creek Park Analysis")
    print("="*80)
    
    fox_creek = by_name.get("Fox Creek Park", [])
    if fox_creek:
        print(f"Found {len(fox_creek)} entries for 'Fox Creek Park':")
        for i, poi in enumerate(fox_creek, 1):
            print(f"\n  Entry {i}:")
            print(f"    URI: {poi['uri']}")
            print(f"    Type: {poi['type']}")
            print(f"    Lat: {poi['lat']:.10f}")
            print(f"    Lon: {poi['lon']:.10f}")
            print(f"    Rounded (5 decimals): ({round(poi['lat'], 5)}, {round(poi['lon'], 5)})")
    else:
        print("Fox Creek Park not found in results")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_kg_duplicates.py <kg_file.ttl>")
        sys.exit(1)
    
    analyze_duplicates(sys.argv[1])