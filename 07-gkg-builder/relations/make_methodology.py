"""Write docs/gkg-full-methodology.md: the hand-written method (methodology_head.md) plus a table of every
relation built from the catalogue (domain and range from the ontology, rule from RELATIONS).

python3 -m relations.make_methodology OUT.md
"""
import sys
from pathlib import Path

from relations.build import CATALOGUE
from relations.make_dictionary import FAMILY

head = (Path(__file__).parent / "methodology_head.md").read_text()
rel = {l.split("\t")[1]: l.rstrip("\n").split("\t") for l in open(CATALOGUE / "relation_type.tsv")}
L = [head.rstrip("\n"), ""]
for fam, cs in FAMILY:
    L += [f"### {fam}", "", "| Relation | Domain -> range | Rule |", "|---|---|---|"]
    for c in cs:
        _, _, dom, rng, cd, sym, inv, note = rel[c]
        flags = (" (symmetric)" if sym == "True" else "") + (" (crash-derived)" if cd == "True" else "")
        L.append(f"| {c}{flags} | {dom.replace(',', ' or ')} -> {rng.replace(',', ' or ')} | {note} |")
    L.append("")
Path(sys.argv[1]).write_text("\n".join(L))
print(sys.argv[1], len(L), "lines")
