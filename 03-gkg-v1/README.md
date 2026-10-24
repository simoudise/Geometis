# Contra Costa County Geospatial Knowledge Graph

A comprehensive knowledge graph integrating OSM infrastructure, Census demographics, SWITRS collision data, and Overture POIs for five Contra Costa County cities: Walnut Creek, Pleasant Hill, Concord, Martinez, and Antioch.

## Overview

This project creates a **40M+ triple knowledge graph** that enables:
- Multi-hop reasoning across urban data domains
- Safety analysis (High Injury Network identification)
- Equity analysis (transit access in underserved areas)
- Infrastructure gap identification
- Knowledge graph embeddings for similarity and link prediction

## Data Sources

| Source | Data | Entity Types | Cost |
|--------|------|--------------|------|
| OpenStreetMap | Infrastructure | Roads, Sidewalks, Crossings, Buildings | FREE |
| US Census ACS | Demographics | Census Tracts, Block Groups | FREE |
| SWITRS/TIMS | Safety | Collisions, High Injury Network | FREE |
| Overture Maps | POIs | Schools, Healthcare, Transit, Businesses | FREE |

## Project Structure

```
contra-costa-gkg/
├── data/
│   ├── contra-costa.osm.pbf     # OSM extract
│   └── crashes.csv              # SWITRS collision data
├── ontology/
│   └── uko_ontology_v8.ttl      # Consolidated ontology (412 classes, 387 properties)
├── scripts/
│   ├── main.py                  # Main KG builder (orchestrates all steps)
│   ├── osm_handler_v2.py        # OSM parsing
│   ├── osm_to_uko_mapper_v2.py  # OSM to UKO mapping
│   ├── census_tract_loader_fast.py
│   ├── overture_poi_loader_fast.py
│   ├── switrs_safety_loader.py
│   ├── materialize_relationships.py
│   ├── multi_llm_area_discovery_fixed.py
│   ├── prepare_embeddings.py
│   └── validate_kg.py
├── georotate_kge/               # Embedding framework (see georotate_kge/README.md)
├── output/
│   └── contracosta_kg_final.nt  # Production knowledge graph
├── requirements.txt
└── README.md
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Build Knowledge Graph

**Option A: All-in-one (recommended)**
```bash
python main.py \
  --pbf_file data/contra-costa.osm.pbf \
  --output_file output/contracosta_kg.nt \
  --add_census \
  --add_pois \
  --add_safety \
  --switrs_csv data/crashes.csv
```

Then materialize cross-domain relationships:
```bash
python materialize_relationships.py \
  --input output/contracosta_kg.nt \
  --output output/contracosta_kg_final.nt
```

**Option B: Step-by-step**
```bash
# Step 1: OSM extraction
python main.py --pbf_file data/contra-costa.osm.pbf --output_file kg_base.nt

# Step 2: Add Census data
python census_tract_loader_fast.py --input kg_base.nt --output kg_census.nt

# Step 3: Add POIs  
python overture_poi_loader_fast.py --input kg_census.nt --output kg_pois.nt

# Step 4: Add Safety data
python switrs_safety_loader.py --input kg_pois.nt --csv_file data/crashes.csv

# Step 5: Materialize cross-domain relationships
python materialize_relationships.py --input kg_pois_with_safety.nt --output kg_final.nt
```

### 3. Prepare for Embedding Training

```bash
python prepare_embeddings.py \
  --input output/contracosta_kg_final.nt \
  --output_dir embeddings_data/
```

### 4. Train Embeddings

```bash
cd georotate_kge
python train_georotate.py --data_dir ../embeddings_data/
```

See `georotate_kge/README.md` for detailed embedding documentation.

---

## Knowledge Graph Statistics

| Metric | Value |
|--------|-------|
| Total Triples | ~40.3M |
| Entities | ~312K |
| Relation Types | 150+ |
| Cross-domain Links | ~212K |

### Entity Distribution

| Type | Count |
|------|-------|
| Roads | ~60K |
| Buildings/Houses | ~32K |
| POIs | ~27K |
| Sidewalks | ~6K |
| Crossings | ~13K |
| Census Tracts | ~242 |
| Collisions | ~3.5K |
| HIN Segments | ~146 |

---

## Cross-Domain Relationships

The KG includes **212K+ explicit relationships** connecting entities across data domains:

### POI ↔ Safety
- `schoolNearHIN` - Schools near High Injury Network segments
- `transitStopInHIN` - Transit stops in high-crash areas
- `seniorFacilityNearHIN` - Senior centers near dangerous roads

### POI ↔ Census
- `inCensusTract` - POIs linked to their census tract
- `transitStopServesLowIncome` - Transit stops in low-income areas

### Safety ↔ Census
- `collisionInTract` - Collisions linked to demographics
- `hinInTract` - HIN segments linked to demographics
- `tractHasHIN` - Census tracts containing HIN

### Transit ↔ POI
- `transitStopNearSchool` - Transit access for schools
- `transitStopNearHealthcare` - Transit access for healthcare

---

## Example SPARQL Queries

### Find schools near pedestrian HIN in low-income tracts
```sparql
PREFIX uko: <urn:urban-kg:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?school ?schoolName ?hin ?tract ?income WHERE {
  ?school a uko:School ;
          rdfs:label ?schoolName ;
          uko:schoolNearHIN ?hin ;
          uko:inCensusTract ?tract .
  ?hin a uko:HighInjuryNetworkPedestrian .
  ?tract uko:medianHouseholdIncome ?income .
  FILTER(?income < 60000)
}
ORDER BY ?income
```

### Find transit stops serving car-free populations
```sparql
PREFIX uko: <urn:urban-kg:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?stop ?stopName ?tract ?pctCarFree WHERE {
  ?stop a uko:TransitStop ;
        rdfs:label ?stopName ;
        uko:inCensusTract ?tract .
  ?tract uko:pctZeroVehicleHouseholds ?pctCarFree .
  FILTER(?pctCarFree > 0.10)
}
ORDER BY DESC(?pctCarFree)
```

### Count collisions by severity in each city
```sparql
PREFIX uko: <urn:urban-kg:>

SELECT ?city (COUNT(?collision) as ?total) (SUM(?fatal) as ?fatalities) 
WHERE {
  ?collision a uko:Collision ;
             uko:city ?city ;
             uko:fatalitiesCount ?fatal .
}
GROUP BY ?city
ORDER BY DESC(?total)
```

---

## Ontology (UKO v8)

The Urban Knowledge Ontology v8.0 consolidates all extensions:

| Component | Classes | Properties |
|-----------|---------|------------|
| Core (OSM) | 397 | 270 |
| Districts/Neighborhoods | +5 | +8 |
| ADAS/Safety Features | +3 | +15 |
| Census Demographics | +4 | +35 |
| Traffic Collisions | +12 | +25 |
| Cross-Domain Relations | - | +51 |
| **Total** | **412** | **387** |

---

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `main.py` | Main orchestrator - builds KG from OSM with optional enrichments | `python main.py --pbf_file X --add_census --add_pois --add_safety` |
| `census_tract_loader_fast.py` | Add Census demographics | `python census_tract_loader_fast.py --input X --output Y` |
| `overture_poi_loader_fast.py` | Add Overture POIs | `python overture_poi_loader_fast.py --input X --output Y` |
| `switrs_safety_loader.py` | Add SWITRS collisions & HIN | `python switrs_safety_loader.py --input X --csv_file Y` |
| `materialize_relationships.py` | Create cross-domain links | `python materialize_relationships.py --input X --output Y` |
| `prepare_embeddings.py` | Prepare data for embedding training | `python prepare_embeddings.py --input X --output_dir Y` |
| `validate_kg.py` | Validate KG structure | `python validate_kg.py --input X` |

---

## License

Copyright (c) 2025 Synapse Partners, LLC

## Acknowledgments

- OpenStreetMap contributors
- US Census Bureau (American Community Survey)
- California Highway Patrol (SWITRS)
- UC Berkeley SafeTREC (TIMS)
- Overture Maps Foundation
