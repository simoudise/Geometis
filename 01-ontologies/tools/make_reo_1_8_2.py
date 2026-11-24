"""REO 1.8.1 -> 1.8.2 (release 2026-11-23b): crash-type groups and a passenger-vehicle flag on crash records.

Source: Evangelos's approval of November 23, 2026 (16:13 Pacific) of the crash-type mapping proposed at 14:35.
The eleven groups are those of Kusano et al. (2025), Traffic Injury Prevention 26(sup1):S8-S20,
doi 10.1080/15389588.2025.2499887, Figure 2. Waymo publishes the California fields it used (arXiv 2505.01515v1,
appendix Table A2) but not the code-by-code rules, so the California assignment rule is Synapse's own and is recorded
in docs/gkg-full-methodology.md; the ontology states the groups, not the rule. Run from 01-ontologies/.
"""
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("m181", pathlib.Path(__file__).with_name("make_reo_1_8_1.py"))
# reuse the Edit class without running the 1.8.1 script body
src = open(pathlib.Path(__file__).with_name("make_reo_1_8_1.py"), encoding="utf-8").read()
ns = {}
exec(src.split("\nDEP = ")[0], ns)
Edit = ns["Edit"]

e = Edit("reo_ontology_v1_8_1.ttl")
e.rep("#    Version 1.8.1 - Neurosymbolic Urban Mobility System", "#    Version 1.8.2 - Neurosymbolic Urban Mobility System")
e.rep("""#    UKO v15.8.0 ← (imported by) REO v1.8.1
#    TKO v8.5.2  ← (imported by) REO v1.8.1
#    MLO v1.8.0  ← (imported by) REO v1.8.1""", """#    UKO v15.8.0 ← (imported by) REO v1.8.2
#    TKO v8.5.2  ← (imported by) REO v1.8.2
#    MLO v1.8.0  ← (imported by) REO v1.8.2""")
e.rep("#    Change Log:\n", """#    Change Log:
#    - v1.8.2: Release 2026-11-23b (release set: UKO v15.8.0, TKO v8.5.2, MLO v1.8.0, REO v1.8.2, FKO v1.2.4).
#              Approved by Evangelos, 2026-11-23: reo:CrashTypeGroup with the eleven crash-type groups of
#              Kusano et al. (2025, Traffic Injury Prevention 26(sup1):S8-S20, Figure 2);
#              reo:incidentCrashTypeGroup (crash record to its group) and reo:involvesPassengerVehicle (a passenger
#              vehicle is among the first two parties). Both are crash-derived. The per-source assignment rule is
#              recorded in the GKG methodology, because Waymo publishes the fields it used but not the code rules.
""")
e.rep("owl:versionIRI <urn:route-event-kg:1.8.1> ;", "owl:versionIRI <urn:route-event-kg:1.8.2> ;")
e.rep("owl:priorVersion <urn:route-event-kg:1.8.0> ;", "owl:priorVersion <urn:route-event-kg:1.8.1> ;")
e.rep('dcterms:title "Route Event Ontology (REO) v1.8.1"@en ;', 'dcterms:title "Route Event Ontology (REO) v1.8.2"@en ;')
e.rep('rdfs:comment "v1.8.1 stores', 'rdfs:comment "v1.8.2 adds the eleven crash-type groups of Kusano et al. (2025) and a passenger-vehicle flag on crash records. v1.8.1 stores')
groups = [
    ("PEDESTRIAN", "Pedestrian", "A crash in which a pedestrian is one of the first two parties."),
    ("CYCLIST", "Cyclist", "A crash in which a cyclist is one of the first two parties."),
    ("MOTORCYCLE", "Motorcycle", "A crash in which a motorcycle, scooter or moped rider is one of the first two parties."),
    ("SINGLE_VEHICLE", "Single Vehicle", "A vehicle striking an object or the ground, with no second road user in transport."),
    ("SECONDARY_CRASH", "Secondary Crash", "A vehicle striking another vehicle that had already crashed. Assignable only where records describe each vehicle in a crash sequence."),
    ("V2V_BACKING", "Vehicle-to-Vehicle, Backing", "Two vehicles, at least one moving in reverse."),
    ("V2V_FRONT_TO_REAR", "Vehicle-to-Vehicle, Front-to-Rear", "Two vehicles in the same direction and lane, one striking the rear of the other."),
    ("V2V_OPPOSITE_DIRECTION", "Vehicle-to-Vehicle, Opposite Direction", "Two vehicles travelling in opposite directions, neither turning across the other's path."),
    ("V2V_INTERSECTION", "Vehicle-to-Vehicle, Intersection", "Two vehicles on crossing paths, or one turning across or into the other's path."),
    ("V2V_LATERAL", "Vehicle-to-Vehicle, Lateral", "Two vehicles in the same direction, one moving laterally into the other (lane change, merge, passing, sideswipe)."),
    ("OTHER", "All Others", "Every crash that fits no other group, including missing or unknown crash types."),
]
block = """
#################################################################
#    REO 1.8.2 (2026-11-23): crash-type groups (Kusano et al. 2025) and passenger-vehicle flag
#################################################################

reo:CrashTypeGroup rdf:type owl:Class ;
    rdfs:label "Crash Type Group"@en ;
    rdfs:comment "One of the eleven crash-type groups of Kusano et al. (2025, Traffic Injury Prevention 26(sup1):S8-S20, Figure 2), used by Waymo to compare crash rates with human benchmarks. A record's group is assigned from its source's fields by a per-source rule recorded with the build."@en .

""" + "".join(
    f'reo:CTG_{k} rdf:type owl:NamedIndividual, reo:CrashTypeGroup ;\n    rdfs:label "{lab}"@en ;\n    rdfs:comment "{c}"@en .\n\n'
    for k, lab, c in groups) + """reo:incidentCrashTypeGroup rdf:type owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain reo:HistoricalIncidentRecord ;
    rdfs:range reo:CrashTypeGroup ;
    rdfs:label "incident crash type group"@en ;
    rdfs:comment "The crash-type group of a crash record, assigned from the first two parties. Crash-derived: never an input to a crash-prediction model."@en .

reo:involvesPassengerVehicle rdf:type owl:DatatypeProperty, owl:FunctionalProperty ;
    rdfs:domain reo:HistoricalIncidentRecord ;
    rdfs:range xsd:boolean ;
    rdfs:label "involves passenger vehicle"@en ;
    rdfs:comment "True when a passenger vehicle (car, station wagon, pickup or panel truck, with or without a trailer) is among the first two parties. Approximates Waymo's restriction to vehicles of 10,000 lb gross vehicle weight rating or less, which police records do not state. Crash-derived."@en .

reo:incidentCrashTypeGroup uko:derivedFromCrashData "true"^^xsd:boolean ;
    uko:crashDerivationBasis "stated" .
reo:involvesPassengerVehicle uko:derivedFromCrashData "true"^^xsd:boolean ;
    uko:crashDerivationBasis "stated" .

"""
e.before_end("#    END OF REO v1.8.1 ONTOLOGY", block)
e.rep("#    END OF REO v1.8.1 ONTOLOGY", "#    END OF REO v1.8.2 ONTOLOGY")
e.write("reo_ontology_v1_8_2.ttl")
