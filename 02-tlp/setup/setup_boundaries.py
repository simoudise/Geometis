import os
import json
import requests

OUTPUT_DIR = os.path.expanduser("~/Downloads/store-trips/boundaries")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Official US Census Bureau TIGERweb API for California (STATE=06) Incorporated Places
CENSUS_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query"

params = {
    "where": "STATE='06' AND BASENAME IN ('Antioch', 'Concord', 'Pittsburg', 'Pleasant Hill', 'Walnut Creek')",
    "outFields": "BASENAME",
    "outSR": "4326",
    "f": "geojson"
}

headers = {
    "User-Agent": "CCTA-Trip-Study/1.0"
}

print("Fetching municipal boundaries from US Census Bureau...")
response = requests.get(CENSUS_URL, params=params, headers=headers, timeout=30)
response.raise_for_status()

data = response.json()
features = data.get("features", [])
print(f"Successfully retrieved {len(features)} city boundaries.")

for feat in features:
    city_name = feat["properties"]["BASENAME"]
    filename = f"{city_name.replace(' ', '_').lower()}.geojson"
    out_path = os.path.join(OUTPUT_DIR, filename)
    
    city_geojson = {
        "type": "FeatureCollection",
        "features": [feat]
    }
    
    with open(out_path, "w") as f:
        json.dump(city_geojson, f, indent=2)
    print(f"  Saved {city_name} -> {out_path}")

print("All boundaries ready.")
