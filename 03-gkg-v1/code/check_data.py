import json
import os
import numpy as np

data_dir = "./georotate_training_data_v4"

def validate():
    print(f"--- Validating Data in {data_dir} ---")
    
    # 1. Check Mappings
    with open(os.path.join(data_dir, "entity_to_id.json"), 'r') as f:
        e2id = json.load(f)
    num_entities = len(e2id)
    print(f"[✓] Mapping: Found {num_entities:,} entities.")

    # 2. Check Triples Alignment
    triples = np.loadtxt(os.path.join(data_dir, "triples.txt"), dtype=np.int64)
    max_entity_id = max(triples[:, 0].max(), triples[:, 2].max())
    if max_entity_id >= num_entities:
        print(f"[!] FAIL: Triples contain ID {max_entity_id}, but mapping only goes to {num_entities-1}.")
    else:
        print(f"[✓] Triples: {len(triples):,} triples are within valid ID range.")

    # 3. Check Coordinate Coverage
    coords = np.loadtxt(os.path.join(data_dir, "coordinates.txt"))
    coord_ids = set(coords[:, 0].astype(int))
    coverage = (len(coord_ids) / num_entities) * 100
    print(f"[✓] Coordinates: Found {len(coord_ids):,} entries ({coverage:.1f}% coverage).")

    # 4. Check Spatial Relations Format
    with open(os.path.join(data_dir, "spatial_relations.json"), 'r') as f:
        spatial_data = json.load(f)
    if isinstance(spatial_data, list):
        print(f"[✓] Spatial JSON: Valid List format (ID-Aware loader will handle this).")
    elif isinstance(spatial_data, dict) and 'spatial_relation_ids' in spatial_data:
        print(f"[✓] Spatial JSON: Valid Dictionary format.")
    else:
        print(f"[!] WARNING: Unexpected format in spatial_relations.json.")

if __name__ == "__main__":
    validate()