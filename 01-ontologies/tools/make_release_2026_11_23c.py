"""Coordinated release 2026-11-23c: UKO 15.8.1, TKO 8.5.3, MLO 1.8.1, REO 1.8.3, FKO 1.2.5.

Source: Evangelos's approval on 2026-11-23 (18:01 Pacific) of HPMS rules A and B and the UKO 15.8.1 additions proposed
at 14:30: uko:FHWAFunctionalSystem with seven codes and uko:fhwaFunctionalSystem; the volume method
uko:VOLUME_STATE_REPORTED_AADT; and uko:volumeIsTwoWayFacilityTotal, the flag for a carriageway that carries a two-way
facility total. TKO, MLO, REO and FKO change only their imports. Run from 01-ontologies/.
"""
import pathlib
src = open(pathlib.Path(__file__).with_name("make_release_2026_11_22b.py"), encoding="utf-8").read()
ns = {}
exec(src.split("\n# ---------------- UKO")[0], ns)
Edit = ns["Edit"]
SET = "release set: UKO v15.8.1, TKO v8.5.3, MLO v1.8.1, REO v1.8.3, FKO v1.2.5"
NOTE = "Import alignment only; no term added or changed"

e = Edit("uko_ontology_v15_8.ttl")
e.rep("#    Version 15.8.0 - Neurosymbolic Urban Mobility System", "#    Version 15.8.1 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v15.8.1: Coordinated release 2026-11-23c ({SET}; Synapse Partners). Approved by Evangelos on 2026-11-23:
#               uko:FHWAFunctionalSystem (the seven FHWA functional systems, HPMS item F_SYSTEM) and
#               uko:fhwaFunctionalSystem; volume method uko:VOLUME_STATE_REPORTED_AADT; and
#               uko:volumeIsTwoWayFacilityTotal for a carriageway that carries the total of a two-way facility.
""", count=1)
e.rep("owl:versionIRI <urn:urban-kg:15.8.0> ;\n    owl:priorVersion <urn:urban-kg:15.7.0> ;",
      "owl:versionIRI <urn:urban-kg:15.8.1> ;\n    owl:priorVersion <urn:urban-kg:15.8.0> ;")
e.rep('dcterms:title "Urban Knowledge Ontology (UKO) v15.8.0"@en ;', 'dcterms:title "Urban Knowledge Ontology (UKO) v15.8.1"@en ;')
e.rep("Companion ontologies: TKO v8.5.2, MLO v1.8.0, REO v1.8.0, FKO v1.2.4 (coordinated release 2026-11-22b).",
      "Companion ontologies: TKO v8.5.3, MLO v1.8.1, REO v1.8.3, FKO v1.2.5 (coordinated release 2026-11-23c).")
e.rep('rdfs:comment "Version 15.8.0 imports the SOSA', 'rdfs:comment "Version 15.8.1 adds the FHWA functional system, a state-reported AADT method and a two-way facility flag on volume observations. Version 15.8.0 imports the SOSA')
e.before_end("#    END OF UKO v15.8.0 ONTOLOGY", open("tools/uko_15_8_1_additions.ttl", encoding="utf-8").read())
e.rep("#    END OF UKO v15.8.0 ONTOLOGY", "#    END OF UKO v15.8.1 ONTOLOGY")
e.write("uko_ontology_v15_8_1.ttl")

e = Edit("tko_ontology_v8_5_2.ttl")
e.rep("#    Version 8.5.2 - Neurosymbolic Urban Mobility System", "#    Version 8.5.3 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"#    Change Log:\n#    - v8.5.3: Coordinated release 2026-11-23c ({SET}).\n#             (1) Imports UKO v15.8.1. {NOTE}.\n", count=1)
e.rep("owl:versionIRI <urn:trip-kg:8.5.2> ;\n    owl:priorVersion <urn:trip-kg:8.5.1> ;\n    owl:imports <urn:urban-kg:15.8.0> ;",
      "owl:versionIRI <urn:trip-kg:8.5.3> ;\n    owl:priorVersion <urn:trip-kg:8.5.2> ;\n    owl:imports <urn:urban-kg:15.8.1> ;")
e.rep('dcterms:title "Trip Knowledge Ontology (TKO) v8.5.2 - Neurosymbolic Urban Mobility"@en ;',
      'dcterms:title "Trip Knowledge Ontology (TKO) v8.5.3 - Neurosymbolic Urban Mobility"@en ;')
e.rep('rdfs:comment "Version 8.5.2 imports UKO v15.8.0; no term changes.', 'rdfs:comment "Version 8.5.3 imports UKO v15.8.1; no term changes. Version 8.5.2 imports UKO v15.8.0; no term changes.')
e.rep("#    END OF TKO v8.5.2 ONTOLOGY", "#    END OF TKO v8.5.3 ONTOLOGY")
e.write("tko_ontology_v8_5_3.ttl")

e = Edit("fko_ontology_v1_2_4.ttl")
e.rep("#    Version 1.2.4 - GeoMetis Over-the-Horizon Risk Model", "#    Version 1.2.5 - GeoMetis Over-the-Horizon Risk Model")
e.rep("#    FKO imports TKO v8.5.2 because fko:hasFreightLoad has", "#    FKO imports TKO v8.5.3 because fko:hasFreightLoad has")
e.rep("#    Change Log:\n", f"#    Change Log:\n#    - v1.2.5: Coordinated release 2026-11-23c ({SET}).\n#              (1) Imports TKO v8.5.3 (and through it UKO v15.8.1). {NOTE}.\n", count=1)
e.rep("owl:versionIRI <urn:freight-kg:1.2.4> ;\n    owl:priorVersion <urn:freight-kg:1.2.3> ;\n    owl:imports <urn:trip-kg:8.5.2> ;",
      "owl:versionIRI <urn:freight-kg:1.2.5> ;\n    owl:priorVersion <urn:freight-kg:1.2.4> ;\n    owl:imports <urn:trip-kg:8.5.3> ;")
e.rep('dcterms:title "Freight Knowledge Ontology (FKO) v1.2.4"@en ;', 'dcterms:title "Freight Knowledge Ontology (FKO) v1.2.5"@en ;')
e.rep("FKO imports TKO v8.5.2 because fko:hasFreightLoad has rdfs:domain", "FKO imports TKO v8.5.3 because fko:hasFreightLoad has rdfs:domain")
e.rep('rdfs:comment "Version 1.2.4 —', 'rdfs:comment "Version 1.2.5 — coordinated-release import alignment (TKO v8.5.3, release set 2026-11-23c); no term changes. Version 1.2.4 —')
e.rep("#    END OF FKO v1.2.4 ONTOLOGY", "#    END OF FKO v1.2.5 ONTOLOGY")
e.write("fko_ontology_v1_2_5.ttl")

e = Edit("mlo_ontology_v1_8_0.ttl")
e.rep("#    Version 1.8.0 - Neurosymbolic Urban Mobility System", "#    Version 1.8.1 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"#    Change Log:\n#    - v1.8.1: Coordinated release 2026-11-23c ({SET}).\n#              (1) Imports UKO v15.8.1, TKO v8.5.3 and FKO v1.2.5. {NOTE}.\n", count=1)
e.rep("owl:versionIRI <urn:mobility-label-kg:1.8.0> ;\n    owl:priorVersion <urn:mobility-label-kg:1.7.2> ;",
      "owl:versionIRI <urn:mobility-label-kg:1.8.1> ;\n    owl:priorVersion <urn:mobility-label-kg:1.8.0> ;")
e.rep("owl:imports <urn:trip-kg:8.5.2> ;\n    owl:imports <urn:urban-kg:15.8.0> ;\n    owl:imports <urn:freight-kg:1.2.4> ;",
      "owl:imports <urn:trip-kg:8.5.3> ;\n    owl:imports <urn:urban-kg:15.8.1> ;\n    owl:imports <urn:freight-kg:1.2.5> ;")
e.rep('dcterms:title "Mobility Label Ontology (MLO) v1.8.0"@en ;', 'dcterms:title "Mobility Label Ontology (MLO) v1.8.1"@en ;')
e.rep('rdfs:comment "Version 1.8.0 adds', 'rdfs:comment "Version 1.8.1 imports UKO v15.8.1, TKO v8.5.3 and FKO v1.2.5; no term changes. Version 1.8.0 adds')
e.rep("#    END OF MLO v1.8.0 ONTOLOGY", "#    END OF MLO v1.8.1 ONTOLOGY")
e.write("mlo_ontology_v1_8_1.ttl")

e = Edit("reo_ontology_v1_8_2.ttl")
e.rep("#    Version 1.8.2 - Neurosymbolic Urban Mobility System", "#    Version 1.8.3 - Neurosymbolic Urban Mobility System")
e.rep("""#    UKO v15.8.0 ← (imported by) REO v1.8.2
#    TKO v8.5.2  ← (imported by) REO v1.8.2
#    MLO v1.8.0  ← (imported by) REO v1.8.2""", """#    UKO v15.8.1 ← (imported by) REO v1.8.3
#    TKO v8.5.3  ← (imported by) REO v1.8.3
#    MLO v1.8.1  ← (imported by) REO v1.8.3""")
e.rep("#    Change Log:\n", f"#    Change Log:\n#    - v1.8.3: Coordinated release 2026-11-23c ({SET}).\n#              (1) Imports UKO v15.8.1, TKO v8.5.3 and MLO v1.8.1. {NOTE}.\n", count=1)
e.rep("owl:versionIRI <urn:route-event-kg:1.8.2> ;\n    owl:priorVersion <urn:route-event-kg:1.8.1> ;",
      "owl:versionIRI <urn:route-event-kg:1.8.3> ;\n    owl:priorVersion <urn:route-event-kg:1.8.2> ;")
e.rep("owl:imports <urn:urban-kg:15.8.0> ;\n    owl:imports <urn:trip-kg:8.5.2> ;\n    owl:imports <urn:mobility-label-kg:1.8.0> ;",
      "owl:imports <urn:urban-kg:15.8.1> ;\n    owl:imports <urn:trip-kg:8.5.3> ;\n    owl:imports <urn:mobility-label-kg:1.8.1> ;")
e.rep('dcterms:title "Route Event Ontology (REO) v1.8.2"@en ;', 'dcterms:title "Route Event Ontology (REO) v1.8.3"@en ;')
e.rep('rdfs:comment "v1.8.2 adds', 'rdfs:comment "v1.8.3 imports UKO v15.8.1, TKO v8.5.3 and MLO v1.8.1; no term changes. v1.8.2 adds')
e.rep("#    END OF REO v1.8.2 ONTOLOGY", "#    END OF REO v1.8.3 ONTOLOGY")
e.write("reo_ontology_v1_8_3.ttl")
