"""Train SPECTRA v0 on one fold's source graph, embed source and target entities, and measure position leakage.

python train_spectra.py EXPORTDIR NETMETRICSDIR FOLDSDIR OUTDIR --fold F --variant S-pub|S-full --seed N
       [--epochs 20] [--max-steps 0] [--device mps]
Writes OUTDIR/<fold>/<variant>/seed<N>/: emb_<type>_<role>.npy (transferable vector z_T, float16, M4),
keys_<type>_<role>.parquet (geofence_id, urn), train_log.json (losses, seconds per epoch, leakage probe, config).
Only source labels from 2015-2019 are read, and only in S-full (L_aux, M17). Held-out labels are never read here.
"""
import argparse, copy, json, os, time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
import spectra as S

CONFIG = {"hidden": S.H, "layers": 3, "tau": 0.15, "tau_plus": 0.05, "lr": 1e-3, "weight_decay": 1e-4,
          "tile_m": 2000.0, "halo_m": 750.0, "anchors": 512, "dm_k": 16, "dm_band_m": [50.0, 1000.0],
          "p_two_view": 0.5, "p_mask_group": 0.2, "p_drop_rel": 0.2, "p_drop_edge": 0.1,
          "lambda_gatereg": 0.01, "lambda_aux": 0.3, "w_r": 1.0, "w_s": 0.3, "w_p": 0.5,
          "feature_groups": S.FEATURE_GROUPS}

def drop_edges(edges, rng, p_rel, p_edge):
    out = {}
    for k, (s, d, ef) in edges.items():
        if rng.random() < p_rel: continue
        keep = torch.from_numpy(rng.random(len(s)) >= p_edge).to(s.device)
        out[k] = (s[keep], d[keep], ef[keep])
    return out

def random_mask(feats, rng, p):
    return {t: {k for k in list(gr) + ["shape"] if rng.random() < p} for t, gr in feats.items()}

def ff_masks():
    A = {t: set(g["function"]) for t, g in S.FEATURE_GROUPS.items()}             # view A keeps form
    B = {t: set(g["form"]) | {"shape"} for t, g in S.FEATURE_GROUPS.items()}     # view B keeps function
    return A, B

def embed(enc, G, device, w):
    """Deterministic inference (M14): eval mode, no masks, tiles in fixed order, core entities only."""
    enc.eval(); out = {t: {} for t in ("segment", "node")}; rblk = {t: {} for t in ("segment", "node")}
    with torch.no_grad():
        for tile in G.tiles(CONFIG["tile_m"]):
            sub = G.subgraph(tile, CONFIG["tile_m"], CONFIG["halo_m"])
            if not any(sub[t]["core"].any() for t in ("segment", "node")): continue
            sub, feats, shapes, locs, edges, _, _ = G.cached(tile, CONFIG["tile_m"], CONFIG["halo_m"], device)
            r, _ = enc(S.assemble(feats, shapes), edges)
            for t in ("segment", "node"):
                c = torch.from_numpy(sub[t]["core"]).to(device)
                if not c.any(): continue
                z = S.transferable(r[t][c], shapes[t][c], w["w_r"], w["w_s"])
                ids = sub[t]["ids"][sub[t]["core"]]
                for i, a, b in zip(ids, z.cpu().numpy(), r[t][c].cpu().numpy()): out[t][i] = a; rblk[t][i] = b
    return out, rblk

def leakage(rblk, G, t="segment"):
    """M13: R^2 of decoding position from the learned block r, with 5-fold spatial-block cross-validation."""
    ids = np.array(sorted(rblk[t])); X = np.stack([rblk[t][i] for i in ids]).astype(np.float64)
    xy = G.types[t]["xy"][ids]; gf = G.types[t]["gf"][ids]
    Y = xy.copy()
    for g in np.unique(gf):
        m = gf == g; Y[m] = (xy[m] - xy[m].mean(0)) / xy[m].std(0)
    groups = [f"{a}_{b}" for a, b in np.floor(xy / 1000).astype(int)]
    pred = np.zeros_like(Y)
    for tr, te in GroupKFold(5).split(X, Y, groups):
        pred[te] = Ridge(alpha=1.0).fit(X[tr], Y[tr]).predict(X[te])
    return float(1 - ((Y - pred) ** 2).sum() / ((Y - Y.mean(0)) ** 2).sum())

def main():
    ap = argparse.ArgumentParser()
    for a in ("exportdir", "netdir", "foldsdir", "outdir"): ap.add_argument(a)
    ap.add_argument("--fold", required=True); ap.add_argument("--variant", default="S-pub", choices=["S-pub", "S-full"])
    ap.add_argument("--seed", type=int, default=0); ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=0); ap.add_argument("--device", default="mps")
    a = ap.parse_args()
    device = torch.device(a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu")
    torch.manual_seed(a.seed); rng = np.random.default_rng(a.seed)
    out = os.path.join(a.outdir, a.fold, a.variant, f"seed{a.seed}"); os.makedirs(out, exist_ok=True)
    t0 = time.time()
    Gs = S.Graph(a.exportdir, a.netdir, a.foldsdir, a.fold, "source", labels=(a.variant == "S-full"))
    print("source graph loaded", {t: len(v["urn"]) for t, v in Gs.types.items()}, round(time.time() - t0), "s", flush=True)
    enc = S.Encoder(Gs.in_dims(), list(Gs.edges), layers=CONFIG["layers"]).to(device)
    init_state = copy.deepcopy(enc.state_dict())
    aux = nn.ModuleDict({"segment": nn.Linear(S.H, 1), "node": nn.Linear(S.H, 1)}).to(device)
    params = list(enc.parameters()) + (list(aux.parameters()) if a.variant == "S-full" else [])
    opt = torch.optim.AdamW(params, lr=CONFIG["lr"], weight_decay=CONFIG["weight_decay"])
    tiles = Gs.tiles(CONFIG["tile_m"]); fa, fb = ff_masks()
    log = {"config": CONFIG, "fold": a.fold, "variant": a.variant, "seed": a.seed, "device": str(device),
           "tiles": len(tiles), "epochs": []}
    step = 0
    for ep in range(a.epochs):
        te = time.time(); losses = []
        for ti in rng.permutation(len(tiles)):
            sub, feats, shapes, locs, edges, xys, rawc = Gs.cached(tiles[ti], CONFIG["tile_m"], CONFIG["halo_m"], device)
            core = [(t, i) for t in S.TYPES for i in np.where(sub[t]["core"])[0]]
            if len(core) < 16: continue
            pick = rng.choice(len(core), size=min(CONFIG["anchors"], len(core)), replace=False)
            anchors = {}
            for j in pick:
                t, i = core[j]; anchors.setdefault(t, []).append(i)
            if rng.random() < CONFIG["p_two_view"]:
                m1, m2 = random_mask(feats, rng, CONFIG["p_mask_group"]), random_mask(feats, rng, CONFIG["p_mask_group"])
                e1 = drop_edges(edges, rng, CONFIG["p_drop_rel"], CONFIG["p_drop_edge"])
                e2 = drop_edges(edges, rng, CONFIG["p_drop_rel"], CONFIG["p_drop_edge"])
            else:
                m1, m2, e1, e2 = fa, fb, edges, edges
            enc.train()
            r1, g1 = enc(S.assemble(feats, shapes, m1), e1)
            r2, g2 = enc(S.assemble(feats, shapes, m2), e2)
            A, P, N = [], [], []
            for t, ix in anchors.items():
                ix = np.array(ix)
                raw = rawc[t]
                dm = S.distance_matched(xys[t], raw, ix, CONFIG["dm_k"], tuple(CONFIG["dm_band_m"]), rng)
                ixt = torch.from_numpy(ix).to(device)
                A.append(r1[t][ixt]); P.append(r2[t][ixt])
                dmt = torch.from_numpy(np.where(dm < 0, 0, dm)).to(device)
                neg = r2[t][dmt]                                   # (n, k, d)
                neg = neg * torch.from_numpy(dm >= 0).to(device)[:, :, None]  # missing -> zero vector
                N.append(neg)
            A, P = torch.cat(A), torch.cat(P)
            k = max(n.shape[1] for n in N)
            N = torch.cat([F.pad(n, (0, 0, 0, k - n.shape[1])) for n in N])
            valid = (N.abs().sum(2) > 0)                      # padded or missing negatives are zero vectors
            loss_nce = _nce_with_dm(A, P, N, valid)
            loss = loss_nce - CONFIG["lambda_gatereg"] * (g1 + g2) / 2
            aux_l = torch.zeros((), device=device)
            if a.variant == "S-full":
                r0, _ = enc(S.assemble(feats, shapes), edges)
                for t in ("segment", "node"):
                    c = np.where(sub[t]["core"])[0]
                    if len(c) == 0: continue
                    ids = sub[t]["ids"][c]
                    y = torch.from_numpy(Gs.labels[t][ids]).to(device)
                    lr = aux[t](r0[t][torch.from_numpy(c).to(device)]).squeeze(1)
                    if t == "segment":
                        lr = lr + torch.log(torch.from_numpy(Gs.length[ids] / 1000.0).clamp(min=1e-3)).to(device)
                    aux_l = aux_l + F.poisson_nll_loss(lr, y, log_input=True)
                loss = loss + CONFIG["lambda_aux"] * aux_l
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(params, 5.0); opt.step()
            losses.append([float(loss_nce.detach()), float(aux_l.detach())]); step += 1
            if a.max_steps and step >= a.max_steps: break
        sec = time.time() - te
        log["epochs"].append({"epoch": ep, "seconds": round(sec, 1), "steps": len(losses),
                              "nce": float(np.mean([l[0] for l in losses])), "aux": float(np.mean([l[1] for l in losses]))})
        print(log["epochs"][-1], flush=True)
        if a.max_steps and step >= a.max_steps: break
    log["train_seconds"] = round(time.time() - t0, 1)
    w = {k: CONFIG[k] for k in ("w_r", "w_s")}
    te = time.time()
    emb_s, r_s = embed(enc, Gs, device, w)
    leak_trained = leakage(r_s, Gs)
    enc0 = S.Encoder(Gs.in_dims(), list(Gs.edges), layers=CONFIG["layers"]).to(device); enc0.load_state_dict(init_state)
    _, r_s0 = embed(enc0, Gs, device, w)
    log["leakage_r2"] = {"trained": leak_trained, "untrained_control": leakage(r_s0, Gs)}
    print("leakage", log["leakage_r2"], flush=True)
    keys = {"source": {t: Gs.types[t] for t in ("segment", "node")}}
    Gt = S.Graph(a.exportdir, a.netdir, a.foldsdir, a.fold, "target", labels=False)
    keys["target"] = {t: Gt.types[t] for t in ("segment", "node")}
    emb_t, _ = embed(enc, Gt, device, w)
    for role, emb in (("source", emb_s), ("target", emb_t)):
        for t in ("segment", "node"):
            ids = np.array(sorted(emb[t]))
            np.save(os.path.join(out, f"emb_{t}_{role}.npy"), np.stack([emb[t][i] for i in ids]).astype(np.float16))
            pd.DataFrame({"geofence_id": keys[role][t]["gf"][ids], "urn": keys[role][t]["urn"][ids]}).to_parquet(
                os.path.join(out, f"keys_{t}_{role}.parquet"), index=False)
    log["embed_seconds"] = round(time.time() - te, 1)
    torch.save({"encoder": enc.state_dict(), "config": CONFIG}, os.path.join(out, "encoder.pt"))
    json.dump(log, open(os.path.join(out, "train_log.json"), "w"), indent=1, default=str)
    print("done", log["train_seconds"], "s training,", log["embed_seconds"], "s embedding", flush=True)

def _nce_with_dm(A, P, N, valid, tau=CONFIG["tau"], tau_plus=CONFIG["tau_plus"]):
    """InfoNCE with debiased in-batch negatives plus distance-matched negatives (padding excluded)."""
    import math
    n = A.shape[0]
    pos = torch.exp((A * P).sum(1) / tau)
    sim = torch.exp(A @ P.T / tau).masked_fill(torch.eye(n, dtype=torch.bool, device=A.device), 0)
    Nn = max(n - 1, 1)
    ng = torch.clamp((sim.sum(1) / Nn - tau_plus * pos) / (1 - tau_plus), min=math.exp(-1 / tau)) * Nn
    dm = (torch.exp((N * A[:, None, :]).sum(2) / tau) * valid).sum(1)
    return -(torch.log(pos / (pos + ng + dm))).mean()

if __name__ == "__main__":
    main()
