# Query Router V2 - Refactored Transportation Safety Analysis

## Overview

This is a completely refactored query routing system that:
- **All SPARQL queries in one auditable file** (`sparql_templates.py`)
- **Mandatory city filters** - queries mentioning a city ALWAYS include the filter
- **Unit tests that work WITHOUT loading KG** - catch bugs quickly
- **Clean modular architecture** - easy to maintain and extend

## Quick Start

### Step 1: Run Unit Tests (No KG Required) - 5 seconds
```bash
cd query_router_v2
python tests/test_sparql_generation.py
```

All 27 tests should pass. This verifies:
- City extraction works for all 5 cities
- SPARQL generation includes city filters
- Query classification is correct

### Step 2: Run Scenario Test with Mock Data - 5 seconds
```bash
python test_scenario_quick.py
```

This runs the full Antioch school safety scenario with mock data to verify the framework works.

### Step 3: Run with Real KG
```bash
python run_scenario.py \
    --kg /path/to/contracosta_kg_final_with_safety_enhanced.nt \
    --embeddings /path/to/georotate_output_v3/entity_embeddings.pt \
    --output antioch_school_safety_report.txt
```

## File Structure

```
query_router_v2/
├── __init__.py              # Package exports
├── sparql_templates.py      # ALL SPARQL queries (audit here!)
├── entity_extractors.py     # Extract city, entity type from NL
├── query_classifier.py      # Classify query type
├── sparql_generator.py      # Map NL to SPARQL
├── router.py                # Main orchestrator
├── run_scenario.py          # Scenario runner
├── test_scenario_quick.py   # Mock scenario test
└── tests/
    └── test_sparql_generation.py  # Unit tests
```

## Key Improvements Over Previous Version

### 1. SPARQL Templates are Functions
```python
# sparql_templates.py
def schools_with_most_collisions(city: str = None, limit: int = 20) -> str:
    city_filter = get_city_filter(city, 'school')  # ALWAYS called
    return f'''...
        ?school a uko:School .
        {city_filter}  # Included when city is provided
        ...
    '''
```

### 2. City Filter is Centralized
```python
def get_city_filter(city: str, entity_var: str) -> str:
    if not city:
        return ""
    city_uri = city.replace(' ', '_')
    return f"?{entity_var} uko:partOf <urn:urban-kg:entity/osm/city/{city_uri}> ."
```

### 3. Tests Verify City Filtering
```python
def test_schools_collisions_with_city_has_filter(self):
    """CRITICAL: Schools with collisions in Antioch MUST have city filter."""
    result = generate_sparql("Which schools in Antioch have the most collisions?")
    
    assert result.city == "Antioch"
    assert result.has_city_filter == True
    assert "Antioch" in result.sparql
```

## Supported Query Types

| Query Pattern | Example | City Filtered |
|--------------|---------|---------------|
| Schools with collisions | "Schools in Antioch with most collisions" | ✓ |
| Schools near HIN | "Schools near HIN in Richmond" | ✓ |
| Count schools | "How many schools in Walnut Creek?" | ✓ |
| Infrastructure around | "Infrastructure around Lincoln Elementary" | Uses name match |
| Roads with collisions | "Roads in Pittsburg with most fatal collisions" | ✓ |
| Transit near schools | "Transit stops near schools in Antioch" | ✓ |
| Collision factors | "Primary collision factors in Richmond" | ✓ |

## Scenario Definition

The Antioch School Safety Scenario has 5 steps:

1. **Identify High-Risk Schools** - KG query for schools with most collisions
2. **Assess Infrastructure** - KG query for infrastructure around top school
3. **Find Similar Schools** - Embedding similarity search
4. **Cluster by Safety Profile** - Embedding clustering
5. **Predict Needs** - Embedding link prediction

## Troubleshooting

### "No results found"
- Check the city name is spelled correctly (Antioch, not ANTIOCH)
- Verify the KG has data for that city: `grep "partOf.*Antioch" your_kg.nt | wc -l`

### Import errors
- Run from the query_router_v2 directory
- Or add to PYTHONPATH: `export PYTHONPATH=/path/to/query_router_v2:$PYTHONPATH`

### SPARQL errors
- Print the generated SPARQL: `result = generate_sparql(query); print(result.sparql)`
- Check the debug output in router.py shows city filter being applied
