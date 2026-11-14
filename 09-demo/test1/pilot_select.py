"""Choose the Test 1 pilot questions from a generated pool. No model calls.

python pilot_select.py POOLDIR SEED
Reads POOLDIR/pool.jsonl (written by gen.py) and writes, in POOLDIR:
  pilot_pool.jsonl  the chosen questions with their reference answers (for score.py)
  pilot.jsonl       qid and question only, for arms A1 to A4
  pilot_a0.jsonl    10 of the chosen questions, for arm A0

Rule (docs/test-plan-2026-11.md, "Cost and order"): one question per template and geofence, drawn with the
seed, which gives 50 questions from 25 templates. When a template has no question in one geofence, a second
question comes from its other geofence. The A0 subset takes 2 network, 2 what-if, 2 constrained and 4 lookup
questions, drawn with the same seed.
"""
import json, os, sys, zlib
import numpy as np

A0_QUOTA = {"network": 2, "what-if": 2, "constrained": 2, "lookup": 4}

def main():
    pooldir, seed = sys.argv[1], int(sys.argv[2])
    pool = [json.loads(l) for l in open(os.path.join(pooldir, "pool.jsonl"))]
    by = {}
    for p in pool:
        by.setdefault(p["template"], {}).setdefault(p["geofence"], []).append(p)
    chosen = []
    for tid in sorted(by):
        rng = np.random.default_rng([seed, zlib.crc32(tid.encode())])
        picks, spare = [], []
        for gf in sorted(by[tid]):
            rows = sorted(by[tid][gf], key=lambda p: p["qid"])
            order = rng.permutation(len(rows))
            picks.append(rows[order[0]]); spare += [rows[i] for i in order[1:]]
        while len(picks) < 2 and spare:
            picks.append(spare.pop(0))
        chosen += picks
    rng = np.random.default_rng([seed, 0])
    a0 = []
    for cat, k in A0_QUOTA.items():
        rows = sorted((p for p in chosen if p["category"] == cat), key=lambda p: p["qid"])
        a0 += [rows[i] for i in rng.permutation(len(rows))[:k]]
    def dump(name, rows, full):
        with open(os.path.join(pooldir, name), "w") as f:
            for p in rows:
                f.write(json.dumps(p if full else {"qid": p["qid"], "question": p["question"]}, default=str) + "\n")
    dump("pilot_pool.jsonl", chosen, True); dump("pilot.jsonl", chosen, False); dump("pilot_a0.jsonl", a0, False)
    cats = {}
    for p in chosen: cats[(p["category"], p["geofence"])] = cats.get((p["category"], p["geofence"]), 0) + 1
    print("pilot questions", len(chosen), "templates", len(by), "A0 subset", len(a0))
    for k in sorted(cats): print("  ", k[0], k[1], cats[k])

if __name__ == "__main__":
    main()
