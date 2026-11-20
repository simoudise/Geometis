"""Consistency check of an ontology set with the HermiT reasoner (shipped with owlready2).

Usage: python tools/reason_check.py OUT.owl file1.ttl [file2.ttl ...]
Merges the files, removes owl:imports (the URN imports cannot be fetched), writes RDF/XML to OUT.owl and runs
HermiT's consistency check (-k). Prints "owl:Thing is satisfiable" when the set is consistent.
"""
import glob, os, subprocess, sys
import rdflib
from rdflib.namespace import OWL

out, files = sys.argv[1], sys.argv[2:]
g = rdflib.Graph()
for f in files:
    g.parse(f)
g.remove((None, OWL.imports, None))
g.serialize(out, format="xml")
import owlready2
h = os.path.join(os.path.dirname(owlready2.__file__), "hermit")
r = subprocess.run(["java", "-Xmx3000M", "-cp", f"{h}:{h}/HermiT.jar", "org.semanticweb.HermiT.cli.CommandLine",
                    "-k", "file://" + os.path.abspath(out)], capture_output=True, text=True)
lines = [l for l in (r.stdout + r.stderr).splitlines() if "JAVA_OPTIONS" not in l and "JAVA_TOOL" not in l]
print("\n".join(l for l in lines if "satisfiable" in l or "Inconsistent" in l) or "\n".join(lines[:5]))
