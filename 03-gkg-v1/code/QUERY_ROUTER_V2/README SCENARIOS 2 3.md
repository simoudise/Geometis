# Scenario Scripts for Contra Costa County Transportation Analysis

This folder contains three scenarios of increasing complexity for the transportation safety analysis system.

## Installation

Copy this entire `scenarios/` folder into your `QUERY_ROUTER_V2/` directory:

```bash
cp -r scenarios/ contra-costa-gkg-v1-frozen/QUERY_ROUTER_V2/
```

Your directory structure should look like:
```
QUERY_ROUTER_V2/
├── __init__.py
├── router.py
├── sparql_templates.py
├── query_classifier.py
├── entity_extractors.py
├── sparql_generator.py
├── run_scenario.py              # Scenario 1 (existing)
└── scenarios/
    ├── __init__.py
    ├── scenario_2_transit_equity.py
    ├── scenario_3_hin_planning.py
    ├── run_scenario_2.py
    ├── run_scenario_3.py
    ├── sparql_templates_additions.py
    └── README.md
```

## Required Modifications

### 1. Add SPARQL Templates

Append the contents of `sparql_templates_additions.py` to your existing `sparql_templates.py`:

```bash
cat scenarios/sparql_templates_additions.py >> sparql_templates.py
```

### 2. Fix the detach() typo in router.py

If you haven't already, fix line 336 in `router.py`:
```python
# Change from:
embeddings_list.append(self.embeddings[idx].detatch().numpy())

# To:
embeddings_list.append(self.embeddings[idx].detach().numpy())
```

## Running the Scenarios

### Scenario 1: Antioch School Safety (Existing)

```bash
cd QUERY_ROUTER_V2
python run_scenario.py \
    --kg ../contracosta_kg_final_with_safety_enhanced.nt \
    --embeddings ../georotate_output_v4/entity_embeddings.pt \
    --output antioch_school_safety_report.txt
```

### Scenario 2: Richmond Transit Equity Analysis

```bash
cd QUERY_ROUTER_V2
python scenarios/run_scenario_2.py \
    --kg ../contracosta_kg_final_with_safety_enhanced.nt \
    --embeddings ../georotate_output_v4/entity_embeddings.pt \
    --output richmond_transit_equity_report.txt
```

### Scenario 3: County-Wide HIN Planning

```bash
cd QUERY_ROUTER_V2
python scenarios/run_scenario_3.py \
    --kg ../contracosta_kg_final_with_safety_enhanced.nt \
    --embeddings ../georotate_output_v4/entity_embeddings.pt \
    --output countywide_hin_plan_report.txt
```

## Scenario Descriptions

### Scenario 1: Prioritizing Safety Improvements for Antioch Schools
**Complexity:** Basic
**Steps:** 5
**Focus:** Single city, single entity type (schools)

1. Identify High-Risk Schools (SPARQL)
2. Assess Infrastructure (SPARQL)
3. Find Similar Schools (Embeddings - Similarity)
4. Cluster by Safety Profile (Embeddings - Clustering)
5. Generate Recommendations

### Scenario 2: Transit Equity Analysis for Richmond
**Complexity:** Medium
**Steps:** 7
**Focus:** Single city, multiple entity types (tracts, transit, schools, healthcare)

1. Identify Underserved Tracts (SPARQL)
2. Map Transit Coverage (SPARQL)
3. Assess School Transit Access (SPARQL)
4. Assess Healthcare Transit Access (SPARQL)
5. Find Similar Tracts (Embeddings - Similarity)
6. Cluster by Access Pattern (Embeddings - Clustering)
7. Predict Service Gaps (Embeddings - Link Prediction)

### Scenario 3: Multi-City High Injury Network Intervention Planning
**Complexity:** High
**Steps:** 8
**Focus:** All 5 cities, multiple entity types, cross-city comparison

1. Inventory HIN Segments (SPARQL)
2. Map Vulnerable Facilities (SPARQL)
3. Assess Demographic Exposure (SPARQL)
4. Compare Infrastructure by City (SPARQL)
5. Find Similar HIN Segments (Embeddings - Similarity)
6. Cluster by Intervention Type (Embeddings - Clustering)
7. Predict Infrastructure Needs (Embeddings - Link Prediction)
8. Rank by Equity-Weighted Severity (SPARQL + Computation)

## Expected Issues and Troubleshooting

### "CensusTract clustering not supported"
The current router's clustering method defaults to School entities. Scenarios 2 and 3 work around this by using custom SPARQL queries. Full support for other entity types will be added in v2.

### "HIN segment not found in embeddings"
Some HIN segments may not have embeddings if they weren't included in the training triples. The scenario will report partial results.

### "No results for healthcare facilities"
Not all cities have healthcare facilities tagged in OSM. The query will return what's available.

## Output Files

Reports are saved as text files with sections for each step, including:
- Query executed
- Results found
- Synthesis and recommendations

Copyright (c) 2026 Synapse Partners, LLC
