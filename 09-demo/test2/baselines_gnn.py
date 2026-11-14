"""Test 2 graph baselines B4: a supervised relational graph network (R-GCN) and an unsupervised GraphSAGE.

python baselines_gnn.py EXPORTDIR NETMETRICSDIR FOLDSDIR OUTDIR --fold F --model rgcn|rgcn-eq|sage --seed N
       [--epochs 20] [--device mps]
Writes OUTDIR/<fold>/<model>/seed<N>/ in the same layout as train_spectra.py (emb_<type>_<role>.npy,
keys_<type>_<role>.parquet, train_log.json), so that evaluate.py --method EMB or EMB+B2 reads them unchanged and
every feature set feeds the same head class (docs/test-plan-2026-11.md, Test 2, "Feature sets compared").

- rgcn: B4. Relational graph convolution (Schlichtkrull et al., ESWC 2018): h_i' = W_0 h_i + sum over relations r
  of the mean over neighbors j of W_r h_j, with the same inputs (attribute and shape blocks), tiles, edges and edge
  cuts as SPECTRA. Trained end to end with a Poisson loss on source 2021-2025 injury-crash counts (segments with
  log length as exposure; intersection nodes without). Its embedding is the last hidden layer.
- rgcn-eq: the equal-supervision version for the S-full comparison (Fable defect 11): rgcn plus 2015-2019 counts
  as additional Poisson targets.
- sage: unsupervised GraphSAGE (Hamilton et al., NeurIPS 2017), mean aggregator over all relations, trained with
  the GraphSAGE loss: neighbors in the tile are positives, random tile entities are negatives.
Held-out labels are never read. Embeddings of held-out entities come from the trained network run on the held-out
graph, as for SPECTRA.
"""
import argparse, json, os, time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import spectra as S

TILE, HALO = 2000.0, 750.0
CONFIG = {"hidden": 256, "layers": 3, "lr": 1e-3, "weight_decay": 1e-4, "sage_neg": 5, "sage_pos": 512}

class RGCN(nn.Module):
    def __init__(self, in_dims, rel_keys, layers=3, hidden=256, mean_agg_all=False):
        super().__init__()
        self.enc = nn.ModuleDict({t: nn.Linear(d, hidden) for t, d in in_dims.items()})
        rk = lambda k: "__".join(k)
        self.mean_agg_all = mean_agg_all
        if mean_agg_all:  # GraphSAGE: one neighbor weight shared by all relations
            self.W = nn.ModuleList([nn.Linear(hidden, hidden) for _ in range(layers)])
        else:
            self.W = nn.ModuleList([nn.ModuleDict({rk(k): nn.Linear(hidden, hidden, bias=False) for k in rel_keys}) for _ in range(layers)])
        self.W0 = nn.ModuleList([nn.ModuleDict({t: nn.Linear(hidden, hidden) for t in in_dims}) for _ in range(layers)])
        self.layers = layers

    def forward(self, x, edges):
        h = {t: F.relu(self.enc[t](v)) for t, v in x.items()}
        for l in range(self.layers):
            new = {t: self.W0[l][t](h[t]) for t in h}
            if self.mean_agg_all:
                acc = {t: torch.zeros_like(h[t]) for t in h}; cnt = {t: torch.zeros(h[t].shape[0], device=h[t].device) for t in h}
                for (a, rel, b), (s, d, _) in edges.items():
                    acc[b].index_add_(0, d, h[a][s]); cnt[b].index_add_(0, d, torch.ones_like(d, dtype=h[a].dtype))
                for t in h:
                    new[t] = new[t] + self.W[l](acc[t] / cnt[t].clamp(min=1)[:, None])
            else:
                for k, (s, d, _) in edges.items():
                    a, rel, b = k
                    m = self.W[l]["__".join(k)](h[a][s])
                    M = torch.zeros_like(new[b]).index_add_(0, d, m)
                    c = torch.zeros(new[b].shape[0], device=m.device).index_add_(0, d, torch.ones_like(d, dtype=m.dtype))
                    new[b] = new[b] + M / c.clamp(min=1)[:, None]
            h = {t: (F.relu(v) if l < self.layers - 1 else v) for t, v in new.items()}
        return h

def embed(model, G, device):
    model.eval(); out = {"segment": {}, "node": {}}
    with torch.no_grad():
        for tile in G.tiles(TILE):
            sub = G.subgraph(tile, TILE, HALO)
            if not any(sub[t]["core"].any() for t in out): continue
            sub, feats, shapes, _, edges, _, _ = G.cached(tile, TILE, HALO, device)
            h = model(S.assemble(feats, shapes), edges)
            for t in out:
                c = sub[t]["core"]
                if not c.any(): continue
                z = h[t][torch.from_numpy(c).to(device)].cpu().numpy()
                for i, v in zip(sub[t]["ids"][c], z): out[t][i] = v
    return out

def main():
    ap = argparse.ArgumentParser()
    for a in ("exportdir", "netdir", "foldsdir", "outdir"): ap.add_argument(a)
    ap.add_argument("--fold", required=True); ap.add_argument("--model", required=True, choices=["rgcn", "rgcn-eq", "sage"])
    ap.add_argument("--seed", type=int, default=0); ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--device", default="mps")
    a = ap.parse_args()
    device = torch.device(a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu")
    torch.manual_seed(a.seed); rng = np.random.default_rng(a.seed)
    out = os.path.join(a.outdir, a.fold, a.model, f"seed{a.seed}"); os.makedirs(out, exist_ok=True)
    t0 = time.time()
    Gs = S.Graph(a.exportdir, a.netdir, a.foldsdir, a.fold, "source", labels=("with_target" if a.model != "sage" else False))
    model = RGCN(Gs.in_dims(), list(Gs.edges), CONFIG["layers"], CONFIG["hidden"], mean_agg_all=(a.model == "sage")).to(device)
    heads = nn.ModuleDict({f"{t}_{w}": nn.Linear(CONFIG["hidden"], 1) for t in ("segment", "node") for w in ("y", "aux")}).to(device)
    params = list(model.parameters()) + (list(heads.parameters()) if a.model != "sage" else [])
    opt = torch.optim.AdamW(params, lr=CONFIG["lr"], weight_decay=CONFIG["weight_decay"])
    tiles = Gs.tiles(TILE); log = {"config": CONFIG, "model": a.model, "fold": a.fold, "seed": a.seed, "epochs": []}
    for ep in range(a.epochs):
        te = time.time(); losses = []
        for ti in rng.permutation(len(tiles)):
            sub, feats, shapes, _, edges, _, _ = Gs.cached(tiles[ti], TILE, HALO, device)
            if sum(int(sub[t]["core"].sum()) for t in S.TYPES) < 16: continue
            model.train()
            h = model(S.assemble(feats, shapes), edges)
            loss = torch.zeros((), device=device)
            if a.model == "sage":
                # Positives: endpoints of edges inside the tile; negatives: random entities of the destination type.
                zs = {t: F.normalize(v, dim=1) for t, v in h.items()}
                keys = list(edges)
                for k in rng.choice(len(keys), size=min(6, len(keys)), replace=False):
                    (sa, rel, sb) = keys[k]; s, d, _ = edges[keys[k]]
                    if len(s) == 0: continue
                    pick = torch.from_numpy(rng.choice(len(s), size=min(CONFIG["sage_pos"], len(s)), replace=False)).to(device)
                    u, v = zs[sa][s[pick]], zs[sb][d[pick]]
                    neg = zs[sb][torch.from_numpy(rng.integers(0, zs[sb].shape[0], (len(pick), CONFIG["sage_neg"]))).to(device)]
                    loss = loss - F.logsigmoid((u * v).sum(1) / 0.1).mean() - F.logsigmoid(-(neg * u[:, None]).sum(2) / 0.1).mean()
            else:
                for t in ("segment", "node"):
                    c = np.where(sub[t]["core"])[0]
                    if len(c) == 0: continue
                    ids = sub[t]["ids"][c]; ct = torch.from_numpy(c).to(device)
                    off = torch.log(torch.from_numpy(Gs.length[ids] / 1000.0).clamp(min=1e-3)).to(device) if t == "segment" else 0.0
                    y = torch.from_numpy(Gs.labels["target_window"][t][ids]).to(device)
                    loss = loss + F.poisson_nll_loss(heads[f"{t}_y"](h[t][ct]).squeeze(1) + off, y, log_input=True)
                    if a.model == "rgcn-eq":
                        ya = torch.from_numpy(Gs.labels[t][ids]).to(device)
                        loss = loss + F.poisson_nll_loss(heads[f"{t}_aux"](h[t][ct]).squeeze(1) + off, ya, log_input=True)
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(params, 5.0); opt.step()
            losses.append(float(loss.detach()))
        log["epochs"].append({"epoch": ep, "seconds": round(time.time() - te, 1), "steps": len(losses), "loss": float(np.mean(losses))})
        print(log["epochs"][-1], flush=True)
    log["train_seconds"] = round(time.time() - t0, 1)
    keys = {"source": {t: Gs.types[t] for t in ("segment", "node")}}
    emb = {"source": embed(model, Gs, device)}
    Gt = S.Graph(a.exportdir, a.netdir, a.foldsdir, a.fold, "target", labels=False)
    keys["target"] = {t: Gt.types[t] for t in ("segment", "node")}
    emb["target"] = embed(model, Gt, device)
    for role in ("source", "target"):
        for t in ("segment", "node"):
            ids = np.array(sorted(emb[role][t]))
            np.save(os.path.join(out, f"emb_{t}_{role}.npy"), np.stack([emb[role][t][i] for i in ids]).astype(np.float16))
            pd.DataFrame({"geofence_id": keys[role][t]["gf"][ids], "urn": keys[role][t]["urn"][ids]}).to_parquet(
                os.path.join(out, f"keys_{t}_{role}.parquet"), index=False)
    json.dump(log, open(os.path.join(out, "train_log.json"), "w"), indent=1, default=str)
    print("done", log["train_seconds"], "s", flush=True)

if __name__ == "__main__":
    main()
