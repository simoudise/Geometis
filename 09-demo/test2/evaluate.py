"""Test 2 heads and held-out evaluation for one method on one fold.

python evaluate.py FEATURESDIR OUTDIR --fold F --method B0|B1|B2|EMB|EMB+B2 [--emb DIR] [--seed N] [--trials 8]
Runs on the Mac mini. Every feature set feeds the same head class: scikit-learn's histogram gradient boosting
with a Poisson loss, trained on source entities only (docs/test-plan-2026-11.md, Test 2). Segment heads model the
crash rate per kilometer with length as the weight, which is the Poisson model with log length as exposure;
intersection heads have no exposure term. B0 is the source mean by cell (features.py, b0_cell).

Tuning (Fable defect 10): each method draws the same number of configurations (8 by default) from a fixed space
with a fixed seed and picks the one with the lowest mean Poisson deviance under 5-fold cross-validation over the
source spatial blocks (cv_group from folds.py). Only then are held-out labels read, once: the script refuses to
run if OUTDIR/evaluations.jsonl already holds a result for this fold, method, embedding run and seed.

Measures on the held-out entities (role 'target'):
- primary: mean Poisson deviance after refitting one intercept per held-out geofence (predictions scaled so that
  their sum equals the observed crash count in that geofence); raw mean deviance reported beside it;
- secondary: share of 2021-2025 crashes on the top 5 percent of street length ranked by predicted crashes per
  kilometer (segments);
- per stratum (arterial, collector, local, intersection) and per held-out geofence, so that results can be pooled
  across folds; and per-block sums of deviance for the block bootstrap.
"""
import argparse, datetime, json, os
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

SPACE = {"learning_rate": [0.03, 0.05, 0.1], "max_leaf_nodes": [15, 31, 63], "min_samples_leaf": [20, 50, 100],
         "l2_regularization": [0.0, 1.0, 10.0], "max_iter": [300, 600]}

def deviance(y, mu):
    mu = np.clip(mu, 1e-9, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return 2 * (t - (y - mu))

def configs(n, seed):
    rng = np.random.default_rng(seed)
    return [{k: v[rng.integers(len(v))] for k, v in SPACE.items()} for _ in range(n)]

def fit_predict(cfg, Xtr, ytr, wtr, Xte, seed):
    m = HistGradientBoostingRegressor(loss="poisson", random_state=seed, early_stopping=False, **cfg)
    m.fit(Xtr, ytr, sample_weight=wtr)
    return m.predict(Xte)

def b0(src, dst, head):
    """Source mean by cell; unseen cells fall back to the class, then to the overall mean."""
    expo = (src.exposure_m / 1000.0) if head == "segment" else pd.Series(1.0, index=src.index)
    s = pd.DataFrame({"cell": src.b0_cell, "cls": src.b0_cell.str.split("|").str[0], "y": src.y, "e": expo})
    cell = s.groupby("cell").apply(lambda g: g.y.sum() / g.e.sum(), include_groups=False)
    cls = s.groupby("cls").apply(lambda g: g.y.sum() / g.e.sum(), include_groups=False)
    overall = s.y.sum() / s.e.sum()
    rate = dst.b0_cell.map(cell).fillna(dst.b0_cell.str.split("|").str[0].map(cls)).fillna(overall)
    return rate.values * ((dst.exposure_m.values / 1000.0) if head == "segment" else 1.0)

def matrix(df, method, flist, emb):
    cols = []
    if method in ("B1", "B2", "EMB+B2"):
        cols = list(flist["B1" if method == "B1" else "B2"])
    X = df[cols].to_numpy(np.float64) if cols else np.zeros((len(df), 0))
    if method in ("EMB", "EMB+B2"):
        X = np.c_[X, emb.loc[list(zip(df.geofence_id, df.urn))].to_numpy(np.float64)]
    return X

def load_emb(embdir, head):
    t = "segment" if head == "segment" else "node"
    parts = []
    for role in ("source", "target"):
        k = pd.read_parquet(os.path.join(embdir, f"keys_{t}_{role}.parquet"))
        e = np.load(os.path.join(embdir, f"emb_{t}_{role}.npy")).astype(np.float32)
        parts.append(pd.DataFrame(e, index=pd.MultiIndex.from_arrays([k.geofence_id, k.urn])).add_prefix("e"))
    return pd.concat(parts)

def run_head(df, head, method, flist, emb, trials, seed):
    src, tgt = df[df.role == "source"].reset_index(drop=True), df[df.role == "target"].reset_index(drop=True)
    expo = lambda d: (d.exposure_m.values / 1000.0) if head == "segment" else np.ones(len(d))
    tuning = []
    if method == "B0":
        mu = b0(src, tgt, head); best = None
    else:
        Xs, Xt = matrix(src, method, flist, emb), matrix(tgt, method, flist, emb)
        es = expo(src); ys = src.y.values / es
        best, best_dev = None, np.inf
        for i, cfg in enumerate(configs(trials, seed)):
            dev = []
            for g in range(5):
                tr, te = src.cv_group.values != g, src.cv_group.values == g
                mu = fit_predict(cfg, Xs[tr], ys[tr], es[tr], Xs[te], seed) * es[te]
                dev.append(deviance(src.y.values[te], mu).sum())
            mdev = float(np.sum(dev) / len(src))
            tuning.append({"trial": i, "config": cfg, "cv_mean_deviance": mdev})
            if mdev < best_dev: best, best_dev = cfg, mdev
        mu = fit_predict(best, Xs, ys, es, Xt, seed) * expo(tgt)
    # Held-out labels are read from here on.
    y = tgt.y.values.astype(float)
    mu_adj = mu.copy()
    for g in tgt.geofence_id.unique():
        m = tgt.geofence_id.values == g
        mu_adj[m] = mu[m] * (y[m].sum() / max(mu[m].sum(), 1e-9))
    d_adj, d_raw = deviance(y, mu_adj), deviance(y, mu)
    res = {"n": int(len(tgt)), "crashes": int(y.sum()), "primary_mean_deviance": float(d_adj.mean()),
           "raw_mean_deviance": float(d_raw.mean()), "best_config": best, "tuning": tuning}
    res["by_stratum"] = {s: {"n": int(m.sum()), "crashes": int(y[m].sum()), "sum_deviance": float(d_adj[m].sum())}
                         for s in tgt.stratum.unique() for m in [tgt.stratum.values == s]}
    res["by_geofence"] = {g: {"n": int(m.sum()), "crashes": int(y[m].sum()), "sum_deviance": float(d_adj[m].sum())}
                          for g in tgt.geofence_id.unique() for m in [tgt.geofence_id.values == g]}
    blk = pd.DataFrame({"b": tgt.geofence_id + "|" + tgt.block.astype(str), "s": tgt.stratum, "d": d_adj, "n": 1})
    res["by_block"] = blk.groupby(["b", "s"])[["d", "n"]].sum().reset_index().values.tolist()
    if head == "segment":
        L = tgt.exposure_m.values; order = np.argsort(-(mu / np.maximum(L / 1000.0, 1e-6)))
        top = order[: int(np.searchsorted(np.cumsum(L[order]), 0.05 * L.sum())) + 1]
        res["top5pct_length_crash_share"] = float(y[top].sum() / max(y.sum(), 1))
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("featdir"); ap.add_argument("outdir")
    ap.add_argument("--fold", required=True); ap.add_argument("--method", required=True, choices=["B0", "B1", "B2", "EMB", "EMB+B2"])
    ap.add_argument("--emb", default=""); ap.add_argument("--seed", type=int, default=0); ap.add_argument("--trials", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    logp = os.path.join(a.outdir, "evaluations.jsonl")
    key = {"fold": a.fold, "method": a.method, "emb": a.emb, "seed": a.seed}
    if os.path.exists(logp):
        for l in open(logp):
            r = json.loads(l)
            if all(r.get(k) == v for k, v in key.items()):
                raise SystemExit(f"already evaluated: {key}; held-out labels are read once per method")
    flist = json.load(open(os.path.join(a.featdir, "feature_list.json")))
    fl_sha = json.load(open(os.path.join(a.featdir, "features.json")))["feature_list_sha256"]
    out = {**key, "time": datetime.datetime.now(datetime.timezone.utc).isoformat(), "feature_list_sha256": fl_sha, "heads": {}}
    for head in ("segment", "intersection"):
        df = pd.read_parquet(os.path.join(a.featdir, a.fold, f"{head}.parquet"))
        emb = load_emb(a.emb, head) if a.method.startswith("EMB") else None
        out["heads"][head] = run_head(df, head, a.method, flist[head], emb, a.trials, a.seed)
        h = out["heads"][head]
        print(a.fold, a.method, head, "n", h["n"], "crashes", h["crashes"], "primary", round(h["primary_mean_deviance"], 4),
              "raw", round(h["raw_mean_deviance"], 4), "top5", round(h.get("top5pct_length_crash_share", float("nan")), 3), flush=True)
    with open(logp, "a") as f:
        f.write(json.dumps(out, default=str) + "\n")

if __name__ == "__main__":
    main()
