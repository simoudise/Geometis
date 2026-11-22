"""Build uko_ontology_v15_7.ttl from uko_ontology_v15_6.ttl.

Every change is a checked text replacement (each must match exactly once). The changes come from the GKG full
build of November 20, 2026: its domain/range enforcement removed 352,082 edges whose subjects UKO 15.6 did not
admit, and the build had to assert extra types for schools, hospitals and pedestrian edges. Evangelos asked for
UKO 15.7 on November 22. Run from 01-ontologies/: python tools/make_uko_15_7.py
"""
SRC, DST = "uko_ontology_v15_6.ttl", "uko_ontology_v15_7.ttl"
SET = "UKO v15.7.0, TKO v8.5.1, MLO v1.7.2, REO v1.7.0, FKO v1.2.3"
s = open(SRC, encoding="utf-8").read()


def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        raise SystemExit(f"expected {count} match(es), found {n}: {old[:80]!r}")
    s = s.replace(old, new)


# Header banner and change log
rep("#    Version 15.6.0 - Neurosymbolic Urban Mobility System", "#    Version 15.7.0 - Neurosymbolic Urban Mobility System")
rep("#    Change Log:\n", f"""#    Change Log:
#    - v15.7.0: GKG-build corrections, coordinated release 2026-11-22 (release set: {SET};
#               Synapse Partners). The GKG full build of 2026-11-20 removed 352,082 edges whose
#               subject or object UKO 15.6 did not admit; this release admits them where the data
#               is right and the declaration was too narrow.
#               (1) uko:sharesBuildingWith: domain and range uko:Building -> uko:PointOfInterest.
#                   The property links places that occupy the same building (shops, offices, a
#                   park's visitor center); most such places are not buildings themselves.
#               (2) uko:insideMall, uko:partOfChain, uko:operatedByOrg: domain uko:Building ->
#                   uko:PointOfInterest, for the same reason.
#               (3) uko:nearestTransitStop: domain uko:PointOfInterest -> uko:GeographicFeature, so
#                   that trails and other linear features can name their nearest stop.
#               (4) uko:hasDataSource: domain uko:GeographicFeature -> owl:Thing. Trips, stop times,
#                   crash records, organizations and routing constraints also come from a data
#                   source. tko:hasTripDataSource keeps its own role (Stage 1 provenance class).
#               (5) uko:pathThroughCommonSpace: domain uko:PedestrianInfrastructure -> the union of
#                   uko:PedestrianInfrastructure, uko:PedestrianNetworkEdge, uko:Trail and
#                   uko:Cycleway, the edge types of the walking and cycling network.
#               (6) uko:constrainsSegment: domain uko:OperationalRoutingConstraint -> the union of
#                   uko:OperationalRoutingConstraint and uko:TruckRoutingConstraint. UKO keeps the
#                   two hierarchies apart (operational constraints are not dimension limits), but
#                   both attach to segments.
#               (7) uko:School is a uko:ChildFacility (and so a uko:VulnerablePopulationFacility);
#                   uko:Hospital is a uko:VulnerablePopulationFacility (Evangelos's decision B1,
#                   2026-11-20: schools and hospitals count as vulnerable-population facilities).
#               Items from the ontology sufficiency audit, part 1 (2026-11-22, section 4), which
#               Evangelos asked to include in 15.7:
#               (8) O2, intersection control: uko:IntersectionControlType with seven individuals
#                   (signal, roundabout, all-way stop, minor-road stop, yield, uncontrolled,
#                   unknown) and uko:hasControlType on uko:IntersectionNode and uko:Intersection.
#                   uko:SignalizedIntersection, uko:StopControlledIntersection and uko:Roundabout
#                   stay under uko:Intersection; their comments point to the control type, so a
#                   GKG node can state its control without becoming a uko:Intersection.
#               (9) O3, exposure: uko:TrafficVolumeObservation (a count or estimate of motor
#                   vehicles, trucks, pedestrians or cyclists on a segment, edge or intersection
#                   for a stated period) with uko:hasVolumeObservation, uko:volumeMode,
#                   uko:volumeStatistic, uko:volumeValue, uko:volumePeriodStart,
#                   uko:volumePeriodEnd, uko:volumeMethod, uko:volumeDirection and
#                   uko:volumeSource, and the individuals of uko:VolumeMode and uko:VolumeMethod.
#               (10) O12, smaller additions: uko:maxGradePercent (numeric peak absolute grade
#                   beside the serialized uko:elevationGradient); uko:typicalLaneWidthM on road
#                   segments (uko:laneWidth stays on uko:Lane); uko:pavementConditionIndex and
#                   uko:pavementConditionDate; uko:isRealTime on uko:DataSource; and
#                   uko:annualEnplanements with uko:enplanementYear on uko:Airport.
""")

# Ontology header triples
rep("owl:versionIRI <urn:urban-kg:15.6.0> ;\n    owl:priorVersion <urn:urban-kg:15.5.0> ;",
    "owl:versionIRI <urn:urban-kg:15.7.0> ;\n    owl:priorVersion <urn:urban-kg:15.6.0> ;")
rep('dcterms:title "Urban Knowledge Ontology (UKO) v15.6.0"@en ;', 'dcterms:title "Urban Knowledge Ontology (UKO) v15.7.0"@en ;')
rep("Companion ontologies: TKO v8.5.0, MLO v1.7.1, REO v1.6.2, FKO v1.2.2 (coordinated release 2026-11-20).",
    "Companion ontologies: TKO v8.5.1, MLO v1.7.2, REO v1.7.0, FKO v1.2.3 (coordinated release 2026-11-22).")
rep('rdfs:comment "Version 15.6.0 declares',
    'rdfs:comment "Version 15.7.0 widens eight property domains that the GKG full build found too narrow '
    '(sharesBuildingWith, insideMall, partOfChain, operatedByOrg, nearestTransitStop, hasDataSource, '
    'pathThroughCommonSpace, constrainsSegment), makes schools and hospitals vulnerable-population '
    'facilities, and adds intersection control types, traffic and pedestrian volume observations, numeric '
    'maximum grade, lane width, pavement condition, a real-time flag on data sources and airport '
    'enplanements. Version 15.6.0 declares')

# (1) sharesBuildingWith
rep('''uko:sharesBuildingWith rdf:type owl:ObjectProperty, owl:SymmetricProperty ;
    rdfs:domain uko:Building ;
    rdfs:range uko:Building ;
    rdfs:comment "Two businesses share the same building"@en ;''',
    '''uko:sharesBuildingWith rdf:type owl:ObjectProperty, owl:SymmetricProperty ;
    rdfs:domain uko:PointOfInterest ;
    rdfs:range uko:PointOfInterest ;
    rdfs:comment "Two places occupy the same building. Domain and range were uko:Building before 15.7; most places that share a building (shops, offices, services) are not buildings themselves."@en ;''')
# (2) insideMall, operatedByOrg, partOfChain
rep('''    rdfs:subPropertyOf uko:within ;
    rdfs:domain uko:Building ;
    rdfs:range uko:ShoppingMall ;
    rdfs:comment "Business is inside a mall"@en ;''',
    '''    rdfs:subPropertyOf uko:within ;
    rdfs:domain uko:PointOfInterest ;
    rdfs:range uko:ShoppingMall ;
    rdfs:comment "A place is inside a shopping mall. Domain was uko:Building before 15.7."@en ;''')
rep('''uko:operatedByOrg rdf:type owl:ObjectProperty ;
    rdfs:domain uko:Building ;
    rdfs:range uko:Organization ;
    rdfs:comment "Building is operated by organization"@en ;''',
    '''uko:operatedByOrg rdf:type owl:ObjectProperty ;
    rdfs:domain uko:PointOfInterest ;
    rdfs:range uko:Organization ;
    rdfs:comment "A place is operated by an organization. Domain was uko:Building before 15.7."@en ;''')
rep('''uko:partOfChain rdf:type owl:ObjectProperty ;
    rdfs:domain uko:Building ;
    rdfs:range uko:Organization ;
    rdfs:comment "Building is part of a chain"@en ;''',
    '''uko:partOfChain rdf:type owl:ObjectProperty ;
    rdfs:domain uko:PointOfInterest ;
    rdfs:range uko:Organization ;
    rdfs:comment "A place is one branch of a chain (brand). Domain was uko:Building before 15.7."@en ;''')
# (3) nearestTransitStop
rep('''uko:nearestTransitStop rdf:type owl:ObjectProperty ;
    rdfs:domain uko:PointOfInterest ;
    rdfs:range uko:TransitStop ;
    rdfs:comment "Nearest transit stop"@en .''',
    '''uko:nearestTransitStop rdf:type owl:ObjectProperty ;
    rdfs:domain uko:GeographicFeature ;
    rdfs:range uko:TransitStop ;
    rdfs:comment "The transit stop nearest a feature. Domain was uko:PointOfInterest before 15.7, which excluded trails and other linear features."@en .''')
# (4) hasDataSource
rep('''uko:hasDataSource rdf:type owl:ObjectProperty ;
    rdfs:domain uko:GeographicFeature ;
    rdfs:range uko:DataSource ;
    rdfs:comment "Links feature to data source"@en .''',
    '''uko:hasDataSource rdf:type owl:ObjectProperty ;
    rdfs:domain owl:Thing ;
    rdfs:range uko:DataSource ;
    rdfs:comment "Links any entity (a feature, a trip, a stop time, a crash record, an organization, a constraint) to the data source release it came from. Domain was uko:GeographicFeature before 15.7. Trip-corpus provenance classes stay in tko:hasTripDataSource."@en .''')
# (5) pathThroughCommonSpace
rep('''uko:pathThroughCommonSpace rdf:type owl:ObjectProperty ;
    rdfs:domain uko:PedestrianInfrastructure ;''',
    '''uko:pathThroughCommonSpace rdf:type owl:ObjectProperty ;
    rdfs:domain [ rdf:type owl:Class ; owl:unionOf ( uko:PedestrianInfrastructure uko:PedestrianNetworkEdge uko:Trail uko:Cycleway ) ] ;''')
# (6) constrainsSegment
rep('''uko:constrainsSegment rdf:type owl:ObjectProperty ;
    rdfs:domain uko:OperationalRoutingConstraint ;''',
    '''uko:constrainsSegment rdf:type owl:ObjectProperty ;
    rdfs:domain [ rdf:type owl:Class ; owl:unionOf ( uko:OperationalRoutingConstraint uko:TruckRoutingConstraint ) ] ;''')
# (7) School and Hospital
rep('''uko:Hospital rdf:type owl:Class ;
    rdfs:subClassOf uko:HealthcareFacility ;''',
    '''uko:Hospital rdf:type owl:Class ;
    rdfs:subClassOf uko:HealthcareFacility, uko:VulnerablePopulationFacility ;''')
rep('''uko:School rdf:type owl:Class ;
    rdfs:subClassOf uko:EducationalFacility ;''',
    '''uko:School rdf:type owl:Class ;
    rdfs:subClassOf uko:EducationalFacility, uko:ChildFacility ;''')

# (8) O2: comments on the intersection control classes
for cls, old, ind in (("SignalizedIntersection", "An intersection with traffic signals", "uko:CONTROL_SIGNAL"),
                      ("StopControlledIntersection", "An intersection with stop signs", "uko:CONTROL_ALL_WAY_STOP or uko:CONTROL_MINOR_STOP"),
                      ("Roundabout", "A circular intersection", "uko:CONTROL_ROUNDABOUT")):
    rep(f'uko:{cls} rdf:type owl:Class ;\n    rdfs:subClassOf uko:Intersection ;\n    rdfs:comment "{old}"@en ;',
        f'uko:{cls} rdf:type owl:Class ;\n    rdfs:subClassOf uko:Intersection ;\n    rdfs:comment "{old}. A GKG '
        f'uko:IntersectionNode states the same fact with uko:hasControlType {ind} (UKO 15.7)."@en ;')

# (8)-(10) appended declarations
ADD = open("tools/uko_15_7_additions.ttl", encoding="utf-8").read()
rep("###############################################################################\n#    END OF UKO v15.6.0 ONTOLOGY",
    ADD + "###############################################################################\n#    END OF UKO v15.7.0 ONTOLOGY")
open(DST, "w", encoding="utf-8").write(s)
print("wrote", DST)
