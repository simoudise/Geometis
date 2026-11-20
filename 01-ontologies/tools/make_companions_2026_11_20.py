"""Coordinated release 2026-11-20: TKO 8.5.0, MLO 1.7.1, REO 1.6.2, FKO 1.2.2, aligned to UKO 15.6.0.

Each change is a checked replacement (exact match count) or an appended block. Run from 01-ontologies/.
"""
import re
import rdflib
from rdflib.namespace import RDF, RDFS, OWL

SET = "release set: UKO v15.6.0, TKO v8.5.0, MLO v1.7.1, REO v1.6.2, FKO v1.2.2"


class Edit:
    def __init__(self, src):
        self.s = open(src, encoding="utf-8").read()

    def rep(self, old, new, count=1):
        n = self.s.count(old)
        if n != count:
            raise SystemExit(f"expected {count}, found {n}: {old[:90]!r}")
        self.s = self.s.replace(old, new)

    def sub_range(self, old, new, want):
        pat = re.compile(r"(rdfs:range )" + re.escape(old) + r"(?=\s*[;.])")
        self.s, k = pat.subn(r"\g<1>" + new, self.s)
        if k != want:
            raise SystemExit(f"{old}: expected {want} ranges, found {k}")

    def prop_range(self, prop, old, new):
        """Change the rdfs:range inside one property's declaration block."""
        pat = re.compile(r"(^" + re.escape(prop) + r" rdf:type owl:DatatypeProperty ;.*?rdfs:range )" + re.escape(old)
                         + r"(?=\s*[;.])", re.S | re.M)
        self.s, k = pat.subn(r"\g<1>" + new, self.s, count=1)
        if k != 1:
            raise SystemExit(f"range of {prop} not found")

    def append(self, marker, block):
        self.rep(marker, block + marker)

    def write(self, dst):
        open(dst, "w", encoding="utf-8").write(self.s)
        print("wrote", dst)


def undeclared(path, ns):
    """Own-namespace terms used in the file but never typed: classes (from subClassOf) and properties."""
    g = rdflib.Graph().parse(path)
    decl = {s for s in g.subjects(RDF.type, None)}
    used = {x for t in g for x in t if isinstance(x, rdflib.URIRef) and str(x).startswith(ns)}
    used.discard(rdflib.URIRef(ns))
    out = []
    for x in sorted(used - decl, key=str):
        if str(x)[len(ns):][:1].isdigit():
            continue  # version IRIs
        if (list(g.objects(x, RDFS.subClassOf)) or list(g.subjects(RDFS.subClassOf, x))
                or list(g.subjects(RDFS.range, x)) or list(g.subjects(RDFS.domain, x))):
            out.append((x, "owl:Class"))
        elif list(g.objects(x, RDFS.subPropertyOf)):
            parent = next(g.objects(x, RDFS.subPropertyOf))
            t = next((t for t in (OWL.ObjectProperty, OWL.DatatypeProperty) if (parent, RDF.type, t) in g), None)
            if t is None:
                raise SystemExit(f"cannot type {x}: parent {parent} untyped")
            out.append((x, "owl:ObjectProperty" if t == OWL.ObjectProperty else "owl:DatatypeProperty"))
        else:
            out.append((x, None))
    return out


# ---------------- TKO 8.4.0 -> 8.5.0
e = Edit("tko_ontology_v8_4.ttl")
e.rep("#    Version 8.3.0 - Neurosymbolic Urban Mobility System", "#    Version 8.5.0 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v8.5.0: Coordinated release 2026-11-20 ({SET}).
#             (1) Imports UKO v15.6.0; uko:TimePeriod and uko:FunctionalClassification, used here
#                 as ranges, are now declared in UKO.
#             (2) OWL 2 datatypes: xsd:duration (7 ranges) becomes uko:ISODuration and xsd:date
#                 (3 ranges) becomes uko:CalendarDate; both are patterned xsd:string datatypes
#                 defined in UKO v15.6.0, because OWL 2 reasoners reject xsd:duration and xsd:date.
#             (3) Declares as owl:Class the 198 TKO classes that 8.4 used without a declaration
#                 (197 introduced only through rdfs:subClassOf, plus tko:EnhancementStage, used
#                 only as a range), and types the 5 sub-properties (originPOI, destinationPOI,
#                 stopPOI, originArea, destinationArea) that lacked a declaration.
#             (4) Declares tko:featureExtraction, tko:featureType and tko:featureGroup as
#                 annotation properties (used on datatype properties, never declared).
""")
e.rep("owl:versionIRI <urn:trip-kg:8.4.0> ;", "owl:versionIRI <urn:trip-kg:8.5.0> ;\n    owl:priorVersion <urn:trip-kg:8.4.0> ;")
e.rep("owl:imports <urn:urban-kg:15.5.0> ;", "owl:imports <urn:urban-kg:15.6.0> ;")
e.rep('dcterms:title "Trip Knowledge Ontology (TKO) v8.4.0', 'dcterms:title "Trip Knowledge Ontology (TKO) v8.5.0')
e.rep('rdfs:comment "Version 8.4.0 adds', 'rdfs:comment "Version 8.5.0 aligns TKO to UKO v15.6.0 (OWL 2 datatypes, '
      'declarations for every class and property TKO uses). Version 8.4.0 adds')
e.sub_range("xsd:duration", "uko:ISODuration", 7)
e.sub_range("xsd:date", "uko:CalendarDate", 3)
und = undeclared("tko_ontology_v8_4.ttl", "urn:trip-kg:")
blank = [str(x) for x, t in und if t is None]
feat = {"urn:trip-kg:featureExtraction", "urn:trip-kg:featureType", "urn:trip-kg:featureGroup"}
if set(blank) - feat:
    raise SystemExit(f"untyped TKO terms with no class or property evidence: {set(blank) - feat}")
classes = [x for x, t in und if t == "owl:Class"]
props = [(x, t) for x, t in und if t and t != "owl:Class"]
if (len(classes), len(props)) != (198, 5):
    raise SystemExit(f"expected 198 classes and 5 properties, found {len(classes)} and {len(props)}")
q = lambda x: "tko:" + str(x)[len("urn:trip-kg:"):]
block = ("\n###############################################################################\n"
         "#    v8.5.0 DECLARATIONS (2026-11-20)\n"
         "###############################################################################\n\n"
         + "".join(f"{q(x)} rdf:type owl:Class .\n" for x in classes) + "\n"
         + "".join(f"{q(x)} rdf:type {t} .\n" for x, t in props) + "\n"
         + "".join(f'tko:{n} rdf:type owl:AnnotationProperty ;\n    rdfs:label "{lbl}"@en .\n'
                   for n, lbl in (("featureExtraction", "feature extraction"), ("featureType", "feature type"),
                                  ("featureGroup", "feature group"))) + "\n")
e.rep("#    END OF TKO v8.4.0 ONTOLOGY", "#    END OF TKO v8.5.0 ONTOLOGY")
e.append("###############################################################################\n#    END OF TKO v8.5.0 ONTOLOGY", block)
e.write("tko_ontology_v8_5.ttl")

# ---------------- MLO 1.7.0 -> 1.7.1
e = Edit("mlo_ontology_v1_7.ttl")
e.rep("#    Version 1.6.0 - Neurosymbolic Urban Mobility System", "#    Version 1.7.1 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.7.1: Coordinated release 2026-11-20 ({SET}).
#              (1) Imports UKO v15.6.0, TKO v8.5.0 and FKO v1.2.2.
#              (2) Declares four datatype properties used on LabelDefinition individuals but never
#                  declared: labelDataType, pipelineStage, requiresGKGLookup, requiresTelematicsData.
#              (3) generationDescription, labelDescription, modelDescription and modelNotes
#                  change range from xsd:string to rdf:PlainLiteral. Their values carry language
#                  tags (@en), and OWL 2 treats tagged strings as outside xsd:string, which made
#                  the stack logically inconsistent under an OWL 2 reasoner.
#              (4) mlo:attachedTo states rdfs:range owl:Thing: its comment already calls the range
#                  polymorphic (trips, stop events, road segments, routes and other entities).
""")
e.rep("owl:versionIRI <urn:mobility-label-kg:1.7.0> ;", "owl:versionIRI <urn:mobility-label-kg:1.7.1> ;\n    owl:priorVersion <urn:mobility-label-kg:1.7.0> ;")
e.rep("owl:imports <urn:trip-kg:8.4.0> ;", "owl:imports <urn:trip-kg:8.5.0> ;")
e.rep("owl:imports <urn:urban-kg:15.5.0> ;", "owl:imports <urn:urban-kg:15.6.0> ;")
e.rep("owl:imports <urn:freight-kg:1.2.1> ;", "owl:imports <urn:freight-kg:1.2.2> ;")
e.rep('dcterms:title "Mobility Label Ontology (MLO) v1.7.0"@en ;', 'dcterms:title "Mobility Label Ontology (MLO) v1.7.1"@en ;')
e.rep('rdfs:comment "Version 1.7.0 adds Part 9', 'rdfs:comment "Version 1.7.1 aligns MLO to UKO v15.6.0 and TKO v8.5.0 and '
      'declares every property it uses. Version 1.7.0 adds Part 9')
e.rep('''mlo:attachedTo rdf:type owl:ObjectProperty ;
    rdfs:domain mlo:LabelAssignment ;''', '''mlo:attachedTo rdf:type owl:ObjectProperty ;
    rdfs:domain mlo:LabelAssignment ;
    rdfs:range owl:Thing ;''')
for prop in ("mlo:generationDescription", "mlo:labelDescription", "mlo:modelDescription", "mlo:modelNotes"):
    e.prop_range(prop, "xsd:string", "rdf:PlainLiteral")
und = undeclared("mlo_ontology_v1_7.ttl", "urn:mobility-label-kg:")
names = sorted(str(x)[len("urn:mobility-label-kg:"):] for x, _ in und)
if names != ["labelDataType", "pipelineStage", "requiresGKGLookup", "requiresTelematicsData"]:
    raise SystemExit(f"unexpected MLO undeclared terms: {names}")
block = '''
###############################################################################
#    v1.7.1 DECLARATIONS (2026-11-20)
###############################################################################

mlo:labelDataType rdf:type owl:DatatypeProperty ;
    rdfs:domain mlo:LabelDefinition ;
    rdfs:range xsd:string ;
    rdfs:label "label data type"@en ;
    rdfs:comment "XSD data type of the label's value, written as a CURIE string (for example 'xsd:boolean')."@en .

mlo:pipelineStage rdf:type owl:DatatypeProperty ;
    rdfs:domain mlo:LabelDefinition ;
    rdfs:range xsd:string ;
    rdfs:label "pipeline stage (code)"@en ;
    rdfs:comment "Code of the pipeline stage that computes the label (for example 'STAGE_5_OUTCOME'). mlo:hasPipelineStage gives the same information as a link to a mlo:PipelineStage individual."@en .

mlo:requiresGKGLookup rdf:type owl:DatatypeProperty ;
    rdfs:domain mlo:LabelDefinition ;
    rdfs:range xsd:boolean ;
    rdfs:label "requires GKG lookup"@en ;
    rdfs:comment "True when computing the label needs a lookup in the geospatial knowledge graph."@en .

mlo:requiresTelematicsData rdf:type owl:DatatypeProperty ;
    rdfs:domain mlo:LabelDefinition ;
    rdfs:range xsd:boolean ;
    rdfs:label "requires telematics data"@en ;
    rdfs:comment "True when computing the label needs vehicle telematics data."@en .

'''
e.rep("#    END OF MLO v1.7.0 ONTOLOGY", "#    END OF MLO v1.7.1 ONTOLOGY")
e.append("###############################################################################\n#    END OF MLO v1.7.1 ONTOLOGY", block)
e.write("mlo_ontology_v1_7_1.ttl")

# ---------------- REO 1.6.1 -> 1.6.2
e = Edit("reo_ontology_v1_6_1.ttl")
e.rep("#    Version 1.6.0 - Neurosymbolic Urban Mobility System", "#    Version 1.6.2 - Neurosymbolic Urban Mobility System")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.6.2: Coordinated release 2026-11-20 ({SET}).
#              (1) Imports UKO v15.6.0, TKO v8.5.0 and MLO v1.7.1.
#              (2) reo:sensitivityLabel and reo:sensitivityRationale change range from xsd:string
#                  to rdf:PlainLiteral: their values carry language tags, which OWL 2 places
#                  outside xsd:string, and the stack was inconsistent under an OWL 2 reasoner.
#              (3) Declares reo:PRIORITY_MODERATE, an AlertPriority individual that a
#                  FleetEventSensitivity record used but that was never declared.
""")
e.rep("owl:versionIRI <urn:route-event-kg:1.6.1> ;", "owl:versionIRI <urn:route-event-kg:1.6.2> ;\n    owl:priorVersion <urn:route-event-kg:1.6.1> ;")
e.rep("owl:imports <urn:urban-kg:15.5.0> ;", "owl:imports <urn:urban-kg:15.6.0> ;")
e.rep("owl:imports <urn:trip-kg:8.4.0> ;", "owl:imports <urn:trip-kg:8.5.0> ;")
e.rep("owl:imports <urn:mobility-label-kg:1.7.0> ;", "owl:imports <urn:mobility-label-kg:1.7.1> ;")
e.rep('dcterms:title "Route Event Ontology (REO) v1.6.1"@en ;', 'dcterms:title "Route Event Ontology (REO) v1.6.2"@en ;')
e.rep('rdfs:comment "v1.6.1 is a coordinated-release', 'rdfs:comment "v1.6.2 is a coordinated-release alignment to UKO '
      'v15.6.0, TKO v8.5.0 and MLO v1.7.1, and declares reo:PRIORITY_MODERATE. v1.6.1 is a coordinated-release')
e.rep('''reo:PRIORITY_INFORMATIONAL rdf:type owl:NamedIndividual, reo:AlertPriority ;''',
      '''reo:PRIORITY_MODERATE rdf:type owl:NamedIndividual, reo:AlertPriority ;
    rdfs:label "Moderate"@en ;
    rdfs:comment "Between High and Informational. Declared in v1.6.2; used earlier without a declaration."@en .

reo:PRIORITY_INFORMATIONAL rdf:type owl:NamedIndividual, reo:AlertPriority ;''')
for prop in ("reo:sensitivityLabel", "reo:sensitivityRationale"):
    e.prop_range(prop, "xsd:string", "rdf:PlainLiteral")
e.rep("#    END OF REO v1.6.0 ONTOLOGY", "#    END OF REO v1.6.2 ONTOLOGY")
e.write("reo_ontology_v1_6_2.ttl")

# ---------------- FKO 1.2.1 -> 1.2.2
e = Edit("fko_ontology_v1_2_1.ttl")
e.rep("#    Version 1.2.0 - GeoMetis Over-the-Horizon Risk Model", "#    Version 1.2.2 - GeoMetis Over-the-Horizon Risk Model")
e.rep("#    Change Log:\n", f"""#    Change Log:
#    - v1.2.2: Coordinated release 2026-11-20 ({SET}).
#              (1) Imports TKO v8.5.0.
#              (2) OWL 2 datatypes: fko:weightsCalibrationDate's range changes from xsd:date to
#                  uko:CalendarDate (defined in UKO v15.6.0), and its six values are written as
#                  xsd:string literals in YYYY-MM-DD form, as OWL 2 requires for such datatypes.
""")
e.rep("owl:versionIRI <urn:freight-kg:1.2.1> ;", "owl:versionIRI <urn:freight-kg:1.2.2> ;\n    owl:priorVersion <urn:freight-kg:1.2.1> ;")
e.rep("owl:imports <urn:trip-kg:8.4.0> ;", "owl:imports <urn:trip-kg:8.5.0> ;")
e.rep('dcterms:title "Freight Knowledge Ontology (FKO) v1.2.1"@en ;', 'dcterms:title "Freight Knowledge Ontology (FKO) v1.2.2"@en ;')
e.rep("FKO imports TKO v8.4.0 because", "FKO imports TKO v8.5.0 because", 2)
e.rep('rdfs:comment "Version 1.2.1', 'rdfs:comment "Version 1.2.2 — coordinated-release alignment (TKO v8.5.0, '
      'release set 2026-11-20); OWL 2 date datatype. Version 1.2.1')
e.sub_range("xsd:date", "uko:CalendarDate", 1)
e.rep('"2026-04-01"^^xsd:date', '"2026-04-01"^^xsd:string', 6)
e.rep("#    END OF FKO v1.2.0 ONTOLOGY", "#    END OF FKO v1.2.2 ONTOLOGY")
e.write("fko_ontology_v1_2_2.ttl")
