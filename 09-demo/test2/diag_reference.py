"""Test 2 diagnostic (not part of the Bet B verdict): B2 against the fixed and the tuned in-geofence reference, per fold.

python diag_reference.py EVALDIR [B] [SEED]
Reads EVALDIR/evaluations.jsonl (B2), reference.jsonl (fixed configuration) and reference_tuned.jsonl (8 trials,
nested cross-validation). For each fold it prints the primary deviance pooled over both heads, and the gain of B2
over each reference with a 95 percent interval from resampling 1 km blocks within the fold.
"""
import json, os, sys
import numpy as np

def blocks(run):
    bd = {}
    for head, h in run["heads"].items():
        for b, s, d, n in h["by_block"]:
            v = bd.setdefault(b, np.zeros(2)); v += [float(d), float(n)]
    return bd

def main():
    ev = sys.argv[1]; B = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    rng = np.random.default_rng(int(sys.argv[3]) if len(sys.argv) > 3 else 20261120)
    b2 = {r["fold"]: r for r in map(json.loads, open(os.path.join(ev, "evaluations.jsonl"))) if r["method"] == "B2"}
    refs = {name: {r["fold"]: r for r in map(json.loads, open(os.path.join(ev, f)))}
            for name, f in (("REF fixed", "reference.jsonl"), ("REF tuned", "reference_tuned.jsonl"))
            if os.path.exists(os.path.join(ev, f))}
    for fold in sorted(b2):
        a = blocks(b2[fold]); pa = sum(v[0] for v in a.values()) / sum(v[1] for v in a.values())
        print(f"{fold}: B2 {pa:.4f}")
        for name, rr in refs.items():
            if fold not in rr: continue
            r = blocks(rr[fold]); pr = sum(v[0] for v in r.values()) / sum(v[1] for v in r.values())
            keys = sorted(set(a) & set(r)); A = np.array([a[k] for k in keys]); R = np.array([r[k] for k in keys])
            draws = []
            for _ in range(B):
                i = rng.integers(0, len(keys), len(keys))
                draws.append(R[i, 0].sum() / R[i, 1].sum() - A[i, 0].sum() / A[i, 1].sum())
            lo, hi = np.percentile(draws, [2.5, 97.5])
            print(f"   {name}: {pr:.4f}; gain of B2 over it {pr - pa:+.4f} [{lo:+.4f}, {hi:+.4f}]"
                  + ("" if name == "REF fixed" else f"; configurations chosen: {[c['learning_rate'] for c in rr[fold]['heads']['segment']['chosen_configs']]} (segment learning rates)"))

if __name__ == "__main__":
    main()
