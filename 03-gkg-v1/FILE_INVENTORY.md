# File Inventory & Cleanup Guide

Based on actual directory structure as of January 2026.

---

## Files to KEEP (Production)

### Knowledge Graph
```
contracosta_kg_final.nt          # Production KG (5.02 GB, ~40.3M triples)
```

### Ontology
```
uko_ontology_v8.ttl              # Consolidated ontology (243 KB)
```

### Core Scripts (in root directory)
```
main.py                          # Main orchestrator (27 KB) - has --add_census, --add_pois, --add_safety
osm_handler.py                   # OSM parsing (33 KB) - this IS v2 internally, keep as-is
osm_to_uko_mapper.py             # OSM tag mapping (34 KB) - this IS v2 internally
                                 # NOTE: Rename to osm_to_uko_mapper_v2.py (osm_handler.py imports from _v2)
census_tract_loader_fast.py      # Census data integration (15 KB)
overture_poi_loader_fast.py      # Overture POI enrichment (21 KB)
switrs_safety_loader.py          # SWITRS collision data & HIN (42 KB)
materialize_relationships.py     # Cross-domain relationship creation (20 KB)
prepare_embeddings.py            # Embedding data preparation (20 KB)
utils.py                         # Utility functions (9 KB)
```

### Supporting Scripts
```
multi_llm_area_discovery_fixed.py  # LLM-based neighborhood discovery (32 KB)
validate_kg.py                     # KG validation (18 KB)
train_georotate.py                 # Embedding training script (15 KB) - keep in root
```

### Embedding Framework (folders in root)
```
models/                          # Model architecture
├── __init__.py
└── georotate.py                 # GeoRotatE model (24 KB)

inference/                       # Inference code  
├── __init__.py
└── similarity.py                # Similarity search (17 KB)

llm_augmentation/                # LLM data augmentation
├── __init__.py
├── area_discovery.py
├── core.py
├── pipeline.py
├── poi_augmentation.py
└── sidewalk_inference.py

georotate_training_data/         # Prepared training data
├── coordinates.txt              # Entity coordinates (14.4 MB)
├── dataset_stats.json
├── entity_to_id.json            # Entity mappings (12.4 MB)
├── relation_to_id.json
├── spatial_relations.json
├── topological_features.npz     # Shape features (66.1 MB)
└── triples.txt                  # Training triples (413.9 MB)

georotate_output/                # Training outputs (keep for trained models)
```

### Data Folders
```
data/                            # General data folder
├── __init__.py
├── __pycache__/
└── dataset.py                   # Dataset class (15 KB)

census/                          # Census data cache

overture/                        # Overture data
└── overture_places.geojson      # POI data (38.3 MB)

switrs/                          # SWITRS data folder
```

### Source Data
```
crashes.csv                      # SWITRS collision data (2.6 MB)
norcal-latest.osm.pbf            # OSM extract (630.6 MB) - or contra-costa specific extract
```

### Documentation & Config
```
README.md                        # Main project documentation (8 KB)
requirements.txt                 # Python dependencies (626 bytes)
```

### Other (Optional Keep)
```
SHACL_rules.ttl                  # Validation rules (24 KB) - optional
relationship_gap_analysis.md     # Analysis document (9 KB) - optional
train_m3_optimized.sh            # Mac M3 training script (5 KB) - optional
train_on_m3.sh                   # Mac M3 training script (2 KB) - optional
GKG Model Notes.docx             # Notes document (25 KB) - optional
```

### Virtual Environment (DO NOT MODIFY)
```
georotate_env/                   # Python virtual environment - leave as-is
```

---

## Files to MOVE to OLD VERSIONS

These are already superseded but you may want to keep for reference:

```
prepare_data_for_embeddings.py   # Superseded by prepare_embeddings.py
prepare_georotate_data.py        # Duplicate of georotate_training_data prep
```

---

## Required Fix

**One file rename needed** (osm_handler.py imports from osm_to_uko_mapper_v2):

```bash
mv osm_to_uko_mapper.py osm_to_uko_mapper_v2.py
```

---

## Files Already in OLD VERSIONS

Good - you've already moved old versions there. Keep that folder for reference.

---

## How to Regenerate contracosta_kg_final.nt

```bash
# Step 1: Build base KG with all enrichments
python main.py \
  --pbf_file norcal-latest.osm.pbf \
  --output_file contracosta_kg.nt \
  --add_census \
  --add_pois \
  --add_safety \
  --switrs_csv crashes.csv

# Step 2: Materialize cross-domain relationships
python materialize_relationships.py \
  --input contracosta_kg.nt \
  --output contracosta_kg_final.nt
```

---

## Directory Structure Summary

Your current flat structure is fine - no reorganization needed:

```
contra-costa-updated-gkg-project/
├── main.py                      # Entry point
├── osm_handler.py               # OSM processing (v2)
├── osm_to_uko_mapper.py         # RENAME TO osm_to_uko_mapper_v2.py
├── census_tract_loader_fast.py
├── overture_poi_loader_fast.py
├── switrs_safety_loader.py
├── materialize_relationships.py
├── prepare_embeddings.py
├── train_georotate.py
├── multi_llm_area_discovery_fixed.py
├── validate_kg.py
├── utils.py
├── contracosta_kg_final.nt      # OUTPUT: Production KG
├── uko_ontology_v8.ttl          # Ontology
├── crashes.csv                  # Source data
├── norcal-latest.osm.pbf        # Source data
├── requirements.txt
├── README.md
├── models/                      # Model code
├── inference/                   # Inference code
├── llm_augmentation/            # LLM augmentation
├── georotate_training_data/     # Training data
├── georotate_output/            # Training output
├── data/                        # Dataset code
├── census/                      # Census cache
├── overture/                    # Overture data
├── switrs/                      # SWITRS cache
├── georotate_env/               # Virtual environment
└── OLD VERSIONS/                # Archived old files
```
