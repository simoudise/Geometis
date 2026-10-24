"""
Scenario 2: Transit Equity Analysis for Richmond

Evaluates whether transit service adequately serves vulnerable populations
in Richmond, identifying service gaps and prioritizing improvements.

Copyright (c) 2026 Synapse Partners, LLC
"""

SCENARIO = {
    "name": "Transit Equity Analysis for Richmond",
    "objective": "Evaluate transit access equity and identify service gaps for vulnerable populations",
    "target_area": "Richmond",
    "steps": [
        {
            "name": "Identify Underserved Tracts",
            "description": "Find census tracts with high proportions of zero-vehicle households",
            "query_type": "sparql",
            "query": "Which census tracts in Richmond have more than 15% zero-vehicle households?",
            "context_key": "underserved_tracts"
        },
        {
            "name": "Map Transit Coverage",
            "description": "Find transit stops serving underserved areas",
            "query_type": "sparql",
            "query": "What transit stops are located in underserved census tracts in Richmond?",
            "context_key": "transit_stops"
        },
        {
            "name": "Assess School Transit Access",
            "description": "Find schools in underserved tracts and their transit access",
            "query_type": "sparql",
            "query": "Which schools in Richmond are in high zero-vehicle tracts and have transit stops nearby?",
            "context_key": "school_transit"
        },
        {
            "name": "Assess Healthcare Transit Access",
            "description": "Find healthcare facilities in underserved tracts",
            "query_type": "sparql",
            "query": "Which healthcare facilities in Richmond are in underserved areas with limited transit?",
            "context_key": "healthcare_transit"
        },
        {
            "name": "Find Similar Tracts",
            "description": "Identify tracts with similar demographic/transit profiles across all cities",
            "query_type": "similarity",
            "query": "Find census tracts similar to Richmond's underserved tracts",
            "context_key": "similar_tracts"
        },
        {
            "name": "Cluster by Access Pattern",
            "description": "Group tracts into access-level clusters",
            "query_type": "clustering",
            "query": "Cluster Richmond census tracts by transit access patterns",
            "context_key": "tract_clusters"
        },
        {
            "name": "Predict Service Gaps",
            "description": "Predict which facilities would benefit most from new transit connections",
            "query_type": "prediction",
            "query": "Predict which schools and healthcare facilities in Richmond need better transit connections",
            "context_key": "predicted_gaps"
        }
    ]
}


# Additional SPARQL templates needed for this scenario
SPARQL_TEMPLATES = {
    "tracts_zero_vehicle": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?tract ?pctZeroVehicle ?totalPop ?medianIncome WHERE {{
            ?tract a uko:CensusTract .
            ?tract uko:tractInCity <urn:urban-kg:entity/osm/city/{city}> .
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            OPTIONAL {{ ?tract uko:totalPopulation ?totalPop }}
            OPTIONAL {{ ?tract uko:medianHouseholdIncome ?medianIncome }}
            FILTER(?pctZeroVehicle > {threshold})
        }}
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    """,
    
    "transit_in_tracts": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?stop ?stopName ?tract ?pctZeroVehicle WHERE {{
            ?stop a uko:TransitStop .
            ?stop rdfs:label ?stopName .
            ?stop uko:inCensusTract ?tract .
            ?tract uko:tractInCity <urn:urban-kg:entity/osm/city/{city}> .
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            FILTER(?pctZeroVehicle > {threshold})
        }}
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    """,
    
    "schools_transit_access": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?school ?schoolName ?tract ?pctZeroVehicle ?transitStop ?stopName WHERE {{
            ?school a uko:School .
            ?school rdfs:label ?schoolName .
            ?school uko:partOf <urn:urban-kg:entity/osm/city/{city}> .
            ?school uko:inCensusTract ?tract .
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            FILTER(?pctZeroVehicle > {threshold})
            OPTIONAL {{
                ?transitStop uko:transitStopNearSchool ?school .
                ?transitStop rdfs:label ?stopName .
            }}
        }}
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    """,
    
    "healthcare_transit_access": """
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?facility ?facilityName ?facilityType ?tract ?pctZeroVehicle ?hasTransit WHERE {{
            VALUES ?facilityType {{ uko:Hospital uko:Clinic uko:Pharmacy uko:MedicalCenter }}
            ?facility a ?facilityType .
            ?facility rdfs:label ?facilityName .
            ?facility uko:partOf <urn:urban-kg:entity/osm/city/{city}> .
            ?facility uko:inCensusTract ?tract .
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            FILTER(?pctZeroVehicle > {threshold})
            BIND(EXISTS {{ ?stop uko:transitStopNearHealthcare ?facility }} AS ?hasTransit)
        }}
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    """
}
