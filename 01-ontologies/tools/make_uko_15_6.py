"""Build uko_ontology_v15_6.ttl from uko_ontology_v15_5.ttl.

Every change is either a checked text replacement (each must match exactly once) or a triple in the
appended "v15.6.0 additions" section. Run from 01-ontologies/: python tools/make_uko_15_6.py
"""
import rdflib
from rdflib.namespace import RDF, RDFS, OWL

SRC, DST = "uko_ontology_v15_5.ttl", "uko_ontology_v15_6.ttl"
s = open(SRC, encoding="utf-8").read()


def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        raise SystemExit(f"expected {count} match(es), found {n}: {old[:80]!r}")
    s = s.replace(old, new)


# 1. Header banner and change log
rep("#    Version 15.5.0 - Neurosymbolic Urban Mobility System",
    "#    Version 15.6.0 - Neurosymbolic Urban Mobility System")
rep("#    Change Log:\n", """#    Change Log:
#    - v15.6.0: Consistency and GKG-build release, coordinated release 2026-11-20 (release set:
#               UKO v15.6.0, TKO v8.5.0, MLO v1.7.1, REO v1.6.2, FKO v1.2.2; Synapse Partners).
#               (1) Declared seven classes and three annotation properties that 15.5 used but
#                   never declared: SpatialEntity, GeographicArea, RoadFeature,
#                   ProactiveSafetyNetwork, TimePeriod, FunctionalClassification (equivalent to
#                   RoadFunctionalClassification), and featureExtraction / featureType /
#                   featureGroup.
#               (2) Class hierarchy: GeographicFeature is now a SpatialEntity; IntersectionNode
#                   is now a GeographicFeature (it had no parent); TruckParkingFacility is a
#                   ParkingFacility; TransitAgency is an Organization; Trail is a LinearFeature
#                   (it was a CommonSpace, an areal class, although trails are lines).
#               (3) New classes: RailSegment (Overture rail segments had no class), OperaHouse,
#                   PriorityDevelopmentArea (MTC Plan Bay Area PDAs), DistanceMeasurement and
#                   RelationAssertion.
#               (4) Explicit rdfs:domain and rdfs:range on the 15 object properties that
#                   declared none (values copied from their inverse or parent property).
#               (5) Corrected comments: connectsToTransit runs from road (segment) to stop;
#                   segmentBetween names the road the sidewalk segment runs along, with the two
#                   cross streets in the new properties fromCrossStreet and toCrossStreet.
#               (6) anchorStation's domain widened to TransitOrientedDevelopment or
#                   PriorityDevelopmentArea.
#               (7) Distance to landmarks and districts: DistanceMeasurement with measuredFrom,
#                   measuredTo, hasDistanceMeasurement, straightLineDistanceM,
#                   networkWalkDistanceM, distanceMeasuredTo and insideTarget.
#               (8) Edge provenance: RelationAssertion (a reified rdf:Statement) with
#                   provenanceSource, provenanceMethod, provenanceVersion and crashDerived.
#               (9) Crash-derived terms marked with the annotation derivedFromCrashData, so that
#                   exports for crash-prediction tests can drop them by rule; terms whose basis
#                   UKO leaves unstated are marked conservatively (crashDerivationBasis).
#               (10) GTFS fares: FareProduct may hold Fares v1 rows; gtfsFaresVersion records
#                   which version a fare product came from.
#               (11) Harmonized duplicate labels on Neighborhood, District, HistoricDistrict and
#                   IndustrialDistrict (two declaration blocks gave each an untagged and an @en
#                   label).
#               (12) OWL 2 datatypes: xsd:date, xsd:time and xsd:gYear are outside the OWL 2
#                   datatype map, so OWL 2 reasoners refused to load UKO. Ranges now use the new
#                   datatypes uko:CalendarDate (YYYY-MM-DD) and uko:TimeOfDay (HH:MM or HH:MM:SS,
#                   hours up to 47 for GTFS service past midnight), both defined as patterned
#                   xsd:string, and xsd:integer for years. uko:ISODuration (ISO 8601 duration as
#                   patterned xsd:string) is defined here for the companion ontologies.
#               (13) The four general distance and travel-time properties declare rdfs:domain
#                   owl:Thing explicitly.
""")

# 2. Ontology header triples
rep("owl:versionIRI <urn:urban-kg:15.5.0> ;",
    "owl:versionIRI <urn:urban-kg:15.6.0> ;\n    owl:priorVersion <urn:urban-kg:15.5.0> ;")
rep('dcterms:title "Urban Knowledge Ontology (UKO) v15.5.0"@en ;',
    'dcterms:title "Urban Knowledge Ontology (UKO) v15.6.0"@en ;')
rep("Companion ontologies: TKO v8.4, MLO v1.7, REO v1.6.1, FKO v1.2.1 (coordinated release 2026-09-19).",
    "Companion ontologies: TKO v8.5.0, MLO v1.7.1, REO v1.6.2, FKO v1.2.2 (coordinated release 2026-11-20).")
rep('rdfs:comment "Version 15.5.0 delivers',
    'rdfs:comment "Version 15.6.0 declares every UKO term the stack uses, repairs the class hierarchy '
    '(IntersectionNode, Trail, SpatialEntity), adds rail segments, priority development areas, distance '
    'measurements to landmarks and districts, reified edge provenance, and crash-derivation annotations. '
    'Version 15.5.0 delivers')

# 3. Trail becomes linear
rep('''uko:Trail rdf:type owl:Class ;
    rdfs:subClassOf uko:CommonSpace ;
    rdfs:comment "A trail"@en ;''',
    '''uko:Trail rdf:type owl:Class ;
    rdfs:subClassOf uko:LinearFeature ;
    rdfs:comment "A trail: a linear path for walking, cycling or riding, often through a common space (see uko:hasTrailConnection and uko:pathThroughCommonSpace). Before 15.6 this class was a uko:CommonSpace, an areal class."@en ;''')

# 4. Comments that were wrong or ambiguous
rep('''    rdfs:range uko:Road ;
    rdfs:comment "Sidewalk segment between two cross streets"@en ;''',
    '''    rdfs:range uko:Road ;
    rdfs:comment "The road this sidewalk segment runs along, between two cross streets. The cross streets are given by uko:fromCrossStreet and uko:toCrossStreet (added in 15.6)."@en ;''')
rep('''    rdfs:range uko:TransitStop ;
    rdfs:comment "Road connects to transit"@en ;''',
    '''    rdfs:range uko:TransitStop ;
    rdfs:comment "Links a road (in the GKG, the road segment nearest the stop) to a transit stop it serves. Direction: road -> stop. The GeoMetis architecture v19, section 9.4, lists the reverse direction; the GKG follows this declaration."@en ;''')

# 5. anchorStation domain widened (replace the single domain with a union)
rep('''uko:anchorStation rdf:type owl:ObjectProperty ;
    rdfs:domain uko:TransitOrientedDevelopment ;''',
    '''uko:anchorStation rdf:type owl:ObjectProperty ;
    rdfs:domain [ rdf:type owl:Class ; owl:unionOf ( uko:TransitOrientedDevelopment uko:PriorityDevelopmentArea ) ] ;''')

# 6. Duplicate labels: give the second declaration blocks the same @en label
for cls in ["Neighborhood", "District", "Historic District", "Industrial District"]:
    rep(f'    rdfs:label "{cls}" ;\n', f'    rdfs:label "{cls}"@en ;\n')

# 6b. OWL 2 datatypes in ranges
import re
for old, new, want in (("xsd:date", "uko:CalendarDate", 9), ("xsd:time", "uko:TimeOfDay", 4), ("xsd:gYear", "xsd:integer", 1)):
    pat = re.compile(r"(rdfs:range )" + re.escape(old) + r"(?=\s*[;.])")
    s, k = pat.subn(r"\g<1>" + new, s)
    if k != want:
        raise SystemExit(f"{old}: expected {want} ranges, found {k}")

# 7. Closing banner
rep("#    END OF UKO v15.5.0 ONTOLOGY", "#    END OF UKO v15.6.0 ONTOLOGY")

# 8. Appended section, built partly from the 15.5 graph
g = rdflib.Graph().parse(SRC)
U = rdflib.Namespace("urn:urban-kg:")
nm = lambda x: x.n3(g.namespace_manager)
op = set(g.subjects(RDF.type, OWL.ObjectProperty))


def inherited(p, pred):
    """Domain or range a property inherits from its inverse or its parent property."""
    for q in g.objects(p, OWL.inverseOf):
        v = list(g.objects(q, RDFS.range if pred == RDFS.domain else RDFS.domain))
        if v: return v[0]
    for q in g.subjects(OWL.inverseOf, p):
        v = list(g.objects(q, RDFS.range if pred == RDFS.domain else RDFS.domain))
        if v: return v[0]
    for q in g.objects(p, RDFS.subPropertyOf):
        if (q, RDF.type, OWL.ObjectProperty) in g:
            v = list(g.objects(q, pred)) or ([inherited(q, pred)] if inherited(q, pred) else [])
            if v: return v[0]
    return None


explicit = []
for p in sorted(op, key=str):
    add = []
    for pred, word in ((RDFS.domain, "rdfs:domain"), (RDFS.range, "rdfs:range")):
        if not list(g.objects(p, pred)):
            v = inherited(p, pred)
            if v is None: raise SystemExit(f"cannot inherit {word} for {nm(p)}")
            add.append(f"    {word} {nm(v)}")
    if add:
        explicit.append(f"{nm(p)}\n" + " ;\n".join(add) + " .\n")
if len(explicit) != 15:
    raise SystemExit(f"expected 15 properties without domain or range, found {len(explicit)}")

CRASH_STATED = """HighInjuryNetwork HighInjuryNetworkBike HighInjuryNetworkMotorcycle HighInjuryNetworkPedestrian
HighInjuryNetworkVehicle HINSegmentSet HINIntersectionSet IntersectionRiskProfile SegmentRiskProfile
inHighInjuryNetwork hinSegmentOf overlapsHIN hasIntersectionRiskProfile crashRate fatalCount hinDataPeriod
injurySeverityScore severeInjuryCount incidentDataLastUpdated incidentDataSource incidentDensityScore
incidentRecordYearRange midblockIncidentCount onHIN segmentCollisionTypeDistribution segmentIncidentTimePattern
segmentPCFDistribution segmentSeverityDistribution segmentSpatialMatchMethod spatialMatchMethod
intersectionCollisionTypeDistribution intersectionCompoundConditionRiskMap intersectionIncidentCount
intersectionIncidentDataLastUpdated intersectionIncidentDensityScore intersectionIncidentRecordYearRange
intersectionPCFDistribution intersectionSeverityDistribution intersectionTimePattern
intersectionVehicleConflictDistribution""".split()
CRASH_CONSERVATIVE = """SafetyScore hasSafetyScore overallSafetyScore pedestrianSafetyScore bicycleSafetyScore
childSafetyScore seniorSafetyScore SafetyConcern hasSafetyConcern affectsRoad affectsIntersection hazardAhead
ProactiveSafetyNetwork onPSN""".split()
declared_15_5 = {str(x)[len("urn:urban-kg:"):] for x in g.subjects(RDF.type, None) if str(x).startswith("urn:urban-kg:")}
for t in CRASH_STATED + CRASH_CONSERVATIVE:
    if t not in declared_15_5 and t != "ProactiveSafetyNetwork":
        raise SystemExit("crash list names an undeclared term: " + t)

crash = "".join(f'uko:{t} uko:derivedFromCrashData "true"^^xsd:boolean ;\n    uko:crashDerivationBasis "stated" .\n'
                for t in CRASH_STATED)
crash += "".join(f'uko:{t} uko:derivedFromCrashData "true"^^xsd:boolean ;\n    uko:crashDerivationBasis "conservative" .\n'
                 for t in CRASH_CONSERVATIVE)

ADD = '''
###############################################################################
#    v15.6.0 ADDITIONS (2026-11-20)
###############################################################################

### (1) Terms used in 15.5 or by the companion ontologies but never declared ###

uko:SpatialEntity rdf:type owl:Class ;
    rdfs:label "Spatial Entity"@en ;
    rdfs:comment "Anything the GKG locates in space: every geographic feature, plus designations such as safety networks, safety concerns and navigation decision points. Used as a domain since 15.x but first declared in 15.6."@en .

uko:GeographicFeature rdfs:subClassOf uko:SpatialEntity .

uko:GeographicArea rdf:type owl:Class ;
    rdfs:subClassOf uko:ConceptualArea ;
    rdfs:label "Geographic Area"@en ;
    rdfs:comment "A named area with a boundary, such as a neighborhood or district. Used as a parent class since 15.x but first declared in 15.6."@en .

uko:RoadFeature rdf:type owl:Class ;
    rdfs:subClassOf uko:GeographicFeature ;
    rdfs:label "Road Feature"@en ;
    rdfs:comment "A feature attached to the road network, such as ADAS map content. First declared in 15.6."@en .

uko:ProactiveSafetyNetwork rdf:type owl:Class ;
    rdfs:subClassOf uko:TransportationSafetyFeature ;
    rdfs:label "Proactive Safety Network"@en ;
    rdfs:comment "Corridors designated for safety treatment from roadway risk factors (for example under the Alameda CTC HIN/PSN methodology) rather than solely from observed injuries. Range of tko:routeOnPSN; first declared in 15.6. A given network's inputs must be recorded; it is marked crash-derived conservatively."@en .

uko:TimePeriod rdf:type owl:Class ;
    rdfs:subClassOf time:TemporalEntity ;
    rdfs:label "Time Period"@en ;
    rdfs:comment "A named recurring period (for example AM peak or school arrival) used to classify trips and aggregates. Range of tko:tripTimePeriod and related TKO properties; first declared in 15.6."@en .

uko:FunctionalClassification rdf:type owl:Class ;
    owl:equivalentClass uko:RoadFunctionalClassification ;
    rdfs:label "Functional Classification"@en ;
    rdfs:comment "Alias of uko:RoadFunctionalClassification, kept because tko:dominantRoadClass uses this name. First declared in 15.6."@en .

uko:featureExtraction rdf:type owl:AnnotationProperty ;
    rdfs:label "feature extraction"@en ;
    rdfs:comment "Marks a property whose values are extracted as model features."@en .

uko:featureType rdf:type owl:AnnotationProperty ;
    rdfs:label "feature type"@en ;
    rdfs:comment "Data type of the extracted feature (for example integer or boolean)."@en .

uko:featureGroup rdf:type owl:AnnotationProperty ;
    rdfs:label "feature group"@en ;
    rdfs:comment "Feature group the extracted feature belongs to."@en .

### (2) Class hierarchy repairs ###

uko:IntersectionNode rdfs:subClassOf uko:GeographicFeature .
uko:TruckParkingFacility rdfs:subClassOf uko:ParkingFacility .
uko:TransitAgency rdfs:subClassOf uko:Organization .

### (3) New classes ###

uko:RailSegment rdf:type owl:Class ;
    rdfs:subClassOf uko:LinearFeature ;
    rdfs:label "Rail Segment"@en ;
    rdfs:comment "A piece of railway track between two connectors (Overture transportation segments of subtype rail). Rail routes (uko:RailRoute) are services that run over rail segments."@en .

uko:railClass rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:RailSegment ;
    rdfs:range xsd:string ;
    rdfs:label "rail class"@en ;
    rdfs:comment "Overture rail class, for example standard_gauge, subway, light_rail or tram."@en .

uko:OperaHouse rdf:type owl:Class ;
    rdfs:subClassOf uko:EntertainmentVenue ;
    rdfs:label "Opera House"@en ;
    rdfs:comment "A venue built for opera and related performing arts."@en .

uko:PriorityDevelopmentArea rdf:type owl:Class ;
    rdfs:subClassOf uko:District ;
    rdfs:label "Priority Development Area"@en ;
    rdfs:comment "An area nominated by a local government and adopted by the Metropolitan Transportation Commission and ABAG (Plan Bay Area) for housing and job growth near transit. Source: MTC Priority Development Areas, Plan Bay Area 2050+."@en .

### (4) Explicit domain and range (copied from the inverse or parent property) ###

''' + "\n".join(explicit) + '''
### (5) Cross streets for sidewalk segments ###

uko:fromCrossStreet rdf:type owl:ObjectProperty ;
    rdfs:domain uko:SidewalkSegment ;
    rdfs:range uko:Road ;
    rdfs:label "from cross street"@en ;
    rdfs:comment "The cross street at the start of this sidewalk segment."@en .

uko:toCrossStreet rdf:type owl:ObjectProperty ;
    rdfs:domain uko:SidewalkSegment ;
    rdfs:range uko:Road ;
    rdfs:label "to cross street"@en ;
    rdfs:comment "The cross street at the end of this sidewalk segment."@en .

### (7) Distance to landmarks and districts ###

uko:DistanceMeasurement rdf:type owl:Class ;
    rdfs:subClassOf prov:Entity ;
    rdfs:label "Distance Measurement"@en ;
    rdfs:comment "A measured distance from one spatial entity to another, typically from a place, stop or intersection to a landmark building or a district. Distances to an area are measured to its boundary and are zero inside it (see uko:distanceMeasuredTo and uko:insideTarget)."@en .

uko:hasDistanceMeasurement rdf:type owl:ObjectProperty ;
    rdfs:domain uko:SpatialEntity ;
    rdfs:range uko:DistanceMeasurement ;
    rdfs:label "has distance measurement"@en ;
    rdfs:comment "Links an entity to a distance measurement that starts from it."@en .

uko:measuredFrom rdf:type owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain uko:DistanceMeasurement ;
    rdfs:range uko:SpatialEntity ;
    rdfs:label "measured from"@en ;
    rdfs:comment "The entity the distance starts from."@en .

uko:measuredTo rdf:type owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain uko:DistanceMeasurement ;
    rdfs:range uko:SpatialEntity ;
    rdfs:label "measured to"@en ;
    rdfs:comment "The target entity: a landmark building, a district or another feature."@en .

uko:straightLineDistanceM rdf:type owl:DatatypeProperty ;
    rdfs:subPropertyOf uko:distanceInMeters ;
    rdfs:domain uko:DistanceMeasurement ;
    rdfs:range xsd:decimal ;
    rdfs:label "straight-line distance (m)"@en ;
    rdfs:comment "Straight-line distance in meters, measured in a projected coordinate system (EPSG:3310 for California)."@en .

uko:networkWalkDistanceM rdf:type owl:DatatypeProperty ;
    rdfs:subPropertyOf uko:distanceInMeters ;
    rdfs:domain uko:DistanceMeasurement ;
    rdfs:range xsd:decimal ;
    rdfs:label "network walking distance (m)"@en ;
    rdfs:comment "Shortest distance in meters over the walking network (road segments other than motorways plus pedestrian edges, joined at access points)."@en .

uko:distanceMeasuredTo rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:DistanceMeasurement ;
    rdfs:range xsd:string ;
    rdfs:label "distance measured to"@en ;
    rdfs:comment "Which part of the target the distance reaches: point, centroid, boundary or entrance."@en .

uko:insideTarget rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:DistanceMeasurement ;
    rdfs:range xsd:boolean ;
    rdfs:label "inside target"@en ;
    rdfs:comment "True when the starting entity lies inside the target area; the distance is then zero."@en .

### (8) Edge provenance ###

uko:RelationAssertion rdf:type owl:Class ;
    rdfs:subClassOf rdf:Statement ;
    rdfs:label "Relation Assertion"@en ;
    rdfs:comment "A reified GKG edge (subject, property, object) carrying its provenance: the source dataset, the method that computed it, the versions used, and whether it derives from crash or injury records."@en .

uko:provenanceSource rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:RelationAssertion ;
    rdfs:range xsd:string ;
    rdfs:label "provenance source"@en ;
    rdfs:comment "Source dataset and release, for example 'Overture 2026-10-21.0' or 'DataSF enwt-3u8m'."@en .

uko:provenanceMethod rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:RelationAssertion ;
    rdfs:range xsd:string ;
    rdfs:label "provenance method"@en ;
    rdfs:comment "Method that computed the edge, with its parameters, for example 'ST_DWithin 200 m, EPSG:3310'."@en .

uko:provenanceVersion rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:RelationAssertion ;
    rdfs:range xsd:string ;
    rdfs:label "provenance version"@en ;
    rdfs:comment "Version of the builder code (for example a git commit) and of the ontology that produced the edge."@en .

uko:crashDerived rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:RelationAssertion ;
    rdfs:range xsd:boolean ;
    rdfs:label "crash derived"@en ;
    rdfs:comment "True when the edge's value depends on crash or injury records. Exports that feed crash-prediction tests must drop every edge with this flag."@en .

### (9) Crash-derivation annotations on terms ###

uko:derivedFromCrashData rdf:type owl:AnnotationProperty ;
    rdfs:label "derived from crash data"@en ;
    rdfs:comment "Marks a class or property whose instances or values depend on crash or injury records. Exports that feed crash-prediction tests must drop such terms."@en .

uko:crashDerivationBasis rdf:type owl:AnnotationProperty ;
    rdfs:label "crash derivation basis"@en ;
    rdfs:comment "'stated' when UKO's own definition rests on crash or injury records; 'conservative' when UKO leaves the inputs unstated and the term is marked to be safe."@en .

''' + crash + '''
### (12) OWL 2 datatypes (patterned strings) ###

uko:CalendarDate rdf:type rdfs:Datatype ;
    owl:equivalentClass [ rdf:type rdfs:Datatype ;
        owl:onDatatype xsd:string ;
        owl:withRestrictions ( [ xsd:pattern "[0-9]{4}-[0-9]{2}-[0-9]{2}" ] ) ] ;
    rdfs:label "calendar date"@en ;
    rdfs:comment "A calendar date written YYYY-MM-DD (ISO 8601), with no time of day. Replaces xsd:date, which is outside the OWL 2 datatype map. Values are written as xsd:string literals in this form; OWL 2 does not allow literals typed with a defined datatype."@en .

uko:TimeOfDay rdf:type rdfs:Datatype ;
    owl:equivalentClass [ rdf:type rdfs:Datatype ;
        owl:onDatatype xsd:string ;
        owl:withRestrictions ( [ xsd:pattern "[0-4][0-9]:[0-5][0-9](:[0-5][0-9])?" ] ) ] ;
    rdfs:label "time of day"@en ;
    rdfs:comment "A local time of day written HH:MM or HH:MM:SS. Hours may exceed 23 (up to 47) for GTFS service that runs past midnight. Replaces xsd:time, which is outside the OWL 2 datatype map. Values are written as xsd:string literals in this form; OWL 2 does not allow literals typed with a defined datatype."@en .

uko:ISODuration rdf:type rdfs:Datatype ;
    owl:equivalentClass [ rdf:type rdfs:Datatype ;
        owl:onDatatype xsd:string ;
        owl:withRestrictions ( [ xsd:pattern "-?P([0-9]+Y)?([0-9]+M)?([0-9]+D)?(T([0-9]+H)?([0-9]+M)?([0-9]+([.][0-9]+)?S)?)?" ] ) ] ;
    rdfs:label "ISO 8601 duration"@en ;
    rdfs:comment "A duration written in ISO 8601 form, for example PT5M30S. Replaces xsd:duration, which is outside the OWL 2 datatype map. Values are written as xsd:string literals in this form; OWL 2 does not allow literals typed with a defined datatype."@en .

uko:distanceInMeters rdfs:domain owl:Thing .
uko:walkingTimeMinutes rdfs:domain owl:Thing .
uko:drivingTimeMinutes rdfs:domain owl:Thing .
uko:transitTimeMinutes rdfs:domain owl:Thing .

### (10) GTFS fares version ###

uko:gtfsFaresVersion rdf:type owl:DatatypeProperty ;
    rdfs:domain uko:FareProduct ;
    rdfs:range xsd:string ;
    rdfs:label "GTFS fares version"@en ;
    rdfs:comment "Which GTFS fares specification the fare product came from: 'v1' (fare_attributes.txt) or 'v2' (fare_products.txt). UKO's FareProduct follows Fares v2; v1 rows are admitted and labeled."@en .

'''
marker = "###############################################################################\n#    END OF UKO v15.6.0 ONTOLOGY"
rep(marker, ADD + marker)
open(DST, "w", encoding="utf-8").write(s)
print("wrote", DST)
