"""Test 2 in-geofence reference: a model trained on the held-out area's own labels (docs/test-plan-2026-11.md).

python reference.py FEATURESDIR OUTDIR --fold F [--seed 0]
Runs on the Mac mini. The reference shows how well a head can do when it sees labels from the place it predicts.
It uses the B2 feature set and the same head class as evaluate.py. The held-out entities' 1 km blocks are assigned
at random (fixed seed) to 5 groups; for each group a head is fitted on the other four groups and predicts this one,
so every prediction is out of fold. The head uses one fixed configuration (the configuration tune.py uses for its
validation head), so no tuning choice is made on held-out labels. The same per-geofence intercept refit and the same
per-stratum and per-block sums as evaluate.py are written to OUTDIR/reference.jsonl. The script refuses to run twice
for the same fold and seed.
"""
import argparse, datetime, json, os
import numpy as np
import pandas as pd
from evaluate import deviance, fit_predict

CFG = {"learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 50, "l2_regularization": 1.0, "max_iter": 300}

def run_head(df, head, cols, seed):
    tgt = df[df.role == "target"].reset_index(drop=True)
    blocks = np.array(sorted(tgt.block.unique()))
    rng = np.random.default_rng(seed)
    grp = dict(zip(blocks[rng.permutation(len(blocks))], np.arange(len(blocks)) % 5))
    g = tgt.block.map(grp).values
    e = (tgt.exposure_m.values / 1000.0) if head == "segment" else np.ones(len(tgt))
    X = tgt[cols].to_numpy(np.float64); y = tgt.y.values.astype(float)
    mu = np.zeros(len(tgt))
    for k in range(5):
        tr, te = g != k, g == k
        mu[te] = fit_predict(CFG, X[tr], y[tr] / e[tr], e[tr], X[te], seed) * e[te]
    mu_adj = mu.copy()
    for gf in tgt.geofence_id.unique():
        m = tgt.geofence_id.values == gf
        mu_adj[m] = mu[m] * (y[m].sum() / max(mu[m].sum(), 1e-9))
    d_adj, d_raw = deviance(y, mu_adj), deviance(y, mu)
    res = {"n": int(len(tgt)), "crashes": int(y.sum()), "primary_mean_deviance": float(d_adj.mean()),
           "raw_mean_deviance": float(d_raw.mean()), "config": CFG}
    res["by_stratum"] = {s: {"n": int(m.sum()), "crashes": int(y[m].sum()), "sum_deviance": float(d_adj[m].sum())}
                         for s in tgt.stratum.unique() for m in [tgt.stratum.values == s]}
    res["by_geofence"] = {gf: {"n": int(m.sum()), "crashes": int(y[m].sum()), "sum_deviance": float(d_adj[m].sum())}
                          for gf in tgt.geofence_id.unique() for m in [tgt.geofence_id.values == gf]}
    blk = pd.DataFrame({"b": tgt.geofence_id + "|" + tgt.block.astype(str), "s": tgt.stratum, "d": d_adj, "n": 1})
    res["by_block"] = blk.groupby(["b", "s"])[["d", "n"]].sum().reset_index().values.tolist()
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("featdir"); ap.add_argument("outdir"); ap.add_argument("--fold", required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    logp = os.path.join(a.outdir, "reference.jsonl")
    if os.path.exists(logp):
        for l in open(logp):
            r = json.loads(l)
            if r["fold"] == a.fold and r["seed"] == a.seed:
                raise SystemExit(f"already evaluated: {a.fold} seed {a.seed}")
    flist = json.load(open(os.path.join(a.featdir, "feature_list.json")))
    out = {"fold": a.fold, "method": "REF", "seed": a.seed,
           "time": datetime.datetime.now(datetime.timezone.utc).isoformat(), "heads": {}}
    for head in ("segment", "intersection"):
        df = pd.read_parquet(os.path.join(a.featdir, a.fold, f"{head}.parquet"))
        out["heads"][head] = run_head(df, head, list(flist[head]["B2"]), a.seed)
    with open(logp, "a") as f:
        f.write(json.dumps(out, default=str) + "\n")
    print(a.fold, "reference written", flush=True)

if __name__ == "__main__":
    main()
