"""Test 2 analysis: pooled measures, block bootstrap and the pass, fail and inconclusive rules for Bet B.

python analyze_test2.py EVALDIR [B] [SEED]
Reads EVALDIR/evaluations.jsonl (evaluate.py) and EVALDIR/reference.jsonl (reference.py). Written and frozen by hash
before any result in those files was read (docs/test-plan-2026-11.md, change log).

Definitions (fixed here, before results):
- Measure: primary Poisson deviance after the per-geofence intercept refit. Lower is better. A method's pooled value
  is the sum of entity deviances over both heads (segments and intersections) and all three folds, divided by the
  number of entities.
- Networks are evaluated with 5 encoder seeds. A network's value in a block is the mean of its 5 seeds.
- S-pub means the S-pub embeddings alone (method EMB). B4 means the R-GCN embeddings alone (EMB with rgcn).
  Combined sets (EMB+B2) are reported beside them and do not enter the rules.
- Gain of X over Y = deviance(Y) - deviance(X); positive means X is better.
- Minimum effect: the gain must be at least 10 percent of the gap between B2 and the in-geofence reference
  (pooled) and larger than two standard deviations of the pooled gain across the 5 encoder seeds.
- Block bootstrap: 1 km blocks are resampled with replacement within each fold (B = 9,999 by default) and the pooled
  gain is recomputed; the 95 percent interval is the 2.5th and 97.5th percentiles. Seed noise is not resampled.
S-pub passes when all six plan conditions hold:
  1. its pooled gain over B2 and over B4 each reaches the minimum effect;
  2. its gain over B2 is positive in every fold;
  3. the bootstrap interval of its pooled gain over B2 excludes zero;
  4. its pooled gain over B2 is positive in the arterial, collector and intersection strata;
  5. it closes at least half of the gap between B1 and the reference: (B1 - S) / (B1 - REF) >= 0.5;
  6. its gain over B2 in the San Francisco fold is not negative.
Fail: the gain over B2 is below the minimum effect and the upper bound of its interval is below the minimum effect.
Inconclusive: every other outcome.
S-full matches S-pub when the interval of their difference lies inside plus or minus the minimum effect.
S-full against the equal-supervision baselines (B2-eq and rgcn-eq) is reported with the same interval.
"""
import json, os, sys
from collections import defaultdict
import numpy as np

FOLDS = ["f1-wc-ph-concord", "f2-antioch-pittsburg", "f3-san-francisco"]
NETS = ["S-pub", "S-full", "rgcn", "rgcn-eq", "sage"]
STRATA = ["arterial", "collector", "intersection"]

def net_of(emb):
    for n in NETS:
        if f"/{n}/seed" in emb:
            return n
    return None

def load(evaldir):
    """Return blocks[(name, fold)][(head, block, stratum)] = [sum_d, n] and per-seed copies for networks."""
    runs = [json.loads(l) for l in open(os.path.join(evaldir, "evaluations.jsonl"))]
    refp = os.path.join(evaldir, "reference.jsonl")
    runs += [dict(r, emb="") for r in (json.loads(l) for l in open(refp))] if os.path.exists(refp) else []
    per_seed = defaultdict(lambda: defaultdict(dict))   # name -> fold -> seed -> blockdict
    for r in runs:
        net = net_of(r.get("emb", ""))
        name = r["method"] if net is None else f"{net} {r['method']}"
        seed = r["emb"].rstrip("/").split("seed")[-1] if net else "0"
        bd = {}
        for head, h in r["heads"].items():
            for b, s, d, n in h["by_block"]:
                bd[(head, b, s)] = np.array([float(d), float(n)])
        if seed in per_seed[name][r["fold"]]:
            raise SystemExit(f"duplicate evaluation for {name} {r['fold']} seed {seed}")
        per_seed[name][r["fold"]][seed] = bd
    mean = {}
    for name, folds in per_seed.items():
        for fold, seeds in folds.items():
            keys = set().union(*[set(v) for v in seeds.values()])
            mean[(name, fold)] = {k: np.mean([seeds[s][k] for s in seeds], axis=0) for k in keys}
    return mean, per_seed

def pooled(bd_by_fold, folds=FOLDS, strata=None):
    d = n = 0.0
    for f in folds:
        for (head, b, s), v in bd_by_fold[f].items():
            if strata is None or s in strata:
                d += v[0]; n += v[1]
    return d / n

def method(mean, name):
    return {f: mean[(name, f)] for f in FOLDS if (name, f) in mean}

def gain(mean, x, y, folds=FOLDS, strata=None):
    return pooled(method(mean, y), folds, strata) - pooled(method(mean, x), folds, strata)

def bootstrap(mean, x, y, B, rng):
    """Pooled gain of x over y with blocks resampled within each fold. Entities in a block keep both heads."""
    X, Y = method(mean, x), method(mean, y)
    per_fold = []
    for f in FOLDS:
        blocks = sorted({b for (_, b, _) in Y[f]})
        idx = {b: i for i, b in enumerate(blocks)}
        a = np.zeros((len(blocks), 4))   # sum_d of y, n of y, sum_d of x, n of x
        for k, v in Y[f].items():
            a[idx[k[1]], 0] += v[0]; a[idx[k[1]], 1] += v[1]
        for k, v in X[f].items():
            a[idx[k[1]], 2] += v[0]; a[idx[k[1]], 3] += v[1]
        per_fold.append(a)
    out = np.empty(B)
    for i in range(B):
        t = np.zeros(4)
        for a in per_fold:
            t += a[rng.integers(0, len(a), len(a))].sum(axis=0)
        out[i] = t[0] / t[1] - t[2] / t[3]
    return np.percentile(out, [2.5, 97.5])

def seed_sd(per_seed, mean, x, y):
    """Standard deviation across encoder seeds of the pooled gain of network x over method y (seed i of x)."""
    seeds = sorted(per_seed[x][FOLDS[0]])
    g = []
    for s in seeds:
        bx = {f: per_seed[x][f][s] for f in FOLDS}
        g.append(pooled(method(mean, y)) - pooled(bx))
    return float(np.std(g, ddof=1)), g

def main():
    evaldir = sys.argv[1]
    B = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    rng = np.random.default_rng(int(sys.argv[3]) if len(sys.argv) > 3 else 20261117)
    mean, per_seed = load(evaldir)
    names = sorted({n for n, _ in mean})
    missing = [(n, f) for n in names for f in FOLDS if (n, f) not in mean]
    if missing:
        print("MISSING evaluations:", missing)
    print("Pooled primary deviance (lower is better), by fold and pooled")
    print(f"{'method':22s}" + "".join(f"{f[:12]:>14s}" for f in FOLDS) + f"{'pooled':>10s}")
    for n in names:
        m = method(mean, n)
        print(f"{n:22s}" + "".join(f"{pooled(m, [f]):14.4f}" if f in m else f"{'-':>14s}" for f in FOLDS)
              + (f"{pooled(m):10.4f}" if len(m) == 3 else ""))
    S, B2, B1, B4, REF = "S-pub EMB", "B2", "B1", "rgcn EMB", "REF"
    if any((x, f) not in mean for x in (S, B2, B1, B4, REF) for f in FOLDS):
        raise SystemExit("cannot apply the rules: S-pub, B1, B2, B4 or the reference is missing on some fold")
    gap = gain(mean, REF, B2)
    sd_b2, seeds_b2 = seed_sd(per_seed, mean, "S-pub EMB", B2)
    sd_b4, _ = seed_sd(per_seed, mean, "S-pub EMB", B4)
    min_eff = max(0.10 * gap, 0.0)
    g_b2, g_b4 = gain(mean, S, B2), gain(mean, S, B4)
    ci = bootstrap(mean, S, B2, B, rng)
    print(f"\nGap B2 - reference: {gap:.4f}; 10 percent of it: {0.1 * gap:.4f}")
    print(f"S-pub gain over B2: {g_b2:+.4f}, 95% block interval [{ci[0]:+.4f}, {ci[1]:+.4f}], seed SD {sd_b2:.4f}, "
          f"per-seed gains {[round(float(x), 4) for x in seeds_b2]}")
    print(f"S-pub gain over B4 (R-GCN): {g_b4:+.4f}, seed SD {sd_b4:.4f}")
    c1 = g_b2 >= min_eff and g_b2 > 2 * sd_b2 and g_b4 >= min_eff and g_b4 > 2 * sd_b4
    per_fold = {f: gain(mean, S, B2, [f]) for f in FOLDS}
    c2 = all(v > 0 for v in per_fold.values())
    c3 = ci[0] > 0
    per_stratum = {s: gain(mean, S, B2, FOLDS, {s}) for s in STRATA + ["local"]}
    c4 = all(per_stratum[s] > 0 for s in STRATA)
    p1, ps, pr = pooled(method(mean, B1)), pooled(method(mean, S)), pooled(method(mean, REF))
    closed = (p1 - ps) / (p1 - pr) if p1 != pr else float("nan")
    c5 = closed >= 0.5
    c6 = per_fold["f3-san-francisco"] >= 0
    print("Per-fold gain over B2:", {f: round(float(v), 4) for f, v in per_fold.items()})
    print("Per-stratum gain over B2 (local is reported, not required):", {s: round(float(v), 4) for s, v in per_stratum.items()})
    print(f"Share of the B1-to-reference gap closed: {closed:.2f}")
    conds = [c1, c2, c3, c4, c5, c6]
    print("Conditions 1 to 6:", ["holds" if c else "fails" for c in conds])
    thresh = max(min_eff, 2 * sd_b2)
    if all(conds):
        verdict = "PASS"
    elif g_b2 < thresh and ci[1] < thresh:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"
    print(f"Bet B verdict for S-pub: {verdict}")
    print("\nS-full against S-pub and the equal-supervision baselines")
    for y in ("S-pub EMB", "B2-eq", "rgcn-eq EMB"):
        if all(("S-full EMB", f) in mean and (y, f) in mean for f in FOLDS):
            g = gain(mean, "S-full EMB", y); c = bootstrap(mean, "S-full EMB", y, B, rng)
            extra = ""
            if y == "S-pub EMB":
                extra = "; matches S-pub" if (c[0] > -min_eff and c[1] < min_eff) else "; does not match S-pub"
            print(f"  S-full gain over {y}: {g:+.4f} [{c[0]:+.4f}, {c[1]:+.4f}]{extra}")
    print("\nCombined sets (descriptive): gain over B2")
    for n in NETS:
        if all((f"{n} EMB+B2", f) in mean for f in FOLDS):
            print(f"  {n} EMB+B2: {gain(mean, f'{n} EMB+B2', B2):+.4f}")

if __name__ == "__main__":
    main()
