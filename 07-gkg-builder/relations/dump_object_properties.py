import rdflib, csv, sys
import os
ONTO_DIR = os.environ.get("ONTO_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "01-ontologies"))
from rdflib.namespace import RDF, RDFS, OWL
# Release set: the Step 1 inventory of 20 November 2026 used the 2026-09-19 set (UKO 15.5); RELEASE=2026-11-20 uses
# the coordinated release of that date (UKO 15.6, TKO 8.5, MLO 1.7.1, REO 1.6.2, FKO 1.2.2), which is the default.
SETS={'2026-09-19':{'UKO':'uko_ontology_v15_5.ttl','TKO':'tko_ontology_v8_4.ttl','MLO':'mlo_ontology_v1_7.ttl','REO':'reo_ontology_v1_6_1.ttl','FKO':'fko_ontology_v1_2_1.ttl'},
      '2026-11-20':{'UKO':'uko_ontology_v15_6.ttl','TKO':'tko_ontology_v8_5.ttl','MLO':'mlo_ontology_v1_7_1.ttl','REO':'reo_ontology_v1_6_2.ttl','FKO':'fko_ontology_v1_2_2.ttl'}}
files=SETS[os.environ.get('RELEASE','2026-11-20')]
out=csv.writer(open('props.csv','w'))
out.writerow(['onto','prop','domain','range','inverse','subprop','deprecated','functional','comment'])
def q(g,n):
    try: return g.namespace_manager.normalizeUri(n) if isinstance(n,rdflib.URIRef) else ('union('+ ' '.join(q(g,x) for x in rdflib.collection.Collection(g, g.value(n,OWL.unionOf)))+')' if g.value(n,OWL.unionOf) else '_bnode')
    except Exception as e: return str(n)
for k,f in files.items():
    g=rdflib.Graph().parse(os.path.join(ONTO_DIR, f))
    ps=sorted(set(g.subjects(RDF.type,OWL.ObjectProperty)))
    print(k,len(ps))
    for p in ps:
        dom='|'.join(q(g,d) for d in g.objects(p,RDFS.domain))
        rng='|'.join(q(g,d) for d in g.objects(p,RDFS.range))
        inv='|'.join(q(g,d) for d in g.objects(p,OWL.inverseOf))+'|'.join('~'+q(g,d) for d in g.subjects(OWL.inverseOf,p))
        sp='|'.join(q(g,d) for d in g.objects(p,RDFS.subPropertyOf))
        dep=str(g.value(p,OWL.deprecated) or '')
        fun='F' if (p,RDF.type,OWL.FunctionalProperty) in g else ''
        c=' '.join(str(x) for x in g.objects(p,RDFS.comment)).replace('\n',' ')[:300]
        out.writerow([k,q(g,p),dom,rng,inv,sp,dep,fun,c])
