"""Test 2 hand-built feature sets B0, B1 and B2 for street segments and intersections, per fold.

python features.py EXPORTDIR NETMETRICSDIR FOLDSDIR OUTDIR
Runs on the Mac mini. Writes OUTDIR/<fold>/segment.parquet and OUTDIR/<fold>/intersection.parquet (source and
target rows only), and OUTDIR/feature_list.json, whose SHA-256 freezes the B1 and B2 lists before SPECTRA trains
(docs/test-plan-2026-11.md, Test 2, "Feature sets compared"; Fable defect 12).

Entities scored (Test 2 task T1, separate heads):
- Street segments: road classes trunk, primary, secondary, tertiary, residential, unclassified and living_street,
  without ramps (the catalog's street definition). Strata: arterial (trunk, primary, secondary), collector
  (tertiary), local (residential, unclassified, living_street). Motorways, ramps, service roads and tracks are
  not scored; their crashes are not in any target. They still appear in neighborhood features.
- Intersections: intersection nodes of kind 'intersection' (three or more street ends).
Labels (Tier R, never features): y = injury crashes 2021-2025; y_aux = injury crashes 2015-2019 (for L_aux and
equal supervision). Segment heads use length_m as the exposure term.

Feature sets:
- B0: no features; the column b0_cell names the cell (road class or highest incident class, by area type) whose
  source mean crash rate is the B0 prediction. Area type comes from the containing tract's population density
  with fixed cut points: under 1,000, 1,000 to 5,000, and over 5,000 people per square kilometer.
- B1: every raw Tier P input the encoder reads for the entity itself (export.py columns and the UNA metrics of
  network_metrics.py). Location (x, y) is not a feature.
- B2: B1 plus (a) the containing tract's attributes; (b) for 1, 2 and 3 hops on the road graph (segments joined
  through shared intersection nodes), the mean of neighbors' numeric attributes, the shares of neighbor road
  groups and the neighbor count; (c) for rings of 250 m, 500 m and 1 km around the centroid, counts and sums of
  places by class, transit stops and departures, intersections and dead ends, street length by road group, and
  sidewalk, crosswalk and other pedestrian-way length.
Fold rules: hop and ring features of a source entity use source entities and source edges only, and those of a
target entity use target entities and target edges only (folds.py). Nothing is fitted here: categories map to
fixed codes, missing values stay missing (the head, scikit-learn's histogram gradient boosting, handles them),
and the area-type cut points are fixed. Ring sums are computed on a 25 m grid with disk kernels, so a ring
boundary is accurate to about 25 m.
"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.signal import fftconvolve

GEOFENCES = ["us-ca-contra-costa-5", "us-ca-san-francisco"]
STREETS = {"trunk": "arterial", "primary": "arterial", "secondary": "arterial", "tertiary": "collector",
           "residential": "local", "unclassified": "local", "living_street": "local"}
ROAD_GROUP = {**STREETS, "motorway": "motorway", "service": "service", "track": "service", "unknown": "other"}
ROAD_CODES = ["motorway", "trunk", "primary", "secondary", "tertiary", "residential", "unclassified",
              "living_street", "service", "track", "unknown"]
CLASS_RANK = {c: i for i, c in enumerate(["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                                          "residential", "living_street", "service", "track", "unknown"])}
GROUPS = ["arterial", "collector", "local", "motorway", "service"]
PLACE_CLASSES = ["Restaurant", "FoodEstablishment", "GroceryStore", "SpecialtyStore", "ClothingStore",
                 "OfficeBuilding", "EducationalFacility", "HealthcareFacility", "Clinic", "EntertainmentVenue",
                 "SportsFacility", "ReligiousBuilding", "AutoRepair", "ServiceEstablishment"]
NODE_KINDS = ["intersection", "dead_end", "through"]
SPEED_SRC = ["posted", "statutory"]
NET = ["btw_road_1000", "btw_road_5000", "hc_road_1000", "btw_walk_800", "reach_place_800", "reach_stop_400"]
RINGS = [250, 500, 1000]
CELL = 25.0
DENSITY_CUTS = [1000.0, 5000.0]

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()

def code(s, cats):
    m = {c: i for i, c in enumerate(cats)}
    return s.map(m).astype("float")  # unknown or missing -> NaN

def load(exportdir, netdir, gf):
    rd = lambda k: pd.read_parquet(os.path.join(exportdir, gf, f"{k}.parquet"))
    nm = lambda k: pd.read_parquet(os.path.join(netdir, gf, f"{k}.parquet"))
    d = {k: rd(k) for k in ["segment", "node", "place", "ped_edge", "stop", "tract", "edges", "labels"]}
    d["segment"] = d["segment"].merge(nm("segment"), on="urn", how="left")
    d["node"] = d["node"].merge(nm("node"), on="urn", how="left")
    return d

def own_segment(seg):
    """B1 for segments: the segment's own raw inputs, with categories as fixed codes."""
    f = pd.DataFrame({"urn": seg.urn})
    f["length_m"] = seg.length_m
    f["road_class"] = code(seg.road_classification, ROAD_CODES)
    f["is_link"] = seg.is_link.astype(float)
    f["speed_limit_mph"] = seg.speed_limit_mph
    f["speed_limit_source"] = code(seg.speed_limit_source, SPEED_SRC)
    for c in ["grade", "max_abs_grade", "sinuosity", "bearing_deg"]: f[c] = seg[c]
    f["is_bridge"], f["is_tunnel"] = seg.is_bridge.astype(float), seg.is_tunnel.astype(float)
    for c in NET: f[c] = seg[c]
    return f

def own_node(node):
    f = pd.DataFrame({"urn": node.urn})
    f["degree"] = node.degree.astype(float)
    f["node_kind"] = code(node.node_kind, NODE_KINDS)
    f["elevation_m"] = node.elevation_m
    for c in NET: f[c] = node[c]
    return f

def hop_features(prefix, own, adj, cols, groups):
    """Mean of neighbor numeric columns over 1, 2 and 3 hops (self excluded), group shares and counts.
    own: frame aligned with adj rows; groups: frame of 0/1 group indicators aligned with adj rows."""
    out = {}
    A1 = (adj > 0).astype(np.float32).tocsr(); A1.setdiag(0); A1.eliminate_zeros()
    reach, k_adj = A1.copy(), A1.copy()
    for k in (1, 2, 3):
        if k > 1:
            k_adj = ((reach @ A1 + reach) > 0).astype(np.float32).tocsr()
            k_adj.setdiag(0); k_adj.eliminate_zeros(); reach = k_adj
        n = np.asarray(reach.sum(1)).ravel()
        out[f"{prefix}h{k}_count"] = n
        for c in cols:
            v = own[c].to_numpy(float); ok = ~np.isnan(v)
            s = reach @ np.where(ok, v, 0.0); m = reach @ ok.astype(float)
            with np.errstate(invalid="ignore", divide="ignore"):
                out[f"{prefix}h{k}_mean_{c}"] = np.where(m > 0, s / m, np.nan)
        for g in groups.columns:
            with np.errstate(invalid="ignore", divide="ignore"):
                out[f"{prefix}h{k}_share_{g}"] = np.where(n > 0, (reach @ groups[g].to_numpy(float)) / n, np.nan)
    return pd.DataFrame(out)

def ring_features(layers, queries, origin, shape):
    """layers: dict name -> (x, y, weight); queries: list of (x, y) arrays. Returns one frame of ring sums per
    query set."""
    outs = [{} for _ in queries]
    q = [(np.clip(((qx - origin[0]) / CELL).astype(int), 0, shape[0] - 1),
          np.clip(((qy - origin[1]) / CELL).astype(int), 0, shape[1] - 1)) for qx, qy in queries]
    kern = {}
    for r in RINGS:
        h = int(np.ceil(r / CELL)); ii, jj = np.mgrid[-h:h + 1, -h:h + 1]
        kern[r] = ((ii * CELL) ** 2 + (jj * CELL) ** 2 <= r * r).astype(np.float32)
    for name, (x, y, w) in layers.items():
        grid = np.zeros(shape, np.float32)
        if len(x):
            i = np.clip(((x - origin[0]) / CELL).astype(int), 0, shape[0] - 1)
            j = np.clip(((y - origin[1]) / CELL).astype(int), 0, shape[1] - 1)
            np.add.at(grid, (i, j), w)
        for r in RINGS:
            conv = fftconvolve(grid, kern[r], mode="same") if len(x) else grid
            for o, (qi, qj) in zip(outs, q):
                o[f"r{r}_{name}"] = np.round(np.maximum(conv[qi, qj], 0), 3)
    return [pd.DataFrame(o) for o in outs]

def build(d, mem, role, fold_edges):
    """Feature frames for one role in one geofence."""
    seg, node = d["segment"], d["node"]
    keep = lambda df: df[df.urn.isin(mem.index[mem == role])]
    seg_r, node_r = keep(seg).reset_index(drop=True), keep(node).reset_index(drop=True)
    place_r, ped_r, stop_r = keep(d["place"]), keep(d["ped_edge"]), keep(d["stop"])
    tract = d["tract"].set_index("urn")
    e = fold_edges
    # Road graph: segment x node incidence over this role's edges.
    sn = e[e.rel == "segment_node"]
    si = pd.Series(np.arange(len(seg_r)), index=seg_r.urn); ni = pd.Series(np.arange(len(node_r)), index=node_r.urn)
    sn = sn[sn.src.isin(si.index) & sn.dst.isin(ni.index)]
    S = sparse.csr_matrix((np.ones(len(sn), np.float32), (si[sn.src].values, ni[sn.dst].values)),
                          shape=(len(seg_r), len(node_r)))
    seg_adj, node_adj = S @ S.T, S.T @ S
    grp = seg_r.road_classification.fillna("unknown").map(ROAD_GROUP).fillna("other")
    seg_groups = pd.DataFrame({g: (grp == g).astype(float) for g in GROUPS})
    own_s, own_n = own_segment(seg_r), own_node(node_r)
    # Tract of each segment (containing its centroid), and of each node through its incident segments.
    st = e[e.rel == "segment_tract"].drop_duplicates("src").set_index("src").dst
    seg_tract = seg_r.urn.map(st)
    node_tract = sn.assign(t=sn.src.map(st)).dropna(subset=["t"]).drop_duplicates("dst").set_index("dst").t
    node_tract = node_r.urn.map(node_tract)
    tcols = ["population", "households", "zero_vehicle_share", "median_household_income", "share_below_35k",
             "share_100k_plus", "area_km2"]
    def tract_feats(t):
        f = tract.reindex(t.values)[tcols].reset_index(drop=True).add_prefix("tract_")
        f["tract_pop_density"] = f.tract_population / f.tract_area_km2
        return f
    num_s = ["length_m", "speed_limit_mph", "grade", "max_abs_grade", "sinuosity"] + NET
    hop_s = hop_features("seg_", own_s, seg_adj, num_s, seg_groups)
    # Node hops: neighbor nodes' own attributes, plus the incident-segment group mix at each hop.
    node_groups = pd.DataFrame({g: np.asarray((S.T @ seg_groups[g].to_numpy(float))).ravel() for g in GROUPS})
    deg = np.asarray(S.sum(0)).ravel()
    with np.errstate(invalid="ignore", divide="ignore"):
        node_groups = node_groups.div(np.where(deg > 0, deg, np.nan), axis=0)
    hop_n = hop_features("node_", own_n, node_adj, ["degree", "elevation_m"] + NET, node_groups)
    inc = pd.DataFrame({f"inc_share_{g}": node_groups[g] for g in GROUPS})
    inc["inc_count"] = deg
    # Rings.
    xs = np.r_[seg.x, node.x, d["place"].x]; ys = np.r_[seg.y, node.y, d["place"].y]
    origin = (xs.min() - 1500, ys.min() - 1500)
    shape = (int((xs.max() - origin[0] + 1500) / CELL) + 1, int((ys.max() - origin[1] + 1500) / CELL) + 1)
    layers = {"places": (place_r.x.values, place_r.y.values, np.ones(len(place_r)))}
    for c in PLACE_CLASSES:
        p = place_r[place_r.uko_class == c]; layers[f"place_{c}"] = (p.x.values, p.y.values, np.ones(len(p)))
    layers["places_branded"] = (place_r.x.values, place_r.y.values, place_r.has_brand.astype(float).values)
    layers["stops"] = (stop_r.x.values, stop_r.y.values, np.ones(len(stop_r)))
    layers["departures"] = (stop_r.x.values, stop_r.y.values, stop_r.departures.fillna(0).astype(float).values)
    for k in ["intersection", "dead_end"]:
        n = node_r[node_r.node_kind == k]; layers[f"nodes_{k}"] = (n.x.values, n.y.values, np.ones(len(n)))
    for g in GROUPS:
        s = seg_r[grp == g]; layers[f"len_{g}"] = (s.x.values, s.y.values, s.length_m.astype(float).values)
    for k in ["sidewalk", "crosswalk"]:
        p = ped_r[ped_r.subclass == k]; layers[f"ped_{k}_len"] = (p.x.values, p.y.values, p.length_m.astype(float).values)
    p = ped_r[~ped_r.subclass.isin(["sidewalk", "crosswalk"])]
    layers["ped_other_len"] = (p.x.values, p.y.values, p.length_m.astype(float).values)
    ring_s, ring_n = ring_features(layers, [(seg_r.x.values, seg_r.y.values), (node_r.x.values, node_r.y.values)],
                                   origin, shape)
    # Assemble.
    ts, tn = tract_feats(seg_tract), tract_feats(node_tract)
    seg_out = pd.concat([own_s.add_prefix("b1_").rename(columns={"b1_urn": "urn"}),
                         pd.concat([ts, hop_s, ring_s], axis=1).add_prefix("b2_")], axis=1)
    node_out = pd.concat([own_n.add_prefix("b1_").rename(columns={"b1_urn": "urn"}),
                          pd.concat([tn, inc, hop_n, ring_n], axis=1).add_prefix("b2_")], axis=1)
    # Street and intersection filters, labels, strata, B0 cells.
    lab = d["labels"]
    ls = lab[lab.entity == "segment"].set_index("urn"); ln = lab[lab.entity == "intersection"].set_index("urn")
    cls = seg_r.road_classification.fillna("unknown")
    street = cls.isin(list(STREETS)) & ~seg_r.is_link.astype(bool)
    def area(t):
        dens = t.tract_pop_density.to_numpy(float)
        return np.where(np.isnan(dens), "unknown", np.where(dens < DENSITY_CUTS[0], "low",
                        np.where(dens < DENSITY_CUTS[1], "mid", "high")))
    seg_out["stratum"] = cls.map(STREETS)
    seg_out["b0_cell"] = cls.values + "|" + area(ts)
    seg_out["exposure_m"] = seg_r.length_m.values
    seg_out["y"] = seg_out.urn.map(ls.crashes_2021_2025).fillna(0).astype(int)
    seg_out["y_aux"] = seg_out.urn.map(ls.crashes_2015_2019).fillna(0).astype(int)
    seg_out = seg_out[street.values]
    # An intersection's class is the highest class among its incident streets.
    top = sn.assign(r=sn.src.map(seg_r.set_index("urn").road_classification.fillna("unknown").map(CLASS_RANK)))
    top = top.groupby("dst").r.min().map({v: k for k, v in CLASS_RANK.items()})
    node_out["stratum"] = "intersection"
    node_out["b0_cell"] = node_r.urn.map(top).fillna("unknown").values + "|" + area(tn)
    node_out["y"] = node_out.urn.map(ln.crashes_2021_2025).fillna(0).astype(int)
    node_out["y_aux"] = node_out.urn.map(ln.crashes_2015_2019).fillna(0).astype(int)
    node_out = node_out[(node_r.node_kind == "intersection").values]
    return seg_out, node_out

def main():
    exportdir, netdir, foldsdir, outdir = sys.argv[1:5]
    os.makedirs(outdir, exist_ok=True)
    folds = json.load(open(os.path.join(foldsdir, "folds.json")))["folds"]
    data = {gf: load(exportdir, netdir, gf) for gf in GEOFENCES}
    lists, files = None, {}
    for fold in folds:
        mem = pd.read_parquet(os.path.join(foldsdir, fold, "membership.parquet"))
        edges = {r: pd.read_parquet(os.path.join(foldsdir, fold, f"edges_{r}.parquet")) for r in ("source", "target")}
        segs, nodes = [], []
        for gf in GEOFENCES:
            m = mem[mem.geofence_id == gf]
            role = m.set_index("urn").role
            for r in ("source", "target"):
                if not (role == r).any(): continue
                s, n = build(data[gf], role, r, edges[r][edges[r].geofence_id == gf])
                for df in (s, n):
                    df.insert(1, "geofence_id", gf); df.insert(2, "role", r)
                    meta = m.set_index("urn").reindex(df.urn)
                    df.insert(3, "block", meta.block.values); df.insert(4, "cv_group", meta.cv_group.values)
                    df.insert(5, "city", meta.city.values)
                segs.append(s); nodes.append(n)
                print(fold, gf, r, "segments", len(s), "intersections", len(n), flush=True)
        d = os.path.join(outdir, fold); os.makedirs(d, exist_ok=True)
        for name, parts in (("segment", segs), ("intersection", nodes)):
            df = pd.concat(parts, ignore_index=True)
            if any(("crash" in c) for c in df.columns): raise SystemExit("lineage: crash column among features")
            p = os.path.join(d, f"{name}.parquet"); df.to_parquet(p, index=False); files[p] = sha(p)
            print(f"  {name}: rows by role {df.groupby('role').size().to_dict()}, y by role {df.groupby('role').y.sum().to_dict()},"
                  f" y_aux by role {df.groupby('role').y_aux.sum().to_dict()}", flush=True)
        cur = {"segment": {"B1": [c for c in pd.concat(segs).columns if c.startswith("b1_")],
                           "B2": [c for c in pd.concat(segs).columns if c.startswith(("b1_", "b2_"))]},
               "intersection": {"B1": [c for c in pd.concat(nodes).columns if c.startswith("b1_")],
                                "B2": [c for c in pd.concat(nodes).columns if c.startswith(("b1_", "b2_"))]}}
        if lists is not None and cur != lists: raise SystemExit("feature lists differ between folds")
        lists = cur
    p = os.path.join(outdir, "feature_list.json")
    json.dump(lists, open(p, "w"), indent=1, sort_keys=True)
    print("feature_list.json sha256", sha(p), {k: {s: len(v) for s, v in x.items()} for k, x in lists.items()}, flush=True)
    json.dump({"files": files, "feature_list_sha256": sha(p)}, open(os.path.join(outdir, "features.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
