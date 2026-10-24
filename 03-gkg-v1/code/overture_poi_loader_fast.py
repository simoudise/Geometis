"""
Overture Maps POI Data Loader - FAST VERSION

This version does NOT load the entire KG into memory.
Instead, it:
1. Downloads/queries Overture Maps POI data
2. Generates new triples as N-Triples
3. Concatenates to the existing file

This is 100x faster for large graphs.

Data source: https://overturemaps.org/ (FREE - No API key required)

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import json
import subprocess
from typing import Dict, List, Optional, Tuple, Set
import time

# =============================================================================
# CONSTANTS
# =============================================================================

# City bounding boxes (min_lon, min_lat, max_lon, max_lat)
CITY_BOUNDS = {
    "Walnut Creek": (-122.10, 37.87, -122.02, 37.93),
    "Pleasant Hill": (-122.10, 37.93, -122.04, 37.97),
    "Antioch": (-121.84, 37.97, -121.75, 38.02),
    "Pittsburg": (-121.92, 37.99, -121.84, 38.04),
    "Richmond": (-122.42, 37.90, -122.30, 37.98),
}

# Combined bounding box for all cities
CONTRA_COSTA_BBOX = (-122.42, 37.87, -121.75, 38.04)

# Overture category to UKO class mapping
OVERTURE_TO_UKO = {
    # Food & Beverage
    "eat_and_drink": "Restaurant",
    "restaurant": "Restaurant",
    "bar": "Bar",
    "cafe": "Cafe",
    "coffee_shop": "Cafe",
    "fast_food": "FastFoodRestaurant",
    "bakery": "Bakery",
    "ice_cream_shop": "IceCreamParlor",
    "brewery": "Brewery",
    "winery": "Winery",
    
    # Retail
    "retail": "RetailStore",
    "supermarket": "Supermarket",
    "grocery_store": "GroceryStore",
    "convenience_store": "ConvenienceStore",
    "department_store": "DepartmentStore",
    "shopping_mall": "ShoppingCenter",
    "clothing_store": "ClothingStore",
    "electronics_store": "ElectronicsStore",
    "furniture_store": "FurnitureStore",
    "hardware_store": "HardwareStore",
    "bookstore": "Bookstore",
    "pharmacy": "Pharmacy",
    "gas_station": "FuelStation",
    "car_dealer": "CarDealership",
    "car_repair": "AutoRepairShop",
    
    # Health
    "health_and_medical": "HealthcareFacility",
    "hospital": "Hospital",
    "doctor": "MedicalOffice",
    "dentist": "DentistOffice",
    "veterinarian": "VeterinaryClinic",
    "urgent_care": "UrgentCare",
    "nursing_home": "NursingHome",
    
    # Education
    "education": "EducationalFacility",
    "school": "School",
    "university": "University",
    "college": "College",
    "library": "Library",
    "preschool": "Preschool",
    
    # Services
    "service": "ServiceBusiness",
    "bank": "Bank",
    "atm": "ATM",
    "post_office": "PostOffice",
    "laundromat": "Laundromat",
    "dry_cleaner": "DryCleaner",
    "hair_salon": "HairSalon",
    "gym": "Gym",
    "fitness_center": "FitnessCenter",
    
    # Accommodation
    "accommodation": "Hotel",
    "hotel": "Hotel",
    "motel": "Motel",
    
    # Entertainment
    "arts_and_entertainment": "Entertainment",
    "movie_theater": "Cinema",
    "theater": "Theater",
    "museum": "Museum",
    "art_gallery": "ArtGallery",
    "park": "Park",
    "playground": "Playground",
    
    # Transportation
    "transportation": "TransportationFacility",
    "bus_station": "BusStation",
    "train_station": "TrainStation",
    "parking": "ParkingFacility",
    
    # Government
    "government": "GovernmentBuilding",
    "city_hall": "TownHall",
    "courthouse": "Courthouse",
    "police_station": "PoliceStation",
    "fire_station": "FireStation",
    
    # Religious
    "religious_organization": "PlaceOfWorship",
    "church": "Church",
    "mosque": "Mosque",
    "synagogue": "Synagogue",
    "temple": "Temple",
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def escape_literal(value: str) -> str:
    """Escape special characters in RDF literal."""
    if value is None:
        return ""
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')


def make_uri(uri: str) -> str:
    """Format as N-Triples URI."""
    return f"<{uri}>"


def make_literal(value, datatype: Optional[str] = None) -> str:
    """Format as N-Triples literal."""
    escaped = escape_literal(str(value))
    if datatype:
        return f'"{escaped}"^^<{datatype}>'
    return f'"{escaped}"'


def make_triple(subject: str, predicate: str, obj: str) -> str:
    """Create an N-Triples line."""
    return f"{subject} {predicate} {obj} .\n"


def safe_id(raw_id: str) -> str:
    """Create a safe ID for URIs."""
    return str(raw_id).replace(":", "_").replace("/", "_").replace(" ", "_").replace("#", "_")


def determine_city(lat: float, lon: float) -> Optional[str]:
    """Determine which city a coordinate belongs to."""
    for city, (min_lon, min_lat, max_lon, max_lat) in CITY_BOUNDS.items():
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return city
    return None


# =============================================================================
# OVERTURE DATA LOADING OPTIONS
# =============================================================================

def download_with_overturemaps_cli(
    bbox: Tuple[float, float, float, float],
    output_file: str
) -> bool:
    """
    Download Overture data using the official CLI tool.
    
    Install: pip install overturemaps
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    
    cmd = [
        "overturemaps", "download",
        "--bbox", f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "-f", "geojson",
        "--type", "place",
        "-o", output_file
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            print(f"✓ Downloaded to: {output_file}")
            return True
        else:
            print(f"Error: {result.stderr}")
            return False
    except FileNotFoundError:
        print("overturemaps CLI not found. Install with: pip install overturemaps")
        return False
    except subprocess.TimeoutExpired:
        print("Download timed out after 10 minutes")
        return False


def query_with_duckdb(
    bbox: Tuple[float, float, float, float],
    output_file: str
) -> bool:
    """
    Query Overture data directly from S3 using DuckDB.
    
    Install: pip install duckdb
    """
    try:
        import duckdb
    except ImportError:
        print("DuckDB not found. Install with: pip install duckdb")
        return False
    
    min_lon, min_lat, max_lon, max_lat = bbox
    
    # Latest Overture release
    OVERTURE_RELEASE = "2024-12-18.0"
    S3_PATH = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=places/type=place/*"
    
    print(f"Querying Overture Maps via DuckDB...")
    print(f"  Release: {OVERTURE_RELEASE}")
    print(f"  Bounding box: {bbox}")
    
    query = f"""
    INSTALL spatial;
    INSTALL httpfs;
    LOAD spatial;
    LOAD httpfs;
    
    SET s3_region='us-west-2';
    
    COPY (
        SELECT
            id,
            names.primary AS name,
            categories.primary AS category,
            confidence,
            websites[1] AS website,
            phones[1] AS phone,
            addresses[1].freeform AS address,
            addresses[1].locality AS city,
            addresses[1].postcode AS postcode,
            ST_X(ST_GeomFromWKB(geometry)) AS longitude,
            ST_Y(ST_GeomFromWKB(geometry)) AS latitude
        FROM read_parquet('{S3_PATH}', filename=true, hive_partitioning=1)
        WHERE 
            bbox.xmin >= {min_lon} AND bbox.xmax <= {max_lon}
            AND bbox.ymin >= {min_lat} AND bbox.ymax <= {max_lat}
    ) TO '{output_file}' (FORMAT CSV, HEADER);
    """
    
    try:
        conn = duckdb.connect()
        conn.execute(query)
        conn.close()
        print(f"✓ Downloaded to: {output_file}")
        return True
    except Exception as e:
        print(f"DuckDB query failed: {e}")
        return False


def load_geojson_file(filepath: str) -> List[Dict]:
    """Load places from a GeoJSON file."""
    import json
    
    print(f"Loading GeoJSON from: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    places = []
    features = data.get('features', [])
    
    for feature in features:
        props = feature.get('properties', {})
        geom = feature.get('geometry', {})
        coords = geom.get('coordinates', [None, None])
        
        # Handle nested name/category structures
        name = props.get('name')
        if isinstance(name, dict):
            name = name.get('primary', name.get('common', str(name)))
        
        category = props.get('category')
        if isinstance(category, dict):
            category = category.get('primary', category.get('main', ''))
        
        # Handle names structure from Overture
        names = props.get('names', {})
        if isinstance(names, dict) and not name:
            name = names.get('primary', '')
        
        categories = props.get('categories', {})
        if isinstance(categories, dict) and not category:
            category = categories.get('primary', '')
        
        places.append({
            'id': props.get('id', feature.get('id', '')),
            'name': name or props.get('names', {}).get('primary', ''),
            'category': category or props.get('categories', {}).get('primary', ''),
            'latitude': coords[1] if len(coords) > 1 else None,
            'longitude': coords[0] if len(coords) > 0 else None,
            'address': props.get('address', props.get('addresses', [{}])[0].get('freeform', '') if isinstance(props.get('addresses'), list) else ''),
            'phone': props.get('phone', ''),
            'website': props.get('website', ''),
            'confidence': props.get('confidence', 0.5),
        })
    
    print(f"✓ Loaded {len(places):,} places")
    return places


def load_csv_file(filepath: str) -> List[Dict]:
    """Load places from a CSV file (DuckDB output)."""
    import csv
    
    print(f"Loading CSV from: {filepath}")
    
    places = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            places.append({
                'id': row.get('id', ''),
                'name': row.get('name', ''),
                'category': row.get('category', ''),
                'latitude': float(row['latitude']) if row.get('latitude') else None,
                'longitude': float(row['longitude']) if row.get('longitude') else None,
                'address': row.get('address', ''),
                'phone': row.get('phone', ''),
                'website': row.get('website', ''),
                'confidence': float(row.get('confidence', 0.5)) if row.get('confidence') else 0.5,
            })
    
    print(f"✓ Loaded {len(places):,} places")
    return places


# =============================================================================
# N-TRIPLES GENERATION
# =============================================================================

def generate_poi_triples(
    places: List[Dict],
    output_file: str,
    existing_ids: Optional[Set[str]] = None
) -> Tuple[int, int]:
    """
    Generate N-Triples for POI data.
    
    Returns (triples_count, places_added).
    """
    print(f"Generating POI triples to: {output_file}")
    
    if existing_ids is None:
        existing_ids = set()
    
    # Namespaces
    UKO = "urn:urban-kg:"
    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    XSD = "http://www.w3.org/2001/XMLSchema#"
    
    triple_count = 0
    places_added = 0
    skipped = 0
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f'# Overture Maps POI Data\n')
        f.write(f'# Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n')
        
        for idx, place in enumerate(places):
            # Skip if missing required fields
            if not place.get('name') or not place.get('latitude') or not place.get('longitude'):
                skipped += 1
                continue
            
            # Generate safe ID
            place_id = safe_id(place.get('id', f"overture_{idx}"))
            
            # Skip duplicates
            if place_id in existing_ids:
                skipped += 1
                continue
            existing_ids.add(place_id)
            
            # Determine UKO class
            category = place.get('category', '').lower().replace(' ', '_')
            uko_class = OVERTURE_TO_UKO.get(category, "PointOfInterest")
            
            # Generate URI
            poi_uri = make_uri(f"urn:urban-kg:entity/overture/{place_id}")
            
            # Type
            f.write(make_triple(poi_uri, make_uri(f"{RDF}type"), make_uri(f"{UKO}{uko_class}")))
            triple_count += 1
            
            # Label
            name = place['name']
            f.write(make_triple(poi_uri, make_uri(f"{RDFS}label"), make_literal(name)))
            triple_count += 1
            
            # Coordinates
            f.write(make_triple(
                poi_uri,
                make_uri(f"{UKO}latitude"),
                make_literal(f"{place['latitude']:.6f}", f"{XSD}decimal")
            ))
            triple_count += 1
            
            f.write(make_triple(
                poi_uri,
                make_uri(f"{UKO}longitude"),
                make_literal(f"{place['longitude']:.6f}", f"{XSD}decimal")
            ))
            triple_count += 1
            
            # External ID and source
            f.write(make_triple(poi_uri, make_uri(f"{UKO}externalId"), make_literal(place.get('id', ''))))
            triple_count += 1
            
            f.write(make_triple(poi_uri, make_uri(f"{UKO}dataSource"), make_literal("overture_maps")))
            triple_count += 1
            
            # Optional: Address
            if place.get('address'):
                f.write(make_triple(poi_uri, make_uri(f"{UKO}address"), make_literal(place['address'])))
                triple_count += 1
            
            # Optional: Phone
            if place.get('phone'):
                f.write(make_triple(poi_uri, make_uri(f"{UKO}phone"), make_literal(place['phone'])))
                triple_count += 1
            
            # Optional: Website
            if place.get('website'):
                f.write(make_triple(poi_uri, make_uri(f"{UKO}website"), make_literal(place['website'])))
                triple_count += 1
            
            # Confidence
            if place.get('confidence'):
                f.write(make_triple(
                    poi_uri,
                    make_uri(f"{UKO}hasConfidenceLevel"),
                    make_literal(f"{place['confidence']:.2f}", f"{XSD}decimal")
                ))
                triple_count += 1
            
            # City relationship
            city = determine_city(place['latitude'], place['longitude'])
            if city:
                city_uri = make_uri(f"urn:urban-kg:entity/osm/city/{city.replace(' ', '_')}")
                f.write(make_triple(poi_uri, make_uri(f"{UKO}partOf"), city_uri))
                triple_count += 1
            
            places_added += 1
            
            if (idx + 1) % 1000 == 0:
                print(f"\r  Processed {idx + 1:,} places...", end='', flush=True)
    
    print(f"\n✓ Generated {triple_count:,} triples for {places_added:,} POIs (skipped {skipped:,})")
    return triple_count, places_added


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main(
    input_kg_path: str,
    output_kg_path: Optional[str] = None,
    data_dir: str = "data/overture",
    geojson_path: Optional[str] = None,
    bbox: Tuple[float, float, float, float] = CONTRA_COSTA_BBOX
):
    """
    Fast Overture POI loader - appends to KG without loading it.
    
    1. Downloads Overture POI data (FREE)
    2. Generates N-Triples
    3. Concatenates to existing KG file
    """
    print("="*60)
    print("OVERTURE MAPS POI LOADER (FAST VERSION)")
    print("="*60)
    print("FREE - No API key required")
    print("="*60)
    
    start_time = time.time()
    os.makedirs(data_dir, exist_ok=True)
    
    # Check input file exists
    if not os.path.exists(input_kg_path):
        print(f"ERROR: Input file not found: {input_kg_path}")
        return None
    
    input_size = os.path.getsize(input_kg_path) / (1024*1024)
    print(f"\nInput KG: {input_kg_path} ({input_size:.1f} MB)")
    
    # Step 1: Get Overture data
    places = []
    
    if geojson_path and os.path.exists(geojson_path):
        # Use provided GeoJSON file
        places = load_geojson_file(geojson_path)
    else:
        # Try to download data
        csv_file = os.path.join(data_dir, "overture_places.csv")
        geojson_file = os.path.join(data_dir, "overture_places.geojson")
        
        # Try DuckDB first (faster for large areas)
        print("\nAttempting to download Overture data...")
        
        if query_with_duckdb(bbox, csv_file):
            places = load_csv_file(csv_file)
        elif download_with_overturemaps_cli(bbox, geojson_file):
            places = load_geojson_file(geojson_file)
        else:
            print("\n" + "="*60)
            print("MANUAL DOWNLOAD REQUIRED")
            print("="*60)
            print("\nCould not automatically download Overture data.")
            print("Please install one of these tools and try again:\n")
            print("Option 1 - DuckDB (recommended):")
            print("  pip install duckdb\n")
            print("Option 2 - Overture CLI:")
            print("  pip install overturemaps\n")
            print("Option 3 - Manual download:")
            print(f"  1. Go to https://docs.overturemaps.org/getting-data/")
            print(f"  2. Download places data for bbox: {bbox}")
            print(f"  3. Run again with: --geojson <downloaded_file.geojson>")
            return None
    
    if not places:
        print("No places found to add.")
        return None
    
    # Step 2: Generate POI triples
    poi_triples_file = os.path.join(data_dir, "poi_triples.nt")
    triple_count, places_added = generate_poi_triples(places, poi_triples_file)
    
    # Step 3: Determine output path
    if output_kg_path is None:
        base, ext = os.path.splitext(input_kg_path)
        output_kg_path = f"{base}_with_pois{ext}"
    
    # Step 4: Concatenate files
    print(f"\nMerging with existing KG...")
    
    if output_kg_path != input_kg_path:
        # Copy original and append
        import shutil
        shutil.copy(input_kg_path, output_kg_path)
        print(f"  Copied base KG to: {output_kg_path}")
    
    # Append POI triples
    with open(output_kg_path, 'a', encoding='utf-8') as out_f:
        out_f.write(f"\n# Overture Maps POI Data - Added {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        with open(poi_triples_file, 'r', encoding='utf-8') as poi_f:
            for line in poi_f:
                out_f.write(line)
    
    output_size = os.path.getsize(output_kg_path) / (1024*1024)
    elapsed = time.time() - start_time
    
    print(f"\n" + "="*60)
    print("COMPLETE")
    print("="*60)
    print(f"Output: {output_kg_path} ({output_size:.1f} MB)")
    print(f"POIs added: {places_added:,}")
    print(f"New triples: {triple_count:,}")
    print(f"Time elapsed: {elapsed:.1f} seconds")
    
    # Cleanup temp file
    if os.path.exists(poi_triples_file):
        os.remove(poi_triples_file)
    
    # Print category breakdown
    print(f"\nPOI Category Breakdown:")
    categories = {}
    for p in places:
        cat = p.get('category', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1
    
    for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:15]:
        print(f"  {cat}: {count:,}")
    
    return output_kg_path


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fast Overture Maps POI loader (appends without loading KG)"
    )
    parser.add_argument("--input", "-i", required=True, 
                       help="Input knowledge graph (.nt file)")
    parser.add_argument("--output", "-o", 
                       help="Output path (default: adds '_with_pois' suffix)")
    parser.add_argument("--data_dir", default="data/overture", 
                       help="Directory for Overture data files")
    parser.add_argument("--geojson", 
                       help="Path to pre-downloaded Overture GeoJSON file")
    parser.add_argument("--bbox", type=str,
                       help="Bounding box: min_lon,min_lat,max_lon,max_lat")
    
    args = parser.parse_args()
    
    bbox = CONTRA_COSTA_BBOX
    if args.bbox:
        bbox = tuple(map(float, args.bbox.split(',')))
    
    main(
        input_kg_path=args.input,
        output_kg_path=args.output,
        data_dir=args.data_dir,
        geojson_path=args.geojson,
        bbox=bbox
    )
