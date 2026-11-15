"""Choose the 30 questions that arm A0 (language model only) answers in the full Test 1 run. No model calls.

python full_select.py POOLDIR SEED
Reads POOLDIR/pool.jsonl (written by gen.py) and writes POOLDIR/full_a0.jsonl (qid and question only).
Rule (docs/test-plan-2026-11.md: A0 answers 30 questions, reported descriptively): 8 network, 8 what-if,
8 constrained and 6 lookup questions, drawn with the seed; within each non-lookup category half come from each
author group when enough questions exist.
"""
import json, os, sys
import numpy as np

QUOTA = {"network": 8, "what-if": 8, "constrained": 8, "lookup": 6}

def main():
    pooldir, seed = sys.argv[1], int(sys.argv[2])
    pool = sorted((json.loads(l) for l in open(os.path.join(pooldir, "pool.jsonl"))), key=lambda p: p["qid"])
    rng = np.random.default_rng([seed, 30])
    out = []
    for cat, k in QUOTA.items():
        rows = [p for p in pool if p["category"] == cat]
        if cat == "lookup":
            out += [rows[i] for i in rng.permutation(len(rows))[:k]]; continue
        picked = []
        for author in ("claude", "evangelos"):
            ra = [p for p in rows if p["author"] == author]
            picked += [ra[i] for i in rng.permutation(len(ra))[:k // 2]]
        rest = [p for p in rows if p not in picked]
        picked += [rest[i] for i in rng.permutation(len(rest))[:k - len(picked)]]
        out += picked
    with open(os.path.join(pooldir, "full_a0.jsonl"), "w") as f:
        for p in out: f.write(json.dumps({"qid": p["qid"], "question": p["question"]}) + "\n")
    print("A0 questions", len(out), {c: sum(1 for p in out if p["category"] == c) for c in QUOTA})

if __name__ == "__main__":
    main()
