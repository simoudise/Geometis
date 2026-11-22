"""Coordinated release 2026-11-22: TKO 8.5.1, MLO 1.7.2, REO 1.7.0, FKO 1.2.3, aligned to UKO 15.7.0.

Why the companions change: each one imports UKO by version IRI, directly (TKO, MLO, REO) or through TKO (FKO), so
a UKO release forces a new import and therefore a new version of each. None of them uses a UKO term whose meaning
15.7 narrowed; 15.7 widens domains, adds two subclass axioms and adds new terms. One TKO comment cited the old
domain of uko:hasDataSource and is corrected. REO also takes item O1 of the ontology sufficiency audit, part 1
(2026-11-22): a crash-to-segment relation, a common severity scale with a per-state mapping table and source-neutral
crash fields, so REO becomes 1.7.0. Each change is a checked replacement. Run from 01-ontologies/.
"""
SET = "release set: UKO v15.7.0, TKO v8.5.1, MLO v1.7.2, REO v1.7.0, FKO v1.2.3"


class Edit:
    def __init__(self, src):
        self.s = open(src, encoding="utf-8").read()

    def rep(self, old, new, count=1):
        n = self.s.count(old)
        if n != count:
            raise SystemExit(f"expected {count}, found {n}: {old[:90]!r}")
        self.s = self.s.replace(old, new)

    def write(self, dst):
        open(dst, "w", encoding="utf-8").write(self.s)
        print("wrote", dst)


NOTE = "Import alignment only; no term added or changed"

# ---------------- TKO 8.5.0 -> 8.5.1
e = Edit("tko_ontology_v8_5.ttl")
e.rep("#    Version 8.5.0 - Neurosymbolic Urban Mobility System", "#    Version 8.5.1 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v8.5.1: Coordinated release 2026-11-22 ({SET}).
#             (1) Imports UKO v15.7.0.
#             (2) Corrects the comment on tko:hasTripDataSource: UKO 15.7 widened the domain of
#                 uko:hasDataSource to owl:Thing, so a trip may also carry uko:hasDataSource;
#                 tko:hasTripDataSource keeps the Stage 1 provenance class. No term added or changed.
""")
e.rep("owl:versionIRI <urn:trip-kg:8.5.0> ;\n    owl:priorVersion <urn:trip-kg:8.4.0> ;\n    owl:imports <urn:urban-kg:15.6.0> ;",
      "owl:versionIRI <urn:trip-kg:8.5.1> ;\n    owl:priorVersion <urn:trip-kg:8.5.0> ;\n    owl:imports <urn:urban-kg:15.7.0> ;")
e.rep('dcterms:title "Trip Knowledge Ontology (TKO) v8.5.0 - Neurosymbolic Urban Mobility"@en ;',
      'dcterms:title "Trip Knowledge Ontology (TKO) v8.5.1 - Neurosymbolic Urban Mobility"@en ;')
e.rep('rdfs:comment "Version 8.5.0 aligns TKO', 'rdfs:comment "Version 8.5.1 imports UKO v15.7.0 and corrects one comment. Version 8.5.0 aligns TKO')
e.rep("uko:hasDataSource cannot serve this role because its rdfs:domain is uko:GeographicFeature and a trip is not one.",
      "This property records the trip corpus's provenance class (tko:TripDataSource), which Stage 1 policies and MLO "
      "admissibility rules test. uko:hasDataSource (domain owl:Thing since UKO 15.7) may also name the source release of "
      "a trip, but it does not carry the provenance class.")
e.rep("#    END OF TKO v8.5.0 ONTOLOGY", "#    END OF TKO v8.5.1 ONTOLOGY")
e.write("tko_ontology_v8_5_1.ttl")

# ---------------- MLO 1.7.1 -> 1.7.2
e = Edit("mlo_ontology_v1_7_1.ttl")
e.rep("#    Version 1.7.1 - Neurosymbolic Urban Mobility System", "#    Version 1.7.2 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.7.2: Coordinated release 2026-11-22 ({SET}).
#              (1) Imports UKO v15.7.0, TKO v8.5.1 and FKO v1.2.3. {NOTE}.
""")
e.rep("owl:versionIRI <urn:mobility-label-kg:1.7.1> ;\n    owl:priorVersion <urn:mobility-label-kg:1.7.0> ;",
      "owl:versionIRI <urn:mobility-label-kg:1.7.2> ;\n    owl:priorVersion <urn:mobility-label-kg:1.7.1> ;")
e.rep("owl:imports <urn:trip-kg:8.5.0> ;\n    owl:imports <urn:urban-kg:15.6.0> ;\n    owl:imports <urn:freight-kg:1.2.2> ;",
      "owl:imports <urn:trip-kg:8.5.1> ;\n    owl:imports <urn:urban-kg:15.7.0> ;\n    owl:imports <urn:freight-kg:1.2.3> ;")
e.rep('dcterms:title "Mobility Label Ontology (MLO) v1.7.1"@en ;', 'dcterms:title "Mobility Label Ontology (MLO) v1.7.2"@en ;')
e.rep('rdfs:comment "Version 1.7.1 aligns MLO', 'rdfs:comment "Version 1.7.2 imports UKO v15.7.0, TKO v8.5.1 and FKO v1.2.3; no term changes. Version 1.7.1 aligns MLO')
e.rep("#    END OF MLO v1.7.1 ONTOLOGY", "#    END OF MLO v1.7.2 ONTOLOGY")
e.write("mlo_ontology_v1_7_2.ttl")

# ---------------- REO 1.6.2 -> 1.7.0 (O1)
import re
import rdflib
e = Edit("reo_ontology_v1_6_2.ttl")
e.rep("#    Version 1.6.2 - Neurosymbolic Urban Mobility System", "#    Version 1.7.0 - Neurosymbolic Urban Mobility System")
e.rep("""#    Import graph (acyclic):
#    UKO v15.5.0 ← (imported by) REO v1.6.1
#    TKO v8.4.0  ← (imported by) REO v1.6.1
#    MLO v1.7.0  ← (imported by) REO v1.6.1""", """#    Import graph (acyclic):
#    UKO v15.7.0 ← (imported by) REO v1.7.0
#    TKO v8.5.1  ← (imported by) REO v1.7.0
#    MLO v1.7.2  ← (imported by) REO v1.7.0""")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.7.0: Coordinated release 2026-11-22 ({SET}).
#              (1) Imports UKO v15.7.0, TKO v8.5.1 and MLO v1.7.2.
#              Item O1 of the ontology sufficiency audit, part 1 (2026-11-22, section 4):
#              (2) reo:onRoadSegment links a historical incident record to the road segment it
#                  occurred on, for midblock crashes and crashes near an intersection alike.
#                  reo:affectsSegment cannot serve: its domain is reo:Event, and a historical
#                  record is not an event. The old class comment named reo:affectsSegment and is
#                  corrected.
#              (3) A common severity scale: reo:KABCOSeverity with the five KABCO individuals
#                  (K fatal, A suspected serious injury, B suspected minor injury, C possible
#                  injury, O no apparent injury) and reo:hasKABCOSeverity (crash level: the most
#                  severe injury in the crash).
#              (4) A per-state mapping table: reo:SeverityCodeMapping individuals that map a
#                  source system's severity code to KABCO. California SWITRS COLLISION_SEVERITY
#                  codes 1, 2, 3, 4 and 0 are included; other states add their rows.
#              (5) Source-neutral crash fields: the HistoricalIncidentRecord fields keep their
#                  names; their comments now name the California SWITRS field as one mapping,
#                  reo:incidentState records the state, and reo:sourceSegmentKey and
#                  reo:sourceIntersectionKey generalize the San Francisco CNN keys (now their
#                  subproperties).
#              (6) Crash-derived marks: reo:HistoricalIncidentRecord and every property whose
#                  domain it is carry uko:derivedFromCrashData, so exports for crash-prediction
#                  tests drop them by rule.
#              Not included: a class for police-reported incidents other than collisions (audit
#              question T3-9), which waits for Evangelos's decision on the outcome scope.
""")
e.rep("owl:versionIRI <urn:route-event-kg:1.6.2> ;\n    owl:priorVersion <urn:route-event-kg:1.6.1> ;",
      "owl:versionIRI <urn:route-event-kg:1.7.0> ;\n    owl:priorVersion <urn:route-event-kg:1.6.2> ;")
e.rep("owl:imports <urn:urban-kg:15.6.0> ;\n    owl:imports <urn:trip-kg:8.5.0> ;\n    owl:imports <urn:mobility-label-kg:1.7.1> ;",
      "owl:imports <urn:urban-kg:15.7.0> ;\n    owl:imports <urn:trip-kg:8.5.1> ;\n    owl:imports <urn:mobility-label-kg:1.7.2> ;")
e.rep('dcterms:title "Route Event Ontology (REO) v1.6.2"@en ;', 'dcterms:title "Route Event Ontology (REO) v1.7.0"@en ;')
e.rep('rdfs:comment "v1.6.2 is a coordinated-release', 'rdfs:comment "v1.7.0 imports UKO v15.7.0, TKO v8.5.1 and MLO v1.7.2 and adds a crash-to-segment relation, the KABCO severity scale with a per-state mapping table, and source-neutral crash fields. v1.6.2 is a coordinated-release')
e.rep("""linked to uko:RoadSegment and uko:IntersectionNode via reo:affectsSegment and reo:atIntersectionNode.""",
      """linked to uko:RoadSegment and uko:IntersectionNode via reo:onRoadSegment (from REO 1.7.0) and reo:atIntersectionNode. Field comments name the California SWITRS source field as the reference mapping; adapters for other states map their own fields to the same properties, and reo:incidentSourceSystem and reo:incidentState say which mapping applies.""")
k = e.s.count("Maps to SWITRS ")
e.s = e.s.replace("Maps to SWITRS ", "California SWITRS field: ")
if k != 21:
    raise SystemExit(f"expected 21 'Maps to SWITRS', found {k}")
e.rep("""rdfs:comment "Collision severity from SWITRS collision_severity field. Values:""",
      """rdfs:comment "Collision severity as the source system records it, kept verbatim. Compare across states with reo:hasKABCOSeverity. California SWITRS field collision_severity, values:""")
e.rep("""reo:cnnSegmentKey rdf:type owl:DatatypeProperty ;
    rdfs:domain reo:HistoricalIncidentRecord ;""", """reo:cnnSegmentKey rdf:type owl:DatatypeProperty ;
    rdfs:subPropertyOf reo:sourceSegmentKey ;
    rdfs:domain reo:HistoricalIncidentRecord ;""")
e.rep("""reo:cnnIntersectionKey rdf:type owl:DatatypeProperty ;
    rdfs:domain reo:HistoricalIncidentRecord ;""", """reo:cnnIntersectionKey rdf:type owl:DatatypeProperty ;
    rdfs:subPropertyOf reo:sourceIntersectionKey ;
    rdfs:domain reo:HistoricalIncidentRecord ;""")
g = rdflib.Graph().parse("reo_ontology_v1_6_2.ttl")
R = rdflib.Namespace("urn:route-event-kg:")
own = sorted(str(p)[len(str(R)):] for p in g.subjects(rdflib.RDFS.domain, R.HistoricalIncidentRecord))
NEW = ["onRoadSegment", "hasKABCOSeverity", "incidentState", "sourceSegmentKey", "sourceIntersectionKey"]
marks = "".join(f'reo:{t} uko:derivedFromCrashData "true"^^xsd:boolean ;\n    uko:crashDerivationBasis "stated" .\n'
                for t in ["HistoricalIncidentRecord"] + own + NEW)
O1 = open("tools/reo_1_7_0_additions.ttl", encoding="utf-8").read() + "\n### (6) Crash-derived marks ###\n\n" + marks + "\n"
e.rep("#    END OF REO v1.6.2 ONTOLOGY", "#    END OF REO v1.7.0 ONTOLOGY")
marker = "#    END OF REO v1.7.0 ONTOLOGY"
i = e.s.index(marker)
j = e.s.rfind("\n", 0, i - 1) + 1  # start of the banner line above the END marker
e.s = e.s[:j] + O1 + e.s[j:]
e.write("reo_ontology_v1_7_0.ttl")

# ---------------- FKO 1.2.2 -> 1.2.3
e = Edit("fko_ontology_v1_2_2.ttl")
e.rep("#    Version 1.2.2 - GeoMetis Over-the-Horizon Risk Model", "#    Version 1.2.3 - GeoMetis Over-the-Horizon Risk Model")
e.rep("#    FKO imports TKO v8.5.0 because fko:hasFreightLoad has", "#    FKO imports TKO v8.5.1 because fko:hasFreightLoad has")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.2.3: Coordinated release 2026-11-22 ({SET}).
#              (1) Imports TKO v8.5.1 (and through it UKO v15.7.0). {NOTE}.
""")
e.rep("owl:versionIRI <urn:freight-kg:1.2.2> ;\n    owl:priorVersion <urn:freight-kg:1.2.1> ;\n    owl:imports <urn:trip-kg:8.5.0> ;",
      "owl:versionIRI <urn:freight-kg:1.2.3> ;\n    owl:priorVersion <urn:freight-kg:1.2.2> ;\n    owl:imports <urn:trip-kg:8.5.1> ;")
e.rep('dcterms:title "Freight Knowledge Ontology (FKO) v1.2.2"@en ;', 'dcterms:title "Freight Knowledge Ontology (FKO) v1.2.3"@en ;')
e.rep("FKO imports TKO v8.5.0 because fko:hasFreightLoad", "FKO imports TKO v8.5.1 because fko:hasFreightLoad")
e.rep('rdfs:comment "Version 1.2.2 —', 'rdfs:comment "Version 1.2.3 — coordinated-release import alignment (TKO v8.5.1, release set 2026-11-22); no term changes. Version 1.2.2 —')
e.rep("#    END OF FKO v1.2.2 ONTOLOGY", "#    END OF FKO v1.2.2 ONTOLOGY".replace("1.2.2", "1.2.3"))
e.write("fko_ontology_v1_2_3.ttl")
