"""
Scenario 3: Multi-City High Injury Network Intervention Planning

County-wide analysis to allocate Vision Zero funding across all five cities,
prioritizing interventions based on severity, equity, and cost-effectiveness.

Copyright (c) 2026 Synapse Partners, LLC
"""

SCENARIO = {
    "name": "Multi-City High Injury Network Intervention Planning",
    "objective": "Prioritize Vision Zero investments across Contra Costa County based on severity, vulnerable population exposure, and equity",
    "target_area": "Contra Costa County",
    "cities": ["Antioch", "Pittsburg", "Richmond", "Walnut Creek", "Pleasant Hill"],
    "steps": [
        {
            "name": "Inventory HIN Segments",
            "description": "Query all HIN segments across 5 cities with collision counts and severity",
            "query_type": "sparql",
            "query": "List all High Injury Network segments across Contra Costa County with collision counts by severity",
            "context_key": "hin_inventory"
        },
        {
            "name": "Map Vulnerable Facilities",
            "description": "For each HIN segment, find nearby schools, senior centers, hospitals, and transit stops",
            "query_type": "sparql",
            "query": "Which schools, senior centers, hospitals, and transit stops are near High Injury Network segments?",
            "context_key": "vulnerable_facilities"
        },
        {
            "name": "Assess Demographic Exposure",
            "description": "Link HIN segments to census tracts and retrieve demographics",
            "query_type": "sparql",
            "query": "What are the demographics of census tracts containing High Injury Network segments?",
            "context_key": "demographic_exposure"
        },
        {
            "name": "Compare Infrastructure by City",
            "description": "Compare existing safety infrastructure along HIN segments across cities",
            "query_type": "sparql",
            "query": "Compare sidewalks, crossings, and bike lanes along HIN segments in each city",
            "context_key": "infrastructure_comparison"
        },
        {
            "name": "Find Similar HIN Segments",
            "description": "Identify HIN segments with similar risk profiles across cities",
            "query_type": "similarity",
            "query": "Find HIN segments with similar safety profiles across all five cities",
            "context_key": "similar_segments"
        },
        {
            "name": "Cluster by Intervention Type",
            "description": "Group HIN segments into clusters suggesting similar intervention approaches",
            "query_type": "clustering",
            "query": "Cluster all HIN segments by safety profile to identify intervention categories",
            "context_key": "intervention_clusters"
        },
        {
            "name": "Predict Infrastructure Needs",
            "description": "Predict which infrastructure types would most reduce risk for each cluster",
            "query_type": "prediction",
            "query": "Predict which infrastructure improvements would most benefit each HIN segment cluster",
            "context_key": "predicted_infrastructure"
        },
        {
            "name": "Rank by Equity-Weighted Severity",
            "description": "Compute composite score combining collision severity, vulnerable facility exposure, and demographic need",
            "query_type": "sparql",
            "query": "Rank HIN segments by equity-weighted severity score combining collisions, vulnerable facilities, and low-income exposure",
            "context_key": "priority_ranking"
        }
    ]
}


# Additional SPARQL templates needed for this scenario
SPARQL_TEMPLATES = {
    "hin_inventory_all_cities": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?hinType ?city ?collisionCount ?fatalCount ?severeCount WHERE {{
            VALUES ?hinType {{ uko:HighInjuryNetworkPedestrian uko:HighInjuryNetworkBicycle uko:HighInjuryNetwork }}
            ?hin a ?hinType .
            ?hin uko:inCity ?cityEntity .
            ?cityEntity rdfs:label ?city .
            OPTIONAL {{
                SELECT ?hin (COUNT(?collision) AS ?collisionCount) 
                       (SUM(IF(?severity = "fatal", 1, 0)) AS ?fatalCount)
                       (SUM(IF(?severity = "severe", 1, 0)) AS ?severeCount)
                WHERE {{
                    ?collision uko:contributesToHIN ?hin .
                    OPTIONAL {{ ?collision uko:severity ?severity }}
                }}
                GROUP BY ?hin
            }}
        }}
        ORDER BY DESC(?fatalCount) DESC(?collisionCount)
        LIMIT {limit}
    """,
    
    "hin_vulnerable_facilities": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?facilityType ?facility ?facilityName ?city WHERE {{
            ?hin a uko:HighInjuryNetwork .
            {{
                ?hin uko:hinNearSchool ?facility .
                ?facility rdfs:label ?facilityName .
                BIND("School" AS ?facilityType)
            }} UNION {{
                ?hin uko:hinNearSeniorCenter ?facility .
                ?facility rdfs:label ?facilityName .
                BIND("SeniorCenter" AS ?facilityType)
            }} UNION {{
                ?hin uko:hinNearTransit ?facility .
                ?facility rdfs:label ?facilityName .
                BIND("TransitStop" AS ?facilityType)
            }} UNION {{
                ?facility uko:collisionNearHospital ?hin .
                ?facility rdfs:label ?facilityName .
                BIND("Hospital" AS ?facilityType)
            }}
            OPTIONAL {{
                ?facility uko:partOf ?cityEntity .
                ?cityEntity rdfs:label ?city .
            }}
        }}
        ORDER BY ?hin ?facilityType
        LIMIT {limit}
    """,
    
    "hin_demographic_exposure": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?tract ?city ?medianIncome ?pctZeroVehicle ?totalPop WHERE {{
            ?hin a uko:HighInjuryNetwork .
            ?hin uko:hinInTract ?tract .
            ?tract uko:tractInCity ?cityEntity .
            ?cityEntity rdfs:label ?city .
            OPTIONAL {{ ?tract uko:medianHouseholdIncome ?medianIncome }}
            OPTIONAL {{ ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle }}
            OPTIONAL {{ ?tract uko:totalPopulation ?totalPop }}
        }}
        ORDER BY ?medianIncome
        LIMIT {limit}
    """,
    
    "hin_infrastructure_by_city": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?city 
               (COUNT(DISTINCT ?hin) AS ?hinSegments)
               (COUNT(DISTINCT ?sidewalk) AS ?sidewalks)
               (COUNT(DISTINCT ?crossing) AS ?crossings)
               (COUNT(DISTINCT ?bikeLane) AS ?bikeLanes)
        WHERE {{
            ?hin a uko:HighInjuryNetwork .
            ?hin uko:inCity ?cityEntity .
            ?cityEntity rdfs:label ?city .
            OPTIONAL {{ ?road uko:inHighInjuryNetwork ?hin . ?road uko:hasSidewalk ?sidewalk }}
            OPTIONAL {{ ?road uko:inHighInjuryNetwork ?hin . ?road uko:hasCrossing ?crossing }}
            OPTIONAL {{ ?road uko:inHighInjuryNetwork ?hin . ?road uko:hasBikeLane ?bikeLane }}
        }}
        GROUP BY ?city
        ORDER BY ?city
    """,
    
    "hin_equity_weighted_ranking": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?city ?collisionScore ?vulnerableScore ?equityScore 
               ((?collisionScore * 0.4 + ?vulnerableScore * 0.3 + ?equityScore * 0.3) AS ?compositeScore)
        WHERE {{
            {{
                SELECT ?hin ?city 
                       (COUNT(?collision) + SUM(IF(?fatal > 0, 10, 0)) AS ?collisionScore)
                WHERE {{
                    ?hin a uko:HighInjuryNetwork .
                    ?hin uko:inCity ?cityEntity .
                    ?cityEntity rdfs:label ?city .
                    OPTIONAL {{ 
                        ?collision uko:contributesToHIN ?hin .
                        ?collision uko:fatalitiesCount ?fatal .
                    }}
                }}
                GROUP BY ?hin ?city
            }}
            {{
                SELECT ?hin (COUNT(DISTINCT ?facility) AS ?vulnerableScore)
                WHERE {{
                    ?hin a uko:HighInjuryNetwork .
                    {{?hin uko:hinNearSchool ?facility}} UNION
                    {{?hin uko:hinNearSeniorCenter ?facility}} UNION
                    {{?hin uko:hinNearTransit ?facility}}
                }}
                GROUP BY ?hin
            }}
            {{
                SELECT ?hin (AVG(IF(?income < 50000, 10, IF(?income < 75000, 5, 1))) AS ?equityScore)
                WHERE {{
                    ?hin a uko:HighInjuryNetwork .
                    ?hin uko:hinInTract ?tract .
                    ?tract uko:medianHouseholdIncome ?income .
                }}
                GROUP BY ?hin
            }}
        }}
        ORDER BY DESC(?compositeScore)
        LIMIT {limit}
    """
}
