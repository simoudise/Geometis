"""
SPARQL Query Templates for Geospatial Knowledge Graph

ALL SPARQL queries are defined here in one auditable place.
Every location-bound query template uses {city_filter} placeholder.

Copyright (c) 2025 Synapse Partners, LLC
"""

# =============================================================================
# PREFIXES
# =============================================================================

PREFIXES = """PREFIX uko: <urn:urban-kg:>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""

# =============================================================================
# CITY FILTER HELPERS
# =============================================================================

def get_city_filter(city: str, entity_var: str) -> str:
    """Generate city filter using partOf relationship."""
    if not city:
        return ""
    city_uri = city.replace(' ', '_')
    return f"?{entity_var} uko:partOf <urn:urban-kg:entity/osm/city/{city_uri}> ."


def get_collision_city_filter(city: str) -> str:
    """Generate city filter for collisions (uses uko:city property)."""
    if not city:
        return ""
    return f"""{{
        {{ ?collision uko:city ?cityVal . FILTER(CONTAINS(UCASE(STR(?cityVal)), "{city.upper()}")) }}
        UNION
        {{ ?collision uko:city "{city}" }}
    }}"""


# =============================================================================
# SCHOOL QUERIES
# =============================================================================

def schools_with_most_collisions(city: str = None, limit: int = 20) -> str:
    """Schools with most nearby collisions - USES CITY FILTER."""
    city_filter = get_city_filter(city, 'school')
    return f"""{PREFIXES}
SELECT ?school ?name (COUNT(?collision) as ?collisionCount) WHERE {{
    ?school a uko:School .
    {city_filter}
    ?collision uko:collisionNearSchool ?school .
    OPTIONAL {{ ?school rdfs:label ?name }}
}}
GROUP BY ?school ?name
ORDER BY DESC(?collisionCount)
LIMIT {limit}"""


def schools_near_hin(city: str = None, low_income: bool = False, limit: int = 50) -> str:
    """Schools near High Injury Network segments."""
    city_filter = get_city_filter(city, 'school')
    income_filter = ""
    if low_income:
        income_filter = "?tract uko:medianHouseholdIncome ?income . FILTER(?income < 50000)"
    
    return f"""{PREFIXES}
SELECT DISTINCT ?school ?schoolName ?hin ?hinName WHERE {{
    ?school a uko:School .
    {city_filter}
    ?school uko:schoolNearHIN ?hin .
    OPTIONAL {{ ?school rdfs:label ?schoolName }}
    OPTIONAL {{ ?hin rdfs:label ?hinName }}
    {income_filter}
}}
LIMIT {limit}"""


def find_schools(city: str, limit: int = 50) -> str:
    """Find all schools in a city."""
    city_filter = get_city_filter(city, 'school')
    return f"""{PREFIXES}
SELECT ?school ?name ?type WHERE {{
    ?school a uko:School .
    {city_filter}
    OPTIONAL {{ ?school rdfs:label ?name }}
    OPTIONAL {{ ?school rdf:type ?subtype . FILTER(?subtype != uko:School) }}
}}
LIMIT {limit}"""


def count_schools(city: str = None) -> str:
    """Count schools, optionally filtered by city."""
    city_filter = get_city_filter(city, 'school')
    return f"""{PREFIXES}
SELECT (COUNT(DISTINCT ?school) as ?count) WHERE {{
    ?school a uko:School .
    {city_filter}
}}"""


# =============================================================================
# INFRASTRUCTURE QUERIES
# =============================================================================

def infrastructure_near_entity(entity_name: str, limit: int = 50) -> str:
    """Find infrastructure near a named entity."""
    return f"""{PREFIXES}
SELECT ?entity ?entityName ?feature ?featureName ?featureType WHERE {{
    ?entity rdfs:label ?entityName .
    FILTER(CONTAINS(LCASE(?entityName), "{entity_name.lower()}"))
    ?entity uko:near ?feature .
    OPTIONAL {{ ?feature rdfs:label ?featureName }}
    OPTIONAL {{ ?feature rdf:type ?featureType }}
}}
LIMIT {limit}"""


def infrastructure_near_school(school_name: str, limit: int = 50) -> str:
    """Find infrastructure near a named school."""
    return f"""{PREFIXES}
SELECT ?school ?schoolName ?feature ?featureName ?featureType WHERE {{
    ?school a uko:School .
    ?school rdfs:label ?schoolName .
    FILTER(CONTAINS(LCASE(?schoolName), "{school_name.lower()}"))
    ?school uko:near ?feature .
    OPTIONAL {{ ?feature rdfs:label ?featureName }}
    OPTIONAL {{ ?feature rdf:type ?featureType }}
}}
LIMIT {limit}"""


# =============================================================================
# COLLISION QUERIES
# =============================================================================

def count_collisions(city: str = None, severity: str = None) -> str:
    """Count collisions with optional city and severity filter."""
    city_filter = get_collision_city_filter(city) if city else ""
    severity_filter = ""
    if severity == 'fatal':
        severity_filter = '?collision uko:collisionSeverity "fatal" .'
    elif severity == 'severe':
        severity_filter = '?collision uko:collisionSeverity ?sev . FILTER(?sev IN ("fatal", "severe_injury"))'
    
    return f"""{PREFIXES}
SELECT (COUNT(DISTINCT ?collision) as ?count) WHERE {{
    ?collision a uko:Collision .
    {severity_filter}
    {city_filter}
}}"""


def collisions_near_schools(city: str = None, severity: str = None, limit: int = 50) -> str:
    """Find collisions near schools."""
    city_filter = get_city_filter(city, 'school')
    severity_filter = ""
    if severity == 'fatal':
        severity_filter = '?collision uko:collisionSeverity "fatal" .'
    elif severity == 'severe':
        severity_filter = '?collision uko:collisionSeverity ?sev . FILTER(?sev IN ("fatal", "severe_injury"))'
    
    return f"""{PREFIXES}
SELECT ?collision ?school ?schoolName ?severity WHERE {{
    ?collision uko:collisionNearSchool ?school .
    ?school a uko:School .
    {city_filter}
    OPTIONAL {{ ?school rdfs:label ?schoolName }}
    OPTIONAL {{ ?collision uko:collisionSeverity ?severity }}
    {severity_filter}
}}
LIMIT {limit}"""


def primary_collision_factors(city: str = None, limit: int = 20) -> str:
    """Get primary collision factors with counts."""
    city_filter = get_collision_city_filter(city) if city else ""
    
    return f"""{PREFIXES}
SELECT ?factorLabel (COUNT(?collision) as ?count) WHERE {{
    ?collision a uko:Collision .
    ?collision uko:primaryCollisionFactor ?factor .
    {city_filter}
    BIND(
        IF(?factor = "A", "Unknown",
        IF(?factor = "B", "DUI",
        IF(?factor = "C", "Impeding Traffic",
        IF(?factor = "D", "Unsafe Speed",
        IF(?factor = "E", "Right-of-Way Violation",
        IF(?factor = "F", "Improper Passing",
        IF(?factor = "G", "Unsafe Lane Change",
        IF(?factor = "H", "Improper Turning",
        IF(?factor = "I", "Following Too Closely",
        IF(?factor = "J", "Pedestrian Violation",
        IF(?factor = "K", "Hazardous Parking",
        IF(?factor = "L", "Lights/Equipment",
        IF(?factor = "M", "Brakes",
        IF(?factor = "N", "Other Equipment",
        IF(?factor = "O", "Other Hazardous Violation",
        IF(?factor = "P", "Other Than Driver",
        IF(?factor = "Q", "Unsafe Starting/Backing",
        IF(?factor = "R", "Other Improper Driving",
        IF(?factor = "S", "Traffic Signals/Signs",
        IF(?factor = "-", "Not Stated",
        ?factor)))))))))))))))))))) AS ?factorLabel
    )
}}
GROUP BY ?factorLabel
ORDER BY DESC(?count)
LIMIT {limit}"""


# =============================================================================
# ROAD QUERIES
# =============================================================================

def roads_with_most_collisions(city: str = None, fatal_only: bool = False, limit: int = 20) -> str:
    """Roads with most collisions."""
    city_filter = get_city_filter(city, 'road')
    severity_filter = '?collision uko:collisionSeverity "fatal" .' if fatal_only else ""
    
    return f"""{PREFIXES}
SELECT ?road ?name (COUNT(?collision) as ?collisionCount) WHERE {{
    ?collision uko:onRoad ?road .
    {city_filter}
    {severity_filter}
    OPTIONAL {{ ?road rdfs:label ?name }}
}}
GROUP BY ?road ?name
ORDER BY DESC(?collisionCount)
LIMIT {limit}"""


# =============================================================================
# TRANSIT QUERIES
# =============================================================================

def transit_stops_near_schools(city: str = None, limit: int = 50) -> str:
    """Transit stops near schools."""
    city_filter = get_city_filter(city, 'stop')
    
    return f"""{PREFIXES}
SELECT ?stop ?stopName ?school ?schoolName WHERE {{
    ?stop a uko:BusStop .
    {city_filter}
    ?stop uko:transitStopNearSchool ?school .
    OPTIONAL {{ ?stop rdfs:label ?stopName }}
    OPTIONAL {{ ?school rdfs:label ?schoolName }}
}}
LIMIT {limit}"""


def bart_station_infrastructure(station_name: str, limit: int = 50) -> str:
    """Infrastructure around a BART station."""
    return f"""{PREFIXES}
SELECT ?station ?stationName ?feature ?featureName ?featureType WHERE {{
    ?station a uko:TrainStation .
    ?station rdfs:label ?stationName .
    FILTER(CONTAINS(LCASE(?stationName), "{station_name.lower()}"))
    ?station uko:near ?feature .
    OPTIONAL {{ ?feature rdfs:label ?featureName }}
    ?feature rdf:type ?featureType .
}}
LIMIT {limit}"""


def list_bart_stations(limit: int = 50) -> str:
    """List all BART/train stations."""
    return f"""{PREFIXES}
SELECT ?station ?stationName WHERE {{
    ?station a uko:TrainStation .
    OPTIONAL {{ ?station rdfs:label ?stationName }}
}}
LIMIT {limit}"""


# =============================================================================
# HIN (High Injury Network) QUERIES
# =============================================================================

def hin_near_schools(city: str = None, limit: int = 50) -> str:
    """HIN segments near schools."""
    city_filter = get_city_filter(city, 'school')
    
    return f"""{PREFIXES}
SELECT DISTINCT ?hin ?hinName ?school ?schoolName WHERE {{
    ?hin a uko:HighInjuryNetwork .
    ?hin uko:hinNearSchool ?school .
    ?school a uko:School .
    {city_filter}
    OPTIONAL {{ ?hin rdfs:label ?hinName }}
    OPTIONAL {{ ?school rdfs:label ?schoolName }}
}}
LIMIT {limit}"""


def hin_near_senior_centers(city: str = None, limit: int = 50) -> str:
    """HIN segments near senior centers lacking crossings."""
    city_filter = get_city_filter(city, 'seniorCenter')
    
    return f"""{PREFIXES}
SELECT ?hin ?hinName ?seniorCenter ?seniorName WHERE {{
    ?hin a uko:HighInjuryNetwork .
    ?hin uko:hinNearSeniorCenter ?seniorCenter .
    {city_filter}
    OPTIONAL {{ ?hin rdfs:label ?hinName }}
    OPTIONAL {{ ?seniorCenter rdfs:label ?seniorName }}
    FILTER NOT EXISTS {{ ?hin uko:hasCrossing ?crossing }}
}}
LIMIT {limit}"""


def find_hin(city: str = None, limit: int = 50) -> str:
    """Find HIN segments in a city."""
    city_filter = get_city_filter(city, 'hin')
    
    return f"""{PREFIXES}
SELECT DISTINCT ?hin ?name WHERE {{
    ?hin a uko:HighInjuryNetwork .
    {city_filter}
    OPTIONAL {{ ?hin rdfs:label ?name }}
}}
LIMIT {limit}"""


# =============================================================================
# CENSUS TRACT QUERIES
# =============================================================================

def tract_collision_count(city: str = None, limit: int = 20) -> str:
    """Census tracts by collision count."""
    # Tracts don't have direct partOf city, filter via collision
    city_filter = get_collision_city_filter(city) if city else ""
    
    return f"""{PREFIXES}
SELECT ?tract ?tractName (COUNT(?collision) as ?count) WHERE {{
    ?collision uko:inTract ?tract .
    {city_filter}
    OPTIONAL {{ ?tract rdfs:label ?tractName }}
}}
GROUP BY ?tract ?tractName
ORDER BY DESC(?count)
LIMIT {limit}"""


def low_income_tracts(income_threshold: int = 50000, city: str = None, limit: int = 50) -> str:
    """Find low-income census tracts."""
    city_filter = get_city_filter(city, 'tract') if city else ""
    
    return f"""{PREFIXES}
SELECT ?tract ?income WHERE {{
    ?tract a uko:CensusTract .
    ?tract uko:medianHouseholdIncome ?income .
    FILTER(?income < {income_threshold})
    {city_filter}
}}
LIMIT {limit}"""


# =============================================================================
# ENTITY LOOKUP QUERIES
# =============================================================================

def find_entity_by_name(name: str) -> str:
    """Find entity by name (partial match)."""
    return f"""{PREFIXES}
SELECT ?entity ?label WHERE {{
    ?entity rdfs:label ?label .
    FILTER(CONTAINS(LCASE(?label), "{name.lower()}"))
}}
LIMIT 10"""


def get_entity_label(uri: str) -> str:
    """Get label for an entity URI."""
    return f"""{PREFIXES}
SELECT ?label WHERE {{
    <{uri}> rdfs:label ?label .
}}
LIMIT 1"""


def get_entities_by_type(entity_type: str, limit: int = 100) -> str:
    """Get entities of a specific type."""
    return f"""{PREFIXES}
SELECT ?entity WHERE {{
    ?entity a uko:{entity_type} .
}}
LIMIT {limit}"""


# =============================================================================
# TBOX (SCHEMA) QUERIES
# =============================================================================

def list_classes() -> str:
    """List all classes in the ontology."""
    return f"""{PREFIXES}
SELECT DISTINCT ?class WHERE {{
    ?instance a ?class .
    FILTER(STRSTARTS(STR(?class), "urn:urban-kg:"))
}}
ORDER BY ?class"""


def list_relations() -> str:
    """List all relations in the ontology."""
    return f"""{PREFIXES}
SELECT DISTINCT ?relation WHERE {{
    ?s ?relation ?o .
    FILTER(STRSTARTS(STR(?relation), "urn:urban-kg:"))
}}
ORDER BY ?relation"""


# =============================================================================
# QUERY REGISTRY - Maps query types to generator functions
# =============================================================================

QUERY_REGISTRY = {
    'schools_most_collisions': schools_with_most_collisions,
    'schools_near_hin': schools_near_hin,
    'find_schools': find_schools,
    'count_schools': count_schools,
    'infrastructure_near_entity': infrastructure_near_entity,
    'infrastructure_near_school': infrastructure_near_school,
    'count_collisions': count_collisions,
    'collisions_near_schools': collisions_near_schools,
    'primary_collision_factors': primary_collision_factors,
    'roads_most_collisions': roads_with_most_collisions,
    'transit_near_schools': transit_stops_near_schools,
    'bart_infrastructure': bart_station_infrastructure,
    'list_bart_stations': list_bart_stations,
    'hin_near_schools': hin_near_schools,
    'hin_near_seniors': hin_near_senior_centers,
    'find_hin': find_hin,
    'tract_collisions': tract_collision_count,
    'low_income_tracts': low_income_tracts,
    'find_entity': find_entity_by_name,
    'entity_label': get_entity_label,
    'entities_by_type': get_entities_by_type,
    'list_classes': list_classes,
    'list_relations': list_relations,
}
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
