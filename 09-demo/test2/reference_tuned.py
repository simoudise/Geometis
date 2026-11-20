"""Test 2 diagnostic (not part of the Bet B verdict): the in-geofence reference with the same tuning budget as B2.

python reference_tuned.py FEATURESDIR EVALDIR --fold F [--seed 0] [--trials 8]
Requested by Evangelos on Nov 19 after the reference scored worse than B2 on the two Contra Costa folds.
reference.py fitted one fixed head configuration. This script gives the reference the same budget evaluate.py gave
B2: 8 configurations drawn with seed 0 from evaluate.py's SPACE. The held-out area's own 1 km blocks are split into 5
outer groups (same assignment as reference.py). For each outer group, every configuration is scored by 4-fold
cross-validation on the other four groups; the best configuration is refitted on those four groups and predicts the
outer group. Selection therefore never sees the labels it is scored on (nested cross-validation). Features, head
class, intercept refit and output fields match reference.py. Writes EVALDIR/reference_tuned.jsonl.
"""
import argparse, datetime, json, os
import numpy as np
import pandas as pd
from evaluate import deviance, fit_predict, configs

def run_head(df, head, cols, seed, trials):
    tgt = df[df.role == "target"].reset_index(drop=True)
    blocks = np.array(sorted(tgt.block.unique()))
    rng = np.random.default_rng(seed)
    grp = dict(zip(blocks[rng.permutation(len(blocks))], np.arange(len(blocks)) % 5))
    g = tgt.block.map(grp).values
    e = (tgt.exposure_m.values / 1000.0) if head == "segment" else np.ones(len(tgt))
    X = tgt[cols].to_numpy(np.float64); y = tgt.y.values.astype(float)
    cfgs = configs(trials, seed)
    mu = np.zeros(len(tgt)); chosen = []
    for k in range(5):
        tr = g != k
        inner = [j for j in range(5) if j != k]
        best, best_dev = None, np.inf
        for cfg in cfgs:
            dev = 0.0
            for j in inner:
                a, b = tr & (g != j), g == j
                p = fit_predict(cfg, X[a], y[a] / e[a], e[a], X[b], seed) * e[b]
                dev += deviance(y[b], p).sum()
            if dev < best_dev:
                best, best_dev = cfg, dev
        chosen.append(best)
        te = g == k
        mu[te] = fit_predict(best, X[tr], y[tr] / e[tr], e[tr], X[te], seed) * e[te]
    mu_adj = mu.copy()
    for gf in tgt.geofence_id.unique():
        m = tgt.geofence_id.values == gf
        mu_adj[m] = mu[m] * (y[m].sum() / max(mu[m].sum(), 1e-9))
    d_adj, d_raw = deviance(y, mu_adj), deviance(y, mu)
    res = {"n": int(len(tgt)), "crashes": int(y.sum()), "primary_mean_deviance": float(d_adj.mean()),
           "raw_mean_deviance": float(d_raw.mean()), "chosen_configs": chosen}
    res["by_stratum"] = {s: {"n": int(m.sum()), "crashes": int(y[m].sum()), "sum_deviance": float(d_adj[m].sum())}
                         for s in tgt.stratum.unique() for m in [tgt.stratum.values == s]}
    blk = pd.DataFrame({"b": tgt.geofence_id + "|" + tgt.block.astype(str), "s": tgt.stratum, "d": d_adj, "n": 1})
    res["by_block"] = blk.groupby(["b", "s"])[["d", "n"]].sum().reset_index().values.tolist()
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("featdir"); ap.add_argument("outdir"); ap.add_argument("--fold", required=True)
    ap.add_argument("--seed", type=int, default=0); ap.add_argument("--trials", type=int, default=8)
    a = ap.parse_args()
    logp = os.path.join(a.outdir, "reference_tuned.jsonl")
    if os.path.exists(logp) and any(json.loads(l)["fold"] == a.fold for l in open(logp)):
        raise SystemExit(f"already evaluated: {a.fold}")
    flist = json.load(open(os.path.join(a.featdir, "feature_list.json")))
    out = {"fold": a.fold, "method": "REF-tuned", "seed": a.seed, "trials": a.trials, "diagnostic": True,
           "time": datetime.datetime.now(datetime.timezone.utc).isoformat(), "heads": {}}
    for head in ("segment", "intersection"):
        df = pd.read_parquet(os.path.join(a.featdir, a.fold, f"{head}.parquet"))
        out["heads"][head] = run_head(df, head, list(flist[head]["B2"]), a.seed, a.trials)
        print(a.fold, head, "done", flush=True)
    with open(logp, "a") as f:
        f.write(json.dumps(out, default=str) + "\n")

if __name__ == "__main__":
    main()
