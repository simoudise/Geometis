"""
Additional SPARQL Templates for Scenarios 2 and 3

Add these functions to your existing sparql_templates.py file.

Copyright (c) 2026 Synapse Partners, LLC
"""


# ============================================================================
# SCENARIO 2: TRANSIT EQUITY TEMPLATES
# ============================================================================

def find_underserved_tracts(city: str = None, threshold: float = 0.15, limit: int = 50) -> str:
    """Find census tracts with high zero-vehicle households."""
    city_filter = ""
    if city:
        city_uri = city.replace(' ', '_')
        city_filter = f"?tract uko:tractInCity <urn:urban-kg:entity/osm/city/{city_uri}> ."
    
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?tract ?pctZeroVehicle ?totalPop ?medianIncome WHERE {{
            ?tract a uko:CensusTract .
            {city_filter}
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            OPTIONAL {{ ?tract uko:totalPopulation ?totalPop }}
            OPTIONAL {{ ?tract uko:medianHouseholdIncome ?medianIncome }}
            FILTER(?pctZeroVehicle > {threshold})
        }}
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    '''


def find_transit_in_underserved_tracts(city: str = None, threshold: float = 0.15, limit: int = 100) -> str:
    """Find transit stops in underserved census tracts."""
    city_filter = ""
    if city:
        city_uri = city.replace(' ', '_')
        city_filter = f"?tract uko:tractInCity <urn:urban-kg:entity/osm/city/{city_uri}> ."
    
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?stop ?stopName ?tract ?pctZeroVehicle WHERE {{
            ?stop a uko:TransitStop .
            OPTIONAL {{ ?stop rdfs:label ?stopName }}
            ?stop uko:inCensusTract ?tract .
            {city_filter}
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            FILTER(?pctZeroVehicle > {threshold})
        }}
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    '''


def find_schools_transit_access(city: str = None, threshold: float = 0.15, limit: int = 100) -> str:
    """Find schools in underserved tracts with their transit access."""
    city_filter = ""
    if city:
        city_uri = city.replace(' ', '_')
        city_filter = f"?school uko:partOf <urn:urban-kg:entity/osm/city/{city_uri}> ."
    
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?school ?schoolName ?tract ?pctZeroVehicle 
               (COUNT(?transitStop) AS ?nearbyTransit) WHERE {{
            ?school a uko:School .
            OPTIONAL {{ ?school rdfs:label ?schoolName }}
            {city_filter}
            ?school uko:inCensusTract ?tract .
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            FILTER(?pctZeroVehicle > {threshold})
            OPTIONAL {{ ?transitStop uko:transitStopNearSchool ?school }}
        }}
        GROUP BY ?school ?schoolName ?tract ?pctZeroVehicle
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    '''


def find_healthcare_transit_access(city: str = None, threshold: float = 0.15, limit: int = 100) -> str:
    """Find healthcare facilities in underserved tracts."""
    city_filter = ""
    if city:
        city_uri = city.replace(' ', '_')
        city_filter = f"?facility uko:partOf <urn:urban-kg:entity/osm/city/{city_uri}> ."
    
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?facility ?facilityName ?facilityType ?tract ?pctZeroVehicle 
               (BOUND(?transitStop) AS ?hasTransit) WHERE {{
            VALUES ?facilityType {{ uko:Hospital uko:Clinic uko:Pharmacy }}
            ?facility a ?facilityType .
            OPTIONAL {{ ?facility rdfs:label ?facilityName }}
            {city_filter}
            ?facility uko:inCensusTract ?tract .
            ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle .
            FILTER(?pctZeroVehicle > {threshold})
            OPTIONAL {{ ?transitStop uko:transitStopNearHealthcare ?facility }}
        }}
        ORDER BY DESC(?pctZeroVehicle)
        LIMIT {limit}
    '''


def find_census_tracts(city: str = None, limit: int = 500) -> str:
    """Find all census tracts, optionally filtered by city."""
    city_filter = ""
    if city:
        city_uri = city.replace(' ', '_')
        city_filter = f"?tract uko:tractInCity <urn:urban-kg:entity/osm/city/{city_uri}> ."
    
    return f'''
        PREFIX uko: <urn:urban-kg:>
        
        SELECT ?tract WHERE {{
            ?tract a uko:CensusTract .
            {city_filter}
        }}
        LIMIT {limit}
    '''


# ============================================================================
# SCENARIO 3: HIN PLANNING TEMPLATES
# ============================================================================

def find_hin_segments(city: str = None, limit: int = 200) -> str:
    """Find all HIN segments with collision counts."""
    city_filter = ""
    if city:
        city_uri = city.replace(' ', '_')
        city_filter = f"?hin uko:inCity <urn:urban-kg:entity/osm/city/{city_uri}> ."
    
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?city (COUNT(?collision) AS ?collisionCount) WHERE {{
            ?hin a uko:HighInjuryNetwork .
            {city_filter}
            OPTIONAL {{
                ?hin uko:inCity ?cityEntity .
                ?cityEntity rdfs:label ?city .
            }}
            OPTIONAL {{ ?collision uko:contributesToHIN ?hin }}
        }}
        GROUP BY ?hin ?city
        ORDER BY DESC(?collisionCount)
        LIMIT {limit}
    '''


def find_hin_all_cities(limit: int = 500) -> str:
    """Find HIN segments across all cities."""
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?city (COUNT(?collision) AS ?collisionCount) WHERE {{
            ?hin a uko:HighInjuryNetwork .
            ?hin uko:inCity ?cityEntity .
            ?cityEntity rdfs:label ?city .
            OPTIONAL {{ ?collision uko:contributesToHIN ?hin }}
        }}
        GROUP BY ?hin ?city
        ORDER BY DESC(?collisionCount)
        LIMIT {limit}
    '''


def find_hin_vulnerable_facilities(limit: int = 300) -> str:
    """Find vulnerable facilities near HIN segments."""
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?facilityType ?facility ?facilityName WHERE {{
            ?hin a uko:HighInjuryNetwork .
            {{
                ?hin uko:hinNearSchool ?facility .
                BIND("School" AS ?facilityType)
            }} UNION {{
                ?hin uko:hinNearSeniorCenter ?facility .
                BIND("SeniorCenter" AS ?facilityType)
            }} UNION {{
                ?hin uko:hinNearTransit ?facility .
                BIND("TransitStop" AS ?facilityType)
            }}
            OPTIONAL {{ ?facility rdfs:label ?facilityName }}
        }}
        ORDER BY ?hin ?facilityType
        LIMIT {limit}
    '''


def find_hin_demographics(limit: int = 200) -> str:
    """Find HIN segments with census tract demographics."""
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?tract ?city ?medianIncome ?pctZeroVehicle WHERE {{
            ?hin a uko:HighInjuryNetwork .
            ?hin uko:hinInTract ?tract .
            OPTIONAL {{
                ?tract uko:tractInCity ?cityEntity .
                ?cityEntity rdfs:label ?city .
            }}
            OPTIONAL {{ ?tract uko:medianHouseholdIncome ?medianIncome }}
            OPTIONAL {{ ?tract uko:pctZeroVehicleHouseholds ?pctZeroVehicle }}
        }}
        ORDER BY ?medianIncome
        LIMIT {limit}
    '''


def compare_hin_infrastructure_by_city() -> str:
    """Compare HIN infrastructure across cities."""
    return '''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?city 
               (COUNT(DISTINCT ?hin) AS ?hinSegments)
               (COUNT(DISTINCT ?sidewalk) AS ?sidewalks)
               (COUNT(DISTINCT ?crossing) AS ?crossings)
               (COUNT(DISTINCT ?bikeLane) AS ?bikeLanes)
        WHERE {
            ?hin a uko:HighInjuryNetwork .
            ?hin uko:inCity ?cityEntity .
            ?cityEntity rdfs:label ?city .
            OPTIONAL { 
                ?road uko:inHighInjuryNetwork ?hin . 
                ?road uko:hasSidewalk ?sidewalk 
            }
            OPTIONAL { 
                ?road uko:inHighInjuryNetwork ?hin . 
                ?road uko:hasCrossing ?crossing 
            }
            OPTIONAL { 
                ?road uko:inHighInjuryNetwork ?hin . 
                ?road uko:hasBikeLane ?bikeLane 
            }
        }
        GROUP BY ?city
        ORDER BY ?city
    '''


def find_hin_priority_ranking(limit: int = 50) -> str:
    """Rank HIN segments by collision count and vulnerable facilities."""
    return f'''
        PREFIX uko: <urn:urban-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?hin ?city 
               (COUNT(DISTINCT ?collision) AS ?collisions) 
               (COUNT(DISTINCT ?school) AS ?nearSchools)
               (COUNT(DISTINCT ?senior) AS ?nearSenior)
        WHERE {{
            ?hin a uko:HighInjuryNetwork .
            ?hin uko:inCity ?cityEntity .
            ?cityEntity rdfs:label ?city .
            OPTIONAL {{ ?collision uko:contributesToHIN ?hin }}
            OPTIONAL {{ ?hin uko:hinNearSchool ?school }}
            OPTIONAL {{ ?hin uko:hinNearSeniorCenter ?senior }}
        }}
        GROUP BY ?hin ?city
        ORDER BY DESC(?collisions) DESC(?nearSchools)
        LIMIT {limit}
    '''
