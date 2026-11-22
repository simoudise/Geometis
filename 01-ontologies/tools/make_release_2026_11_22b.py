"""Coordinated release 2026-11-22b: UKO 15.8.0, TKO 8.5.2, MLO 1.8.0, REO 1.8.0, FKO 1.2.4.

Source: the design note "GeoMetis ontology design note O4 O5 incidents (approved) 2026-11-22 11.50", approved by
Evangelos on November 22, 2026 (11:34 Pacific):
- UKO 15.8.0: imports the SOSA module (external/sosa.ttl, http://www.w3.org/ns/sosa/); adds uko:MeasuredValue as a
  subclass of sosa:Observation and makes uko:TrafficVolumeObservation a subclass of it; adds place statistics (O4)
  and the fingerprint (O5).
- MLO 1.8.0: adds mlo:TransferEvaluation.
- REO 1.8.0: adds police-reported incidents other than collisions, stored as monthly counts.
- TKO 8.5.2 and FKO 1.2.4: import alignment only (TKO imports UKO by version; FKO imports TKO).
Each change is a checked replacement or an appended block. Run from 01-ontologies/.
"""
SET = "release set: UKO v15.8.0, TKO v8.5.2, MLO v1.8.0, REO v1.8.0, FKO v1.2.4"
NOTE = "Import alignment only; no term added or changed"
SOSA_PREFIX = "@prefix sosa: <http://www.w3.org/ns/sosa/> .\n"


class Edit:
    def __init__(self, src):
        self.s = open(src, encoding="utf-8").read()

    def rep(self, old, new, count=1):
        n = self.s.count(old)
        if n != count:
            raise SystemExit(f"expected {count}, found {n}: {old[:90]!r}")
        self.s = self.s.replace(old, new)

    def before_end(self, marker, block):
        """Insert block before the banner line that precedes the END marker."""
        i = self.s.index(marker)
        j = self.s.rfind("\n", 0, i - 1) + 1
        self.s = self.s[:j] + block + self.s[j:]

    def write(self, dst):
        open(dst, "w", encoding="utf-8").write(self.s)
        print("wrote", dst)


# ---------------- UKO 15.7.0 -> 15.8.0
e = Edit("uko_ontology_v15_7.ttl")
e.rep("#    Version 15.7.0 - Neurosymbolic Urban Mobility System", "#    Version 15.8.0 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v15.8.0: Coordinated release 2026-11-22b ({SET}; Synapse Partners), from the design note
#               "O4 O5 incidents" that Evangelos approved on 2026-11-22.
#               (1) Imports the SOSA module (http://www.w3.org/ns/sosa/, the core of the W3C/OGC Semantic
#                   Sensor Network ontology, W3C Recommendation 2017-10-19), not the full SSN ontology.
#               (2) uko:MeasuredValue, a subclass of sosa:Observation: a number with the feature it
#                   describes, its variable, period, method, unit, margin of error, source and a
#                   crash-derived flag (uko:numericValue, uko:valueUnit, uko:marginOfError,
#                   uko:marginConfidenceLevel, uko:valueSource, uko:sourceTable, uko:periodStart,
#                   uko:periodEnd, uko:valueCrashDerived; methods as uko:EstimationProcedure individuals).
#                   uko:TrafficVolumeObservation becomes a subclass, and its properties become
#                   subproperties of the general ones, so existing volume data keeps its meaning.
#               (3) O4, place statistics: uko:PlaceStatistic, uko:statisticOf / uko:hasPlaceStatistic,
#                   uko:PlaceVariable (11 variables), uko:TravelMode (10 modes), uko:travelMode,
#                   uko:travelTimeThresholdMinutes, and uko:GridCell with uko:gridSystem,
#                   uko:gridResolution and uko:gridIndex. uko:jobAccessibility stays for existing data.
#               (4) O5, the fingerprint: uko:Fingerprint, uko:FingerprintFactor (factors 1-17 of the
#                   Fingerprint Factor Specification draft v0.1 and graded questions Q1-Q6), uko:FactorValue,
#                   uko:ReferenceSet and uko:FingerprintDistance with their properties. Factor 12 is
#                   crash-derived.
#               Deviation from the note: the period is stated as two dates (uko:periodStart, uko:periodEnd)
#               rather than a sosa:phenomenonTime interval, so that queries can filter on it; a producer may
#               state sosa:phenomenonTime as well.
""")
e.rep("@prefix prov: <http://www.w3.org/ns/prov#> .\n", "@prefix prov: <http://www.w3.org/ns/prov#> .\n" + SOSA_PREFIX)
e.rep("owl:versionIRI <urn:urban-kg:15.7.0> ;\n    owl:priorVersion <urn:urban-kg:15.6.0> ;",
      "owl:versionIRI <urn:urban-kg:15.8.0> ;\n    owl:priorVersion <urn:urban-kg:15.7.0> ;\n    owl:imports <http://www.w3.org/ns/sosa/> ;")
e.rep('dcterms:title "Urban Knowledge Ontology (UKO) v15.7.0"@en ;', 'dcterms:title "Urban Knowledge Ontology (UKO) v15.8.0"@en ;')
e.rep("Companion ontologies: TKO v8.5.1, MLO v1.7.2, REO v1.7.0, FKO v1.2.3 (coordinated release 2026-11-22).",
      "Companion ontologies: TKO v8.5.2, MLO v1.8.0, REO v1.8.0, FKO v1.2.4 (coordinated release 2026-11-22b).")
e.rep('rdfs:comment "Version 15.7.0 widens',
      'rdfs:comment "Version 15.8.0 imports the SOSA module and adds measured values (uko:MeasuredValue, a sosa:Observation), '
      'place statistics and the fingerprint. Version 15.7.0 widens')
i = e.s.index("uko:jobAccessibility rdf:type owl:DatatypeProperty ;")
j = e.s.index('"@en .', i)
e.s = e.s[:j] + (" Since UKO 15.8 the general pattern is a uko:PlaceStatistic with sosa:observedProperty uko:VAR_JOBS_REACHABLE, "
                 "uko:travelMode and uko:travelTimeThresholdMinutes, which states the mode and the time limit as values.") + e.s[j:]
e.before_end("#    END OF UKO v15.7.0 ONTOLOGY", open("tools/uko_15_8_additions.ttl", encoding="utf-8").read())
e.rep("#    END OF UKO v15.7.0 ONTOLOGY", "#    END OF UKO v15.8.0 ONTOLOGY")
e.write("uko_ontology_v15_8.ttl")

# ---------------- TKO 8.5.1 -> 8.5.2
e = Edit("tko_ontology_v8_5_1.ttl")
e.rep("#    Version 8.5.1 - Neurosymbolic Urban Mobility System", "#    Version 8.5.2 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v8.5.2: Coordinated release 2026-11-22b ({SET}).
#             (1) Imports UKO v15.8.0. {NOTE}.
""")
e.rep("owl:versionIRI <urn:trip-kg:8.5.1> ;\n    owl:priorVersion <urn:trip-kg:8.5.0> ;\n    owl:imports <urn:urban-kg:15.7.0> ;",
      "owl:versionIRI <urn:trip-kg:8.5.2> ;\n    owl:priorVersion <urn:trip-kg:8.5.1> ;\n    owl:imports <urn:urban-kg:15.8.0> ;")
e.rep('dcterms:title "Trip Knowledge Ontology (TKO) v8.5.1 - Neurosymbolic Urban Mobility"@en ;',
      'dcterms:title "Trip Knowledge Ontology (TKO) v8.5.2 - Neurosymbolic Urban Mobility"@en ;')
e.rep('rdfs:comment "Version 8.5.1 imports UKO v15.7.0', 'rdfs:comment "Version 8.5.2 imports UKO v15.8.0; no term changes. Version 8.5.1 imports UKO v15.7.0')
e.rep("#    END OF TKO v8.5.1 ONTOLOGY", "#    END OF TKO v8.5.2 ONTOLOGY")
e.write("tko_ontology_v8_5_2.ttl")

# ---------------- FKO 1.2.3 -> 1.2.4
e = Edit("fko_ontology_v1_2_3.ttl")
e.rep("#    Version 1.2.3 - GeoMetis Over-the-Horizon Risk Model", "#    Version 1.2.4 - GeoMetis Over-the-Horizon Risk Model")
e.rep("#    FKO imports TKO v8.5.1 because fko:hasFreightLoad has", "#    FKO imports TKO v8.5.2 because fko:hasFreightLoad has")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.2.4: Coordinated release 2026-11-22b ({SET}).
#              (1) Imports TKO v8.5.2 (and through it UKO v15.8.0). {NOTE}.
""")
e.rep("owl:versionIRI <urn:freight-kg:1.2.3> ;\n    owl:priorVersion <urn:freight-kg:1.2.2> ;\n    owl:imports <urn:trip-kg:8.5.1> ;",
      "owl:versionIRI <urn:freight-kg:1.2.4> ;\n    owl:priorVersion <urn:freight-kg:1.2.3> ;\n    owl:imports <urn:trip-kg:8.5.2> ;")
e.rep('dcterms:title "Freight Knowledge Ontology (FKO) v1.2.3"@en ;', 'dcterms:title "Freight Knowledge Ontology (FKO) v1.2.4"@en ;')
e.rep("FKO imports TKO v8.5.1 because fko:hasFreightLoad", "FKO imports TKO v8.5.2 because fko:hasFreightLoad")
e.rep('rdfs:comment "Version 1.2.3 —', 'rdfs:comment "Version 1.2.4 — coordinated-release import alignment (TKO v8.5.2, release set 2026-11-22b); no term changes. Version 1.2.3 —')
e.rep("#    END OF FKO v1.2.3 ONTOLOGY", "#    END OF FKO v1.2.4 ONTOLOGY")
e.write("fko_ontology_v1_2_4.ttl")

# ---------------- MLO 1.7.2 -> 1.8.0
e = Edit("mlo_ontology_v1_7_2.ttl")
e.rep("#    Version 1.7.2 - Neurosymbolic Urban Mobility System", "#    Version 1.8.0 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.8.0: Coordinated release 2026-11-22b ({SET}).
#              (1) Imports UKO v15.8.0, TKO v8.5.2 and FKO v1.2.4.
#              (2) mlo:TransferEvaluation (design note "O4 O5 incidents", approved 2026-11-22): one evaluation of
#                  a model trained on a source area and applied to a target area, with mlo:sourceArea,
#                  mlo:targetArea, mlo:sourceFingerprint, mlo:targetFingerprint, mlo:evaluatesModel,
#                  mlo:featureSet, mlo:outcomeDefinition, mlo:errorMeasure, mlo:errorValue, mlo:evaluatedOn and
#                  mlo:evaluationLogRef.
""")
e.rep("owl:versionIRI <urn:mobility-label-kg:1.7.2> ;\n    owl:priorVersion <urn:mobility-label-kg:1.7.1> ;",
      "owl:versionIRI <urn:mobility-label-kg:1.8.0> ;\n    owl:priorVersion <urn:mobility-label-kg:1.7.2> ;")
e.rep("owl:imports <urn:trip-kg:8.5.1> ;\n    owl:imports <urn:urban-kg:15.7.0> ;\n    owl:imports <urn:freight-kg:1.2.3> ;",
      "owl:imports <urn:trip-kg:8.5.2> ;\n    owl:imports <urn:urban-kg:15.8.0> ;\n    owl:imports <urn:freight-kg:1.2.4> ;")
e.rep('dcterms:title "Mobility Label Ontology (MLO) v1.7.2"@en ;', 'dcterms:title "Mobility Label Ontology (MLO) v1.8.0"@en ;')
e.rep('rdfs:comment "Version 1.7.2 imports', 'rdfs:comment "Version 1.8.0 adds mlo:TransferEvaluation and imports UKO v15.8.0, TKO v8.5.2 and FKO v1.2.4. Version 1.7.2 imports')
e.before_end("#    END OF MLO v1.7.2 ONTOLOGY", open("tools/mlo_1_8_0_additions.ttl", encoding="utf-8").read())
e.rep("#    END OF MLO v1.7.2 ONTOLOGY", "#    END OF MLO v1.8.0 ONTOLOGY")
e.write("mlo_ontology_v1_8_0.ttl")

# ---------------- REO 1.7.0 -> 1.8.0
e = Edit("reo_ontology_v1_7_0.ttl")
e.rep("#    Version 1.7.0 - Neurosymbolic Urban Mobility System", "#    Version 1.8.0 - Neurosymbolic Urban Mobility System")
e.rep("""#    UKO v15.7.0 ← (imported by) REO v1.7.0
#    TKO v8.5.1  ← (imported by) REO v1.7.0
#    MLO v1.7.2  ← (imported by) REO v1.7.0""", """#    UKO v15.8.0 ← (imported by) REO v1.8.0
#    TKO v8.5.2  ← (imported by) REO v1.8.0
#    MLO v1.8.0  ← (imported by) REO v1.8.0""")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.8.0: Coordinated release 2026-11-22b ({SET}).
#              (1) Imports UKO v15.8.0, TKO v8.5.2 and MLO v1.8.0.
#              Design note "O4 O5 incidents", approved by Evangelos on 2026-11-22:
#              (2) reo:ReportedTrafficIncident is the parent of reo:HistoricalIncidentRecord (collisions) and the
#                  new reo:NonCollisionIncident.
#              (3) reo:NonCollisionCategory with four groups: curb and right-of-way violations, dangerous
#                  driving (secondary outcome only), incidents involving automated vehicles, and crash-linked
#                  records (hit-and-run reports, arrests after a collision), which are crash-derived.
#              (4) reo:recordOrigin (citation or arrest, dispatched call, incident report), reo:issuingAgency,
#                  reo:involvesAutomatedVehicle, reo:avOperator, reo:relatedCollision (crash-derived) and
#                  reo:locationPrecision.
#              (5) reo:onRoadSegment and reo:atIntersectionNode take reo:ReportedTrafficIncident as their domain.
#                  Their crash-derived marks change basis to 'conservative': they are crash-derived when the
#                  subject is a collision record.
#              (6) reo:IncidentCount, a uko:MeasuredValue: monthly counts per category, origin, place,
#                  time-of-day band (five bands) and day type (weekday or weekend). The graph stores counts only.
#              Addition to the note: the crash-linked group names the hit-and-run and arrest-after-collision
#              records as categories, so that their counts can carry uko:valueCrashDerived true.
""")
e.rep("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n", "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n" + SOSA_PREFIX)
e.rep("owl:versionIRI <urn:route-event-kg:1.7.0> ;\n    owl:priorVersion <urn:route-event-kg:1.6.2> ;",
      "owl:versionIRI <urn:route-event-kg:1.8.0> ;\n    owl:priorVersion <urn:route-event-kg:1.7.0> ;")
e.rep("owl:imports <urn:urban-kg:15.7.0> ;\n    owl:imports <urn:trip-kg:8.5.1> ;\n    owl:imports <urn:mobility-label-kg:1.7.2> ;",
      "owl:imports <urn:urban-kg:15.8.0> ;\n    owl:imports <urn:trip-kg:8.5.2> ;\n    owl:imports <urn:mobility-label-kg:1.8.0> ;")
e.rep('dcterms:title "Route Event Ontology (REO) v1.7.0"@en ;', 'dcterms:title "Route Event Ontology (REO) v1.8.0"@en ;')
e.rep('rdfs:comment "v1.7.0 imports', 'rdfs:comment "v1.8.0 adds police-reported incidents other than collisions, stored as monthly counts, and imports UKO v15.8.0, TKO v8.5.2 and MLO v1.8.0. v1.7.0 imports')
e.rep("""reo:atIntersectionNode rdf:type owl:ObjectProperty ;
    rdfs:domain reo:HistoricalIncidentRecord ;""", """reo:atIntersectionNode rdf:type owl:ObjectProperty ;
    rdfs:domain reo:ReportedTrafficIncident ;""")
e.rep("""reo:onRoadSegment rdf:type owl:ObjectProperty ;
    rdfs:domain reo:HistoricalIncidentRecord ;""", """reo:onRoadSegment rdf:type owl:ObjectProperty ;
    rdfs:domain reo:ReportedTrafficIncident ;""")
for p in ("atIntersectionNode", "onRoadSegment"):
    e.rep(f'reo:{p} uko:derivedFromCrashData "true"^^xsd:boolean ;\n    uko:crashDerivationBasis "stated" .',
          f'reo:{p} uko:derivedFromCrashData "true"^^xsd:boolean ;\n    uko:crashDerivationBasis "conservative" .')
e.before_end("#    END OF REO v1.7.0 ONTOLOGY", open("tools/reo_1_8_0_additions.ttl", encoding="utf-8").read())
e.rep("#    END OF REO v1.7.0 ONTOLOGY", "#    END OF REO v1.8.0 ONTOLOGY")
e.write("reo_ontology_v1_8_0.ttl")
