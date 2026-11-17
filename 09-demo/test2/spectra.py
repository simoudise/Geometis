"""SPECTRA v0 for Test 2: data, encoder, samplers and losses.

Follows the v19 SPECTRA review patch (Drive file "v19 patch - SPECTRA review decisions", edits M1 to M18) as far
as Test 2 needs it:
- M1: no path head, no co-corridor positives, no path loss. Positives are 50 percent two-view pairs (two random
  views of the same node: dropped relations, dropped edges, masked feature groups, as in GRACE and BGRL) and
  50 percent form-versus-function pairs (view A keeps the form groups and masks the function groups; view B does
  the reverse). FEATURE_GROUPS records the assignment.
- M2: negatives are distance-matched negatives of the same node type (drawn from a band of straight-line distance
  around the anchor, because both positive types pair a node with itself) plus in-batch negatives with the
  debiased correction of Chuang et al. (NeurIPS 2020); candidates whose raw features nearly equal the anchor's are
  excluded. InfoNCE temperature 0.15.
- M3: the attribute block and the shape block enter the encoder; the location block never does. Relative position
  enters through edge features (inter-centroid distance and bearing).
- M4: three separately normalized blocks; the transferable vector z_T = [w_r r | w_s s] / sqrt(w_r^2 + w_s^2) has
  no absolute position; the local vector is p. Heads read z_T only.
- M7: Tier P inputs only (export.py lineage manifest and network_metrics.py). M8: no city indicator.
  M9: fixed, unit-based transforms (TRANSFORMS below); nothing is fitted on data.
- M12: location encoding scales start at 50 m. M13: leakage probe in train_spectra.py. M14: deterministic
  inference (eval mode, no masks, fixed tile order).
- M17: L_aux, Poisson heads on 2015-2019 crash counts of source segments and intersections, weight 0.3, S-full only.
Gaps (flagged, not hidden): the export has no polygon or polyline geometry, so the shape block holds a few
descriptors (length, sinuosity, orientation, grade, area) rather than the 64 learned shape descriptors of v19
Section 9.5.4; buildings and land use are not in the export, so view B of form-versus-function uses places,
census and transit only.
"""
import math, os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy.spatial import cKDTree

GEOFENCES = ["us-ca-contra-costa-5", "us-ca-san-francisco"]
TYPES = ["segment", "node", "place", "ped_edge", "ped_node", "stop", "tract"]
RELS = {  # relation name in export -> (source type, destination type)
    "segment_node": ("segment", "node"), "pededge_pednode": ("ped_edge", "ped_node"),
    "node_pednode": ("node", "ped_node"), "stop_segment": ("stop", "segment"),
    "place_segment": ("place", "segment"), "segment_tract": ("segment", "tract"),
    "place_tract": ("place", "tract"), "stop_tract": ("stop", "tract"),
}
ROAD = ["motorway", "trunk", "primary", "secondary", "tertiary", "residential", "unclassified", "living_street",
        "service", "track", "unknown"]
UKO = ["ServiceEstablishment", "Clinic", "Restaurant", "OfficeBuilding", "SpecialtyStore", "HealthcareFacility",
       "AutoRepair", "SportsFacility", "ReligiousBuilding", "ClothingStore", "DentalClinic", "FoodEstablishment",
       "EntertainmentVenue", "EducationalFacility", "GroceryStore", "Hotel", "Bar", "Cafe", "Bank", "Pharmacy",
       "GasStation", "Park", "School", "ParkingFacility"]
STOP_UKO = ["BusStop", "TransitStop", "StationEntrance", "StopLocation", "TransitStation"]
PED_CLASS = ["footway", "path", "cycleway", "steps", "pedestrian", "bridleway"]
PED_SUB = ["sidewalk", "crosswalk", "cycle_crossing"]
NODE_KIND = ["intersection", "dead_end", "through"]
SHAPE_DIM, LOC_DIM, H = 8, 64, 256

# Feature groups for the form-versus-function views (M1j). Form: street and network form and geometry.
# Function: points of interest, census and transit context.
FEATURE_GROUPS = {
    "segment": {"form": ["road", "speed", "grade", "flags", "net"], "function": ["reach"]},
    "node": {"form": ["kind", "elev", "net"], "function": ["reach"]},
    "place": {"form": [], "function": ["category"]},
    "ped_edge": {"form": ["ped"], "function": []},
    "ped_node": {"form": ["deg"], "function": []},
    "stop": {"form": [], "function": ["stop"]},
    "tract": {"form": [], "function": ["census"]},
}

def onehot(s, cats):
    m = {c: i for i, c in enumerate(cats)}
    idx = s.map(m)
    out = np.zeros((len(s), len(cats) + 1), np.float32)
    out[np.arange(len(s)), idx.fillna(len(cats)).astype(int).values] = 1.0
    return out

def num(s, f, missing_bit=True):
    v = s.astype(float).values
    miss = np.isnan(v)
    x = np.where(miss, 0.0, f(np.where(miss, 0.0, v))).astype(np.float32)[:, None]
    return np.c_[x, miss.astype(np.float32)] if missing_bit else x

LOG = lambda c: (lambda v: np.log1p(np.maximum(v, 0)) / c)
NET_T = {"btw_road_1000": LOG(10), "btw_road_5000": LOG(14), "hc_road_1000": LOG(3), "btw_walk_800": LOG(12),
         "reach_place_800": LOG(5), "reach_stop_400": LOG(3)}

def attributes(kind, df):
    """Return dict group -> float32 array (fixed, unit-based transforms, M9) and the shape block."""
    n = len(df); g = {}; shape = np.zeros((n, SHAPE_DIM), np.float32)
    if kind == "segment":
        g["road"] = np.c_[onehot(df.road_classification, ROAD), df.is_link.astype(np.float32).values[:, None]]
        g["speed"] = np.c_[num(df.speed_limit_mph, lambda v: v / 70), onehot(df.speed_limit_source, ["posted", "statutory"])]
        g["grade"] = np.c_[num(df.grade, lambda v: np.clip(v * 10, -3, 3), False), num(df.max_abs_grade, lambda v: np.clip(v * 10, 0, 5), False)]
        g["flags"] = np.c_[df.is_bridge.astype(np.float32).values, df.is_tunnel.astype(np.float32).values]
        g["net"] = np.concatenate([num(df[c], NET_T[c]) for c in ["btw_road_1000", "btw_road_5000", "hc_road_1000", "btw_walk_800"]], 1)
        g["reach"] = np.concatenate([num(df[c], NET_T[c]) for c in ["reach_place_800", "reach_stop_400"]], 1)
        th = np.radians(df.bearing_deg.astype(float).fillna(0).values)
        shape[:, 0] = np.log1p(df.length_m.astype(float).values) / 8
        shape[:, 1] = np.log(np.clip(df.sinuosity.astype(float).fillna(1).values, 1, 50))
        shape[:, 2], shape[:, 3] = np.sin(2 * th), np.cos(2 * th)
        shape[:, 4] = np.clip(df.grade.astype(float).fillna(0).values * 10, -3, 3)
    elif kind == "node":
        g["kind"] = np.c_[onehot(df.node_kind, NODE_KIND), np.clip(df.degree.astype(float).values, 0, 8)[:, None] / 4]
        g["elev"] = num(df.elevation_m, lambda v: v / 500)
        g["net"] = np.concatenate([num(df[c], NET_T[c]) for c in ["btw_road_1000", "btw_road_5000", "hc_road_1000", "btw_walk_800"]], 1)
        g["reach"] = np.concatenate([num(df[c], NET_T[c]) for c in ["reach_place_800", "reach_stop_400"]], 1)
    elif kind == "place":
        g["category"] = np.c_[onehot(df.uko_class, UKO), df.has_brand.astype(np.float32).values[:, None],
                              num(df.confidence, lambda v: v, False)]
    elif kind == "ped_edge":
        g["ped"] = np.c_[onehot(df.edge_class, PED_CLASS), onehot(df.subclass, PED_SUB)]
        shape[:, 0] = np.log1p(df.length_m.astype(float).values) / 8
    elif kind == "ped_node":
        g["deg"] = np.clip(df.degree.astype(float).values, 0, 8)[:, None].astype(np.float32) / 4
    elif kind == "stop":
        g["stop"] = np.c_[onehot(df.uko_class, STOP_UKO), onehot(df.location_type.astype("Int64").astype(str), ["0", "1", "2"]),
                          num(df.departures, LOG(6)), num(df.route_count, lambda v: v / 10, False)]
    elif kind == "tract":
        g["census"] = np.c_[num(df.population, LOG(10)), num(df.households, LOG(9)), num(df.zero_vehicle_share, lambda v: v),
                            num(df.median_household_income, lambda v: v / 250000), num(df.share_below_35k, lambda v: v),
                            num(df.share_100k_plus, lambda v: v)]
        shape[:, 6] = np.log1p(df.area_km2.astype(float).values) / 5
    return {k: v.astype(np.float32) for k, v in g.items()}, shape

def location_encoding(x, y):
    """Fixed sinusoidal encoding, 16 scales from 50 m to 50 km (M12), 64 dimensions. Output-only (M3)."""
    scales = np.geomspace(50, 50000, 16)
    ex = x[:, None] * (2 * np.pi / scales[None, :]); ey = y[:, None] * (2 * np.pi / scales[None, :])
    return np.c_[np.sin(ex), np.cos(ex), np.sin(ey), np.cos(ey)].astype(np.float32)

class Graph:
    """All entities of one role in one fold, both geofences, with typed edges and features."""
    def __init__(self, exportdir, netdir, foldsdir, fold, role, labels=True):
        mem = pd.read_parquet(os.path.join(foldsdir, fold, "membership.parquet"))
        mem = mem[mem.role == role]
        edges = pd.read_parquet(os.path.join(foldsdir, fold, f"edges_{role}.parquet"))
        self.types = {}
        for t in TYPES:
            parts = []
            for gf in GEOFENCES:
                df = pd.read_parquet(os.path.join(exportdir, gf, f"{t}.parquet"))
                if t in ("segment", "node", "ped_edge", "ped_node"):
                    df = df.merge(pd.read_parquet(os.path.join(netdir, gf, f"{t}.parquet")), on="urn", how="left")
                df["geofence_id"] = gf
                mk = mem[(mem.geofence_id == gf) & (mem.kind == t)].set_index("urn").cv_group
                df = df[df.urn.isin(mk.index)].copy(); df["cv_group"] = df.urn.map(mk).values
                parts.append(df)
            df = pd.concat(parts, ignore_index=True)
            groups, shape = attributes(t, df)
            self.types[t] = {"urn": df.urn.values, "gf": df.geofence_id.values,
                             "xy": df[["x", "y"]].to_numpy(np.float64), "groups": groups, "shape": shape,
                             "cv": df.cv_group.to_numpy(np.int64)}
        self.index = {t: pd.Series(np.arange(len(v["urn"])), index=pd.MultiIndex.from_arrays([v["gf"], v["urn"]]))
                      for t, v in self.types.items()}
        self.edges = {}
        for rel, (a, b) in RELS.items():
            e = edges[edges.rel == rel]
            si = self.index[a].reindex(pd.MultiIndex.from_arrays([e.geofence_id, e.src])).values
            di = self.index[b].reindex(pd.MultiIndex.from_arrays([e.geofence_id, e.dst])).values
            ok = ~(np.isnan(si) | np.isnan(di))
            si, di = si[ok].astype(np.int64), di[ok].astype(np.int64)
            self.edges[(a, rel, b)] = (si, di)
            self.edges[(b, rel + "_rev", a)] = (di, si)
        self.labels = {}
        if labels:
            lab = pd.concat([pd.read_parquet(os.path.join(exportdir, gf, "labels.parquet")).assign(geofence_id=gf) for gf in GEOFENCES])
            for t, ent in (("segment", "segment"), ("node", "intersection")):
                l = lab[lab.entity == ent]
                y = np.zeros(len(self.types[t]["urn"]), np.float32)
                ix = self.index[t].reindex(pd.MultiIndex.from_arrays([l.geofence_id, l.urn])).values
                ok = ~np.isnan(ix)
                y[ix[ok].astype(int)] = l.crashes_2015_2019.values[ok]  # L_aux window only (M17)
                self.labels[t] = y
                if labels == "with_target":  # source 2021-2025 counts, for supervised baselines (B4) only
                    y2 = np.zeros_like(y); y2[ix[ok].astype(int)] = l.crashes_2021_2025.values[ok]
                    self.labels.setdefault("target_window", {})[t] = y2
        segdf = pd.concat([pd.read_parquet(os.path.join(exportdir, gf, "segment.parquet"), columns=["urn", "length_m"]).assign(geofence_id=gf) for gf in GEOFENCES])
        ix = self.index["segment"].reindex(pd.MultiIndex.from_arrays([segdf.geofence_id, segdf.urn])).values
        ok = ~np.isnan(ix)
        self.length = np.ones(len(self.types["segment"]["urn"]), np.float32)
        self.length[ix[ok].astype(int)] = segdf.length_m.values[ok]
        # Spatial index over all entities, for tiles. Geofences are far apart in EPSG:3310, so tiles never mix them.
        self.all_xy = np.concatenate([v["xy"] for v in self.types.values()])
        self.offsets = np.cumsum([0] + [len(v["urn"]) for v in self.types.values()])

    def in_dims(self):
        return {t: sum(g.shape[1] for g in v["groups"].values()) + SHAPE_DIM for t, v in self.types.items()}

    def tiles(self, size=2000.0):
        """Core tiles: 2 km squares holding at least one entity, in a fixed order."""
        k = np.unique(np.floor(self.all_xy / size).astype(np.int64), axis=0)
        return [tuple(r) for r in k]

    def cached(self, tile, size, halo, device):
        """Subgraph and tensors of one tile, built once per run and reused every epoch. The cache changes how
        batches are assembled, not what they contain."""
        if not hasattr(self, "_cache"): self._cache = {}
        if tile not in self._cache:
            sub = self.subgraph(tile, size, halo)
            feats, shapes, locs, edges, xys = build_batch(self, sub, device)
            raw = {t: np.concatenate([g[sub[t]["ids"]] for g in self.types[t]["groups"].values()]
                                     + [self.types[t]["shape"][sub[t]["ids"]]], 1) for t in sub}
            self._cache[tile] = (sub, feats, shapes, locs, edges, xys, raw)
        return self._cache[tile]

    def subgraph(self, tile, size=2000.0, halo=750.0):
        """Induced subgraph of entities within the tile plus a halo. Returns local indices per type and core masks."""
        x0, y0 = tile[0] * size, tile[1] * size
        sub = {}
        for t, v in self.types.items():
            xy = v["xy"]
            inh = (xy[:, 0] >= x0 - halo) & (xy[:, 0] < x0 + size + halo) & (xy[:, 1] >= y0 - halo) & (xy[:, 1] < y0 + size + halo)
            core = (xy[:, 0] >= x0) & (xy[:, 0] < x0 + size) & (xy[:, 1] >= y0) & (xy[:, 1] < y0 + size)
            ids = np.where(inh)[0]
            sub[t] = {"ids": ids, "core": core[ids]}
        return sub

def edge_features(xa, xb):
    d = xb - xa
    dist = np.hypot(d[:, 0], d[:, 1]); th = np.arctan2(d[:, 1], d[:, 0])
    return np.c_[np.log1p(dist) / 8, np.sin(th), np.cos(th)].astype(np.float32)

def build_batch(G, sub, device):
    """Tensors for one subgraph: per-type group tensors, shape, location, edges with features."""
    feats, shapes, locs, xys = {}, {}, {}, {}
    for t, s in sub.items():
        v = G.types[t]; ids = s["ids"]
        feats[t] = {k: torch.from_numpy(g[ids]).to(device) for k, g in v["groups"].items()}
        shapes[t] = torch.from_numpy(v["shape"][ids]).to(device)
        xy = v["xy"][ids]; xys[t] = xy
        locs[t] = torch.from_numpy(location_encoding(xy[:, 0], xy[:, 1])).to(device)
    edges = {}
    for (a, rel, b), (si, di) in G.edges.items():
        la = pd.Series(np.arange(len(sub[a]["ids"])), index=sub[a]["ids"]); lb = pd.Series(np.arange(len(sub[b]["ids"])), index=sub[b]["ids"])
        m = np.isin(si, sub[a]["ids"]) & np.isin(di, sub[b]["ids"])
        if not m.any(): continue
        s_, d_ = la[si[m]].values, lb[di[m]].values
        ef = edge_features(xys[a][s_], xys[b][d_])
        edges[(a, rel, b)] = (torch.from_numpy(s_).to(device), torch.from_numpy(d_).to(device), torch.from_numpy(ef).to(device))
    return feats, shapes, locs, edges, xys

class Encoder(nn.Module):
    def __init__(self, in_dims, rel_keys, layers=3, hidden=H, untyped=False):
        super().__init__()
        self.untyped = untyped
        self.enc = nn.ModuleDict({t: nn.Sequential(nn.Linear(d, hidden), nn.ReLU(), nn.Linear(hidden, hidden)) for t, d in in_dims.items()})
        if untyped:
            # S-pub-untyped (change log, Nov 17): one message function and one update and normalization layer shared by
            # every relation and node type; messages from all incoming edges are averaged together, so no relation-
            # specific parameter or gate remains (a gate over one pooled message is the identity). Per-type input
            # encoders stay, because node types have different input widths.
            self.msg_u = nn.ModuleList([nn.Linear(hidden + 3, hidden) for _ in range(layers)])
            self.self_u = nn.ModuleList([nn.Linear(hidden, hidden) for _ in range(layers)])
            self.norm_u = nn.ModuleList([nn.LayerNorm(hidden) for _ in range(layers)])
            self.out = nn.Linear(hidden, hidden)
            self.layers, self.hidden, self.rel_keys, self.last_gates = layers, hidden, list(rel_keys), []
            return
        self.rel_keys = [k for k in rel_keys]
        rk = lambda k: "__".join(k)
        self.msg = nn.ModuleList([nn.ModuleDict({rk(k): nn.Linear(hidden + 3, hidden) for k in self.rel_keys}) for _ in range(layers)])
        self.gate = nn.ModuleList([nn.ModuleDict({rk(k): nn.Linear(hidden, 1) for k in self.rel_keys}) for _ in range(layers)])
        self.self_lin = nn.ModuleList([nn.ModuleDict({t: nn.Linear(hidden, hidden) for t in in_dims}) for _ in range(layers)])
        self.norm = nn.ModuleList([nn.ModuleDict({t: nn.LayerNorm(hidden) for t in in_dims}) for _ in range(layers)])
        self.out = nn.Linear(hidden, hidden)
        self.layers, self.hidden = layers, hidden
        self.last_gates = []

    def forward(self, x, edges, drop_rel=None):
        """x: type -> (n_t, in_dim) input (attribute groups and shape block concatenated). Returns r per type and
        the mean relation-gate entropy (for L_gatereg)."""
        h = {t: self.enc[t](v) for t, v in x.items()}
        if self.untyped:
            return self._forward_untyped(h, edges)
        ent = []
        for l in range(self.layers):
            agg = {t: [] for t in h}; logits = {t: [] for t in h}
            for k, (s, d, ef) in edges.items():
                a, rel, b = k
                if drop_rel and k in drop_rel: continue
                rk = "__".join(k)
                m = self.msg[l][rk](torch.cat([h[a][s], ef], 1))
                M = torch.zeros_like(h[b]).index_add_(0, d, m)
                c = torch.zeros(h[b].shape[0], device=m.device).index_add_(0, d, torch.ones_like(d, dtype=m.dtype))
                has = c > 0
                M = M / c.clamp(min=1)[:, None]
                g = self.gate[l][rk](h[b]).squeeze(1).masked_fill(~has, -1e4)
                agg[b].append(M); logits[b].append(g)
            new = {}
            for t in h:
                upd = self.self_lin[l][t](h[t])
                if agg[t]:
                    L = torch.stack(logits[t], 1); w = torch.softmax(L, 1)
                    has_any = (L > -1e3).any(1, keepdim=True).float()
                    w = w * has_any
                    upd = upd + (torch.stack(agg[t], 1) * w[:, :, None]).sum(1)
                    p = w.clamp_min(1e-8); ent.append(-(p * p.log()).sum(1)[has_any.squeeze(1) > 0].mean() if has_any.sum() > 0 else torch.zeros((), device=upd.device))
                new[t] = F.relu(self.norm[l][t](h[t] + upd))
            h = new
        r = {t: F.normalize(self.out(v), dim=1) for t, v in h.items()}
        gent = torch.stack(ent).mean() if ent else torch.zeros(())
        return r, gent

    def _forward_untyped(self, h, edges):
        for l in range(self.layers):
            M = {t: torch.zeros_like(v) for t, v in h.items()}
            c = {t: torch.zeros(v.shape[0], device=v.device) for t, v in h.items()}
            for (a, rel, b), (s, d, ef) in edges.items():
                m = self.msg_u[l](torch.cat([h[a][s], ef], 1))
                M[b].index_add_(0, d, m)
                c[b].index_add_(0, d, torch.ones_like(d, dtype=m.dtype))
            h = {t: F.relu(self.norm_u[l](h[t] + self.self_u[l](h[t]) + M[t] / c[t].clamp(min=1)[:, None])) for t in h}
        r = {t: F.normalize(self.out(v), dim=1) for t, v in h.items()}
        return r, torch.zeros(())

def matched_width(in_dims, rel_keys, layers, step=8):
    """Hidden width at which the untyped encoder has about as many parameters as the typed encoder with width H on the
    same inputs, relations and layers (secondary width-matched check, change log Nov 17)."""
    n = lambda m: sum(p.numel() for p in m.parameters())
    target = n(Encoder(in_dims, rel_keys, layers, H, untyped=False))
    best = min(range(H, 4 * H + 1, step), key=lambda w: abs(n(Encoder(in_dims, rel_keys, layers, w, untyped=True)) - target))
    return best, target

def assemble(feats, shapes, mask_groups=None):
    """Concatenate attribute groups (masked groups zeroed) and the shape block, per type."""
    x = {}
    for t, gr in feats.items():
        parts = []
        for k, v in gr.items():
            parts.append(torch.zeros_like(v) if mask_groups and k in mask_groups.get(t, ()) else v)
        parts.append(torch.zeros_like(shapes[t]) if mask_groups and "shape" in mask_groups.get(t, ()) else shapes[t])
        x[t] = torch.cat(parts, 1)
    return x

def transferable(r, shape, w_r=1.0, w_s=0.3):
    """z_T = [w_r r | w_s s] / sqrt(w_r^2 + w_s^2), s = L2-normalized shape block (M4)."""
    s = F.normalize(shape, dim=1, eps=1e-6)
    return torch.cat([w_r * r, w_s * s], 1) / math.sqrt(w_r ** 2 + w_s ** 2)

def info_nce(a, p, dm_neg, tau=0.15, tau_plus=0.05):
    """a, p: (n, d) anchor and positive (unit norm). dm_neg: (n, k, d) distance-matched negatives (may be empty).
    In-batch negatives use the debiased estimator of Chuang et al. (2020)."""
    n = a.shape[0]
    pos = torch.exp((a * p).sum(1) / tau)
    sim = torch.exp(a @ p.T / tau)
    off = sim.masked_fill(torch.eye(n, dtype=torch.bool, device=a.device), 0)
    N = max(n - 1, 1)
    ng = (off.sum(1) / N - tau_plus * pos) / (1 - tau_plus)
    ng = torch.clamp(ng, min=math.exp(-1 / tau)) * N
    denom = pos + ng
    if dm_neg is not None and dm_neg.shape[1] > 0:
        denom = denom + torch.exp((dm_neg * a[:, None, :]).sum(2) / tau).sum(1)
    return -(torch.log(pos / denom)).mean()

def distance_matched(xy, raw, anchors, k=16, band=(50.0, 1000.0), rng=None, dup_cos=0.995):
    """For each anchor (local index), k same-type candidates at straight-line distance within the band,
    excluding near-duplicate raw feature vectors (false-negative control). Returns (n, k) indices, -1 if missing."""
    tree = cKDTree(xy)
    out = -np.ones((len(anchors), k), np.int64)
    rn = raw / (np.linalg.norm(raw, axis=1, keepdims=True) + 1e-8)
    for i, a in enumerate(anchors):
        cand = np.array(tree.query_ball_point(xy[a], band[1]), np.int64)
        if len(cand) == 0: continue
        dd = np.hypot(*(xy[cand] - xy[a]).T)
        cand = cand[(dd >= band[0])]
        if len(cand) == 0: continue
        cand = cand[(rn[cand] @ rn[a]) < dup_cos]
        if len(cand) == 0: continue
        pick = rng.choice(cand, size=min(k, len(cand)), replace=False)
        out[i, :len(pick)] = pick
    return out
