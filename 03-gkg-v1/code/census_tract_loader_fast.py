"""
Census Tract Data Loader - FAST VERSION

This version does NOT load the entire KG into memory.
Instead, it:
1. Downloads census tract data
2. Generates new triples as N-Triples
3. Concatenates to the existing file

This is 100x faster for large graphs.

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import json
import requests
import geopandas as gpd
from shapely.geometry import Point, Polygon
from typing import Dict, List, Optional, Tuple
import time

# =============================================================================
# CONSTANTS
# =============================================================================

CALIFORNIA_FIPS = "06"
CONTRA_COSTA_FIPS = "013"

TIGER_BASE_URL = "https://www2.census.gov/geo/tiger/TIGER2023/TRACT/"
CENSUS_API_BASE = "https://api.census.gov/data"

# City bounding boxes for tract assignment
CITY_BOUNDS = {
    "Walnut Creek": {"lat_min": 37.87, "lat_max": 37.93, "lon_min": -122.10, "lon_max": -122.02},
    "Pleasant Hill": {"lat_min": 37.93, "lat_max": 37.97, "lon_min": -122.10, "lon_max": -122.04},
    "Antioch": {"lat_min": 37.97, "lat_max": 38.02, "lon_min": -121.84, "lon_max": -121.75},
    "Pittsburg": {"lat_min": 37.99, "lat_max": 38.04, "lon_min": -121.92, "lon_max": -121.84},
    "Richmond": {"lat_min": 37.90, "lat_max": 37.98, "lon_min": -122.42, "lon_max": -122.30},
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def escape_literal(value: str) -> str:
    """Escape special characters in RDF literal."""
    return value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')


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


# =============================================================================
# CENSUS DATA FUNCTIONS
# =============================================================================

def download_tiger_tracts(state_fips: str, output_dir: str) -> str:
    """Download TIGER/Line census tract shapefile."""
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"tl_2023_{state_fips}_tract.zip"
    url = f"{TIGER_BASE_URL}{filename}"
    local_path = os.path.join(output_dir, filename)
    
    if os.path.exists(local_path):
        print(f"✓ Using cached TIGER file: {local_path}")
        return local_path
    
    print(f"Downloading TIGER tracts from: {url}")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    
    with open(local_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total_size > 0:
                pct = 100 * downloaded / total_size
                print(f"\r  Downloading: {pct:.1f}%", end='', flush=True)
    
    print(f"\n✓ Downloaded to: {local_path}")
    return local_path


def load_county_tracts(shapefile_path: str, county_fips: str) -> gpd.GeoDataFrame:
    """Load census tracts for the specific county."""
    print(f"Loading tracts for county {county_fips}...")
    
    gdf = gpd.read_file(f"zip://{shapefile_path}")
    county_gdf = gdf[gdf['COUNTYFP'] == county_fips].copy()
    
    print(f"✓ Loaded {len(county_gdf)} census tracts")
    return county_gdf


def fetch_acs_demographics(state_fips: str, county_fips: str, year: int = 2022) -> Dict[str, Dict]:
    """Fetch demographic data from ACS API (FREE)."""
    print(f"Fetching ACS {year} 5-year estimates...")
    
    url = f"{CENSUS_API_BASE}/{year}/acs/acs5"
    
    variables = [
        "NAME",
        "B01003_001E",  # Total population
        "B19013_001E",  # Median household income
        "B01002_001E",  # Median age
        "B25001_001E",  # Housing units
    ]
    
    params = {
        "get": ",".join(variables),
        "for": "tract:*",
        "in": f"state:{state_fips}&in=county:{county_fips}"
    }
    
    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        headers = data[0]
        demographics = {}
        
        for row in data[1:]:
            row_dict = dict(zip(headers, row))
            geoid = f"{state_fips}{county_fips}{row_dict['tract']}"
            
            demographics[geoid] = {
                'name': row_dict.get('NAME', ''),
                'total_population': safe_int(row_dict.get('B01003_001E')),
                'median_household_income': safe_int(row_dict.get('B19013_001E')),
                'median_age': safe_float(row_dict.get('B01002_001E')),
                'housing_units': safe_int(row_dict.get('B25001_001E')),
            }
        
        print(f"✓ Fetched demographics for {len(demographics)} tracts")
        return demographics
        
    except Exception as e:
        print(f"Warning: Could not fetch ACS data: {e}")
        return {}


def safe_int(value) -> Optional[int]:
    try:
        return int(value) if value and value not in ['-', 'null', ''] else None
    except (ValueError, TypeError):
        return None


def safe_float(value) -> Optional[float]:
    try:
        return float(value) if value and value not in ['-', 'null', ''] else None
    except (ValueError, TypeError):
        return None


def assign_tract_to_city(centroid_lat: float, centroid_lon: float) -> Optional[str]:
    """Determine which city a tract belongs to based on centroid."""
    for city, bounds in CITY_BOUNDS.items():
        if (bounds['lat_min'] <= centroid_lat <= bounds['lat_max'] and
            bounds['lon_min'] <= centroid_lon <= bounds['lon_max']):
            return city
    return None


# =============================================================================
# N-TRIPLES GENERATION
# =============================================================================

def generate_census_triples(
    tracts_gdf: gpd.GeoDataFrame,
    demographics: Dict[str, Dict],
    output_file: str
) -> int:
    """
    Generate N-Triples for census tract data.
    
    Returns number of triples generated.
    """
    print(f"Generating census tract triples to: {output_file}")
    
    # Namespaces
    UKO = "urn:urban-kg:"
    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    XSD = "http://www.w3.org/2001/XMLSchema#"
    GEO = "http://www.opengis.net/ont/geosparql#"
    
    triple_count = 0
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # First, add ontology triples (class definitions)
        f.write(f'# Census Tract Ontology Extension\n')
        f.write(make_triple(
            make_uri(f"{UKO}CensusTract"),
            make_uri(f"{RDF}type"),
            make_uri("http://www.w3.org/2002/07/owl#Class")
        ))
        triple_count += 1
        
        f.write(make_triple(
            make_uri(f"{UKO}CensusTract"),
            make_uri(f"{RDFS}label"),
            make_literal("Census Tract")
        ))
        triple_count += 1
        
        # Add each tract
        for idx, tract in tracts_gdf.iterrows():
            geoid = tract['GEOID']
            tract_code = tract['TRACTCE']
            
            # Get centroid for coordinates
            centroid = tract.geometry.centroid
            lat, lon = centroid.y, centroid.x
            
            # Determine city
            city = assign_tract_to_city(lat, lon)
            
            # Get demographics
            demo = demographics.get(geoid, {})
            
            # Generate URI
            tract_uri = make_uri(f"urn:urban-kg:entity/census/tract/{geoid}")
            
            # Type
            f.write(make_triple(tract_uri, make_uri(f"{RDF}type"), make_uri(f"{UKO}CensusTract")))
            triple_count += 1
            
            # Label
            label = demo.get('name', f"Census Tract {tract_code}")
            f.write(make_triple(tract_uri, make_uri(f"{RDFS}label"), make_literal(label)))
            triple_count += 1
            
            # Identifiers
            f.write(make_triple(tract_uri, make_uri(f"{UKO}geoid"), make_literal(geoid)))
            triple_count += 1
            
            f.write(make_triple(tract_uri, make_uri(f"{UKO}tractCode"), make_literal(tract_code)))
            triple_count += 1
            
            f.write(make_triple(tract_uri, make_uri(f"{UKO}statefp"), make_literal(CALIFORNIA_FIPS)))
            triple_count += 1
            
            f.write(make_triple(tract_uri, make_uri(f"{UKO}countyfp"), make_literal(CONTRA_COSTA_FIPS)))
            triple_count += 1
            
            # Coordinates
            f.write(make_triple(
                tract_uri, 
                make_uri(f"{UKO}latitude"), 
                make_literal(f"{lat:.6f}", f"{XSD}decimal")
            ))
            triple_count += 1
            
            f.write(make_triple(
                tract_uri, 
                make_uri(f"{UKO}longitude"), 
                make_literal(f"{lon:.6f}", f"{XSD}decimal")
            ))
            triple_count += 1
            
            # Demographics
            if demo.get('total_population'):
                f.write(make_triple(
                    tract_uri,
                    make_uri(f"{UKO}totalPopulation"),
                    make_literal(demo['total_population'], f"{XSD}integer")
                ))
                triple_count += 1
            
            if demo.get('median_household_income'):
                f.write(make_triple(
                    tract_uri,
                    make_uri(f"{UKO}medianHouseholdIncome"),
                    make_literal(demo['median_household_income'], f"{XSD}integer")
                ))
                triple_count += 1
            
            if demo.get('median_age'):
                f.write(make_triple(
                    tract_uri,
                    make_uri(f"{UKO}medianAge"),
                    make_literal(f"{demo['median_age']:.1f}", f"{XSD}decimal")
                ))
                triple_count += 1
            
            if demo.get('housing_units'):
                f.write(make_triple(
                    tract_uri,
                    make_uri(f"{UKO}housingUnits"),
                    make_literal(demo['housing_units'], f"{XSD}integer")
                ))
                triple_count += 1
            
            # City relationship
            if city:
                city_uri = make_uri(f"urn:urban-kg:entity/osm/city/{city.replace(' ', '_')}")
                f.write(make_triple(tract_uri, make_uri(f"{UKO}tractInCity"), city_uri))
                triple_count += 1
            
            # Provenance
            f.write(make_triple(
                tract_uri,
                make_uri(f"{UKO}censusYear"),
                make_literal("2020", f"{XSD}gYear")
            ))
            triple_count += 1
            
            if (idx + 1) % 50 == 0:
                print(f"\r  Processed {idx + 1} tracts...", end='', flush=True)
    
    print(f"\n✓ Generated {triple_count:,} triples for {len(tracts_gdf)} census tracts")
    return triple_count


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main(
    input_kg_path: str,
    output_kg_path: Optional[str] = None,
    data_dir: str = "data/census"
):
    """
    Fast census tract loader - appends to KG without loading it.
    
    1. Downloads TIGER shapefiles (FREE)
    2. Fetches ACS demographics (FREE)
    3. Generates N-Triples
    4. Concatenates to existing KG file
    """
    print("="*60)
    print("CENSUS TRACT LOADER (FAST VERSION)")
    print("="*60)
    
    start_time = time.time()
    
    # Check input file exists
    if not os.path.exists(input_kg_path):
        print(f"ERROR: Input file not found: {input_kg_path}")
        return None
    
    input_size = os.path.getsize(input_kg_path) / (1024*1024)
    print(f"\nInput KG: {input_kg_path} ({input_size:.1f} MB)")
    
    # Download TIGER data
    tiger_path = download_tiger_tracts(CALIFORNIA_FIPS, data_dir)
    
    # Load county tracts
    tracts_gdf = load_county_tracts(tiger_path, CONTRA_COSTA_FIPS)
    
    # Fetch demographics
    demographics = fetch_acs_demographics(CALIFORNIA_FIPS, CONTRA_COSTA_FIPS)
    
    # Generate census triples to temp file
    census_triples_file = os.path.join(data_dir, "census_triples.nt")
    triple_count = generate_census_triples(tracts_gdf, demographics, census_triples_file)
    
    # Determine output path
    if output_kg_path is None:
        base, ext = os.path.splitext(input_kg_path)
        output_kg_path = f"{base}_with_census{ext}"
    
    # Concatenate files
    print(f"\nMerging with existing KG...")
    
    if output_kg_path != input_kg_path:
        # Copy original and append
        import shutil
        shutil.copy(input_kg_path, output_kg_path)
    
    # Append census triples
    with open(output_kg_path, 'a', encoding='utf-8') as out_f:
        out_f.write(f"\n# Census Tract Data - Added {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        with open(census_triples_file, 'r', encoding='utf-8') as census_f:
            for line in census_f:
                out_f.write(line)
    
    output_size = os.path.getsize(output_kg_path) / (1024*1024)
    elapsed = time.time() - start_time
    
    print(f"\n" + "="*60)
    print("COMPLETE")
    print("="*60)
    print(f"Output: {output_kg_path} ({output_size:.1f} MB)")
    print(f"Census tracts added: {len(tracts_gdf)}")
    print(f"New triples: {triple_count:,}")
    print(f"Time elapsed: {elapsed:.1f} seconds")
    
    # Cleanup temp file
    if os.path.exists(census_triples_file):
        os.remove(census_triples_file)
    
    return output_kg_path


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Fast census tract loader (appends without loading KG)")
    parser.add_argument("--input", "-i", required=True, help="Input knowledge graph (.nt file)")
    parser.add_argument("--output", "-o", help="Output path (default: adds '_with_census' suffix)")
    parser.add_argument("--data_dir", default="data/census", help="Directory for census data files")
    
    args = parser.parse_args()
    
    main(args.input, args.output, args.data_dir)
