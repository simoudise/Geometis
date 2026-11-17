"""Tune one graph network on one fold inside the source cities (docs/test-plan-2026-11.md, Test 2, "Tuning").

python tune.py EXPORTDIR NETMETRICSDIR FOLDSDIR FEATURESDIR OUTDIR --fold F --network S-pub|S-full|rgcn|rgcn-eq|sage
       [--trials 8] [--seed 0]
Each network gets the same number of trials (8), drawn from its fixed space (SPACES below) with a fixed seed.
A trial trains the network on the fold's source graph with the labels of source CV group 0 hidden from any
supervised loss (L_aux in S-full; the Poisson loss in rgcn and rgcn-eq). A head with fixed settings (HEAD) is then
fitted on the trial's embeddings of source groups 1 to 4 and scored by mean Poisson deviance on source group 0,
segments and intersections together. The trial with the lowest deviance wins. No held-out label is read.
Writes OUTDIR/<fold>/<network>/tuning.json (every trial, its score and the winner).
"""
import argparse, json, os, subprocess, sys, time
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
SPACES = {
    "spectra": {"tau": [0.1, 0.15, 0.2], "lr": [5e-4, 1e-3, 2e-3], "layers": [2, 3], "p_mask_group": [0.1, 0.2, 0.3],
                "p_drop_rel": [0.1, 0.2, 0.3], "epochs": [10, 20]},
    "gnn": {"lr": [5e-4, 1e-3, 2e-3], "layers": [2, 3], "epochs": [10, 20]},
}
HEAD = {"learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 50, "l2_regularization": 1.0, "max_iter": 300}
VALID_GROUP = 0

def configs(space, n, seed):
    rng = np.random.default_rng(seed)
    return [{k: v[rng.integers(len(v))] for k, v in space.items()} for _ in range(n)]

def deviance(y, mu):
    mu = np.clip(mu, 1e-9, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return 2 * (t - (y - mu))

def score(featdir, fold, embdir):
    total, n = 0.0, 0
    for head, t in (("segment", "segment"), ("intersection", "node")):
        df = pd.read_parquet(os.path.join(featdir, fold, f"{head}.parquet"),
                             columns=["geofence_id", "urn", "role", "cv_group", "y", "exposure_m"] if head == "segment"
                             else ["geofence_id", "urn", "role", "cv_group", "y"])
        df = df[df.role == "source"]
        k = pd.read_parquet(os.path.join(embdir, f"keys_{t}_source.parquet"))
        e = np.load(os.path.join(embdir, f"emb_{t}_source.npy")).astype(np.float32)
        E = pd.DataFrame(e, index=pd.MultiIndex.from_arrays([k.geofence_id, k.urn]))
        X = E.reindex(pd.MultiIndex.from_arrays([df.geofence_id, df.urn])).to_numpy(np.float64)
        expo = (df.exposure_m.values / 1000.0) if head == "segment" else np.ones(len(df))
        tr, va = df.cv_group.values != VALID_GROUP, df.cv_group.values == VALID_GROUP
        m = HistGradientBoostingRegressor(loss="poisson", random_state=0, early_stopping=False, **HEAD)
        m.fit(X[tr], df.y.values[tr] / expo[tr], sample_weight=expo[tr])
        mu = m.predict(X[va]) * expo[va]
        total += deviance(df.y.values[va].astype(float), mu).sum(); n += int(va.sum())
    return total / n

def main():
    ap = argparse.ArgumentParser()
    for x in ("exportdir", "netdir", "foldsdir", "featdir", "outdir"): ap.add_argument(x)
    ap.add_argument("--fold", required=True); ap.add_argument("--network", required=True,
                    choices=["S-pub", "S-full", "S-pub-untyped", "S-pub-untyped-wide", "rgcn", "rgcn-eq", "sage"])
    ap.add_argument("--trials", type=int, default=8); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    spectra = a.network.startswith("S-")
    out = os.path.join(a.outdir, a.fold, a.network); os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "tuning.json")
    rec = json.load(open(path)) if os.path.exists(path) else {"network": a.network, "fold": a.fold, "head": HEAD,
                                                               "valid_group": VALID_GROUP, "trials": []}
    done = {t["trial"] for t in rec["trials"]}
    for i, cfg in enumerate(configs(SPACES["spectra" if spectra else "gnn"], a.trials, a.seed)):
        if i in done: continue
        cfg = {k: (v.item() if hasattr(v, "item") else v) for k, v in cfg.items()}
        epochs = cfg.pop("epochs"); tdir = os.path.join(out, f"trial{i}")
        if spectra:
            cmd = [sys.executable, "-u", os.path.join(HERE, "train_spectra.py"), a.exportdir, a.netdir, a.foldsdir, tdir,
                   "--fold", a.fold, "--variant", a.network, "--seed", str(a.seed), "--epochs", str(epochs)]
        else:
            cmd = [sys.executable, "-u", os.path.join(HERE, "baselines_gnn.py"), a.exportdir, a.netdir, a.foldsdir, tdir,
                   "--fold", a.fold, "--model", a.network, "--seed", str(a.seed), "--epochs", str(epochs)]
        cmd += ["--overrides", json.dumps(cfg), "--mask-cv-group", str(VALID_GROUP)]
        t0 = time.time()
        subprocess.run(cmd, check=True)
        embdir = os.path.join(tdir, a.fold, a.network, f"seed{a.seed}")
        s = score(a.featdir, a.fold, embdir)
        rec["trials"].append({"trial": i, "config": cfg, "epochs": epochs, "valid_mean_deviance": s,
                              "seconds": round(time.time() - t0)})
        print(f"{a.fold} {a.network} trial {i} {cfg} epochs {epochs}: validation deviance {s:.4f}", flush=True)
        json.dump(rec, open(path, "w"), indent=1)
    best = min(rec["trials"], key=lambda t: t["valid_mean_deviance"])
    rec["best"] = best; json.dump(rec, open(path, "w"), indent=1)
    print("best", best, flush=True)

if __name__ == "__main__":
    main()
