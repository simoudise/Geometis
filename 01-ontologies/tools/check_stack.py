"""Consistency checks across the ontology stack (no reasoner).

Usage: python tools/check_stack.py uko.ttl tko.ttl mlo.ttl reo.ttl fko.ttl
Reports, per namespace: terms used but never declared, object/datatype properties without domain or range,
terms with more than one label, datatypes outside the OWL 2 datatype map, and imports that point at versions not
in the file set.
"""
import sys, collections, rdflib
from rdflib.namespace import RDF, RDFS, OWL, XSD

OWL2 = {XSD[x] for x in ("decimal integer nonNegativeInteger nonPositiveInteger positiveInteger negativeInteger long int "
        "short byte unsignedLong unsignedInt unsignedShort unsignedByte double float string normalizedString token "
        "language Name NCName NMTOKEN boolean hexBinary base64Binary anyURI dateTime dateTimeStamp").split()}
OWL2 |= {RDF.PlainLiteral, RDF.XMLLiteral, RDFS.Literal, RDF.langString}
NS = {"uko": "urn:urban-kg:", "tko": "urn:trip-kg:", "mlo": "urn:mobility-label-kg:", "reo": "urn:route-event-kg:",
      "fko": "urn:freight-kg:"}

files = sys.argv[1:]
G = rdflib.Graph()
per = {}
for f in files:
    g = rdflib.Graph().parse(f)
    per[f] = g
    G += g
nm = lambda x: x.n3(G.namespace_manager) if not isinstance(x, rdflib.Literal) else repr(str(x)[:60])
versions = {str(o) for g in per.values() for o in g.objects(None, OWL.versionIRI)}
datatypes = set(G.subjects(RDF.type, RDFS.Datatype))
problems = 0
for pfx, ns in NS.items():
    decl = {s for s in G.subjects(RDF.type, None) if isinstance(s, rdflib.URIRef) and str(s).startswith(ns)}
    used = {x for t in G for x in t if isinstance(x, rdflib.URIRef) and str(x).startswith(ns)}
    ont = {rdflib.URIRef(ns)} | {rdflib.URIRef(v) for v in versions if v.startswith(ns)}
    und = sorted(nm(x) for x in used - decl - ont if not str(x)[len(ns):][:1].isdigit())
    props = {s for t in (OWL.ObjectProperty, OWL.DatatypeProperty) for s in G.subjects(RDF.type, t) if str(s).startswith(ns)}
    nodom = sorted(nm(p) for p in props if not list(G.objects(p, RDFS.domain)))
    norng = sorted(nm(p) for p in props if not list(G.objects(p, RDFS.range)))
    multi = sorted(nm(s) for s in decl if len(set(G.objects(s, RDFS.label))) > 1)
    print(f"== {pfx}: {len(decl)} declared; undeclared used {len(und)}; no domain {len(nodom)}; no range {len(norng)}; "
          f"multi-label {len(multi)}")
    for name, lst in (("undeclared", und), ("no domain", nodom), ("no range", norng), ("multi-label", multi)):
        if lst:
            print(f"   {name}: {lst}")
            problems += len(lst)
bad = collections.Counter()
for s, p, o in G:
    if isinstance(o, rdflib.URIRef) and str(o).startswith(str(XSD)) and o not in OWL2:
        bad[nm(o)] += 1
    if isinstance(o, rdflib.Literal) and o.datatype and o.datatype not in OWL2 and o.datatype not in datatypes:
        bad["literal " + nm(o.datatype)] += 1
print("non-OWL-2 datatypes:", dict(bad))
problems += sum(bad.values())
for f, g in per.items():
    imp = [str(o) for o in g.objects(None, OWL.imports)]
    missing = [i for i in imp if i not in versions]
    print(f"imports {f}: {imp}" + (f"  NOT IN SET: {missing}" if missing else ""))
    problems += len(missing)
print("TOTAL PROBLEMS:", problems)
