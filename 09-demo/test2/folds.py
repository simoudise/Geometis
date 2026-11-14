"""Test 2 folds: source and held-out membership, cut edges, and spatial blocks.

python folds.py EXPORTDIR OUTDIR
Runs on the Mac mini. Reads the export written by export.py (job 130) and writes, per fold:
  OUTDIR/<fold>/membership.parquet  urn, kind, geofence_id, city, role, block, cv_group
  OUTDIR/<fold>/edges_source.parquet, edges_target.parquet
and OUTDIR/folds.json with counts, label totals by role, and the SHA-256 of every file written.

Rules (docs/test-plan-2026-11.md, Test 2, "Splits" and "Tuning"):
- Three folds: hold out Walnut Creek + Pleasant Hill + Concord; hold out Antioch + Pittsburg; hold out San
  Francisco. The held-out area is the union of the held-out city cores (gkg.geofence.core, cores.parquet).
- role 'target': the entity lies inside the held-out area. Held-out labels are scored on target segments and
  intersections only.
- role 'excluded': the entity lies outside the held-out area but within 1 km of it.
- role 'source': every other entity, in both geofences, inside or outside a city core.
- An entity "lies" at its centroid. A road segment or pedestrian edge counts as source only when its centroid
  and both end nodes lie more than 1 km from the held-out area; a segment whose ends straddle the area takes
  role 'excluded'. Tracts use their centroid; a tract that straddles the boundary takes the role of its centroid.
- Graph edges are kept only between two entities of the same role (source-source or target-target). Every edge
  touching an excluded entity, and every edge between source and target, is cut.
- A spatial block is a 1 km by 1 km square in EPSG:3310 (export coordinates are already EPSG:3310). Source
  blocks are assigned at random, with a fixed seed, to 5 cross-validation groups for tuning inside the source.
"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd
import shapely

GEOFENCES = ["us-ca-contra-costa-5", "us-ca-san-francisco"]
KINDS = ["segment", "node", "place", "ped_edge", "ped_node", "stop", "tract"]
FOLDS = {
    "f1-wc-ph-concord": ["Walnut Creek", "Pleasant Hill", "Concord"],
    "f2-antioch-pittsburg": ["Antioch", "Pittsburg"],
    "f3-san-francisco": ["San Francisco city"],
}
BUFFER_M = 1000.0
BLOCK_M = 1000.0
CV_GROUPS = 5
SEED = 20261114
LINE_KINDS = {"segment": "segment_node", "ped_edge": "pededge_pednode"}

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()

def load(exportdir):
    ents, edges = [], []
    for gf in GEOFENCES:
        for kind in KINDS:
            df = pd.read_parquet(os.path.join(exportdir, gf, f"{kind}.parquet"), columns=["urn", "x", "y"])
            df["kind"], df["geofence_id"] = kind, gf
            ents.append(df)
        e = pd.read_parquet(os.path.join(exportdir, gf, "edges.parquet")); e["geofence_id"] = gf
        edges.append(e)
    ents = pd.concat(ents, ignore_index=True); edges = pd.concat(edges, ignore_index=True)
    dup = ents.duplicated(["geofence_id", "urn"]).sum()
    if dup: raise SystemExit(f"{dup} duplicate urns within a geofence")
    cores = pd.read_parquet(os.path.join(exportdir, "cores.parquet"))
    cores = {r["name"]: shapely.from_wkb(bytes(r["wkb"])) for _, r in cores.iterrows()}
    return ents, edges, cores

def city_of(ents, cores):
    pts = shapely.points(ents.x.values, ents.y.values)
    city = np.full(len(ents), "", dtype=object)
    for name, g in cores.items():
        shapely.prepare(g); city[shapely.contains(g, pts)] = name
    return city

def roles(ents, edges, held):
    """Return role per entity for one held-out area (a shapely geometry)."""
    pts = shapely.points(ents.x.values, ents.y.values)
    shapely.prepare(held)
    inside = shapely.contains(held, pts)
    dist = shapely.distance(held, pts)
    role = np.where(inside, "target", np.where(dist <= BUFFER_M, "excluded", "source")).astype(object)
    # Line entities: both end nodes must agree with the centroid.
    key = pd.Series(np.arange(len(ents)), index=pd.MultiIndex.from_arrays([ents.geofence_id, ents.urn]))
    for kind, rel in LINE_KINDS.items():
        e = edges[edges.rel == rel]
        si = key.reindex(pd.MultiIndex.from_arrays([e.geofence_id, e.src])).values
        di = key.reindex(pd.MultiIndex.from_arrays([e.geofence_id, e.dst])).values
        ok = ~(np.isnan(si) | np.isnan(di))
        si, di = si[ok].astype(int), di[ok].astype(int)
        end_inside, end_dist = inside[di], dist[di]
        # A line is source only if every end is beyond the buffer; target only if every end is inside.
        far = pd.Series(end_dist > BUFFER_M).groupby(si).all()
        allin = pd.Series(end_inside).groupby(si).all()
        idx = far.index.values
        r = role[idx]
        r = np.where((r == "source") & ~far.values, "excluded", r)
        r = np.where((r == "target") & ~allin.loc[idx].values, "excluded", r)
        role[idx] = r
    return role

def main():
    exportdir, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    ents, edges, cores = load(exportdir)
    ents["city"] = city_of(ents, cores)
    bx = np.floor(ents.x.values / BLOCK_M).astype(int); by = np.floor(ents.y.values / BLOCK_M).astype(int)
    ents["block"] = [f"{a}_{b}" for a, b in zip(bx, by)]
    labels = []
    for gf in GEOFENCES:
        l = pd.read_parquet(os.path.join(exportdir, gf, "labels.parquet")); l["geofence_id"] = gf; labels.append(l)
    labels = pd.concat(labels, ignore_index=True)
    summary = {"buffer_m": BUFFER_M, "block_m": BLOCK_M, "cv_groups": CV_GROUPS, "seed": SEED, "folds": {}, "files": {}}
    for fold, held_cities in FOLDS.items():
        missing = [c for c in held_cities if c not in cores]
        if missing: raise SystemExit(f"{fold}: no core for {missing}")
        held = shapely.union_all([cores[c] for c in held_cities])
        m = ents[["urn", "kind", "geofence_id", "city", "block"]].copy()
        m["role"] = roles(ents, edges, held)
        # Sanity: every entity whose centroid lies in a held-out core must be target or excluded.
        bad = m[m.city.isin(held_cities) & (m.role == "source")]
        if len(bad): raise SystemExit(f"{fold}: {len(bad)} held-out-core entities marked source")
        src_blocks = np.array(sorted(m.loc[m.role == "source", "block"].unique()))
        rng = np.random.default_rng([SEED, list(FOLDS).index(fold)])
        grp = dict(zip(src_blocks[rng.permutation(len(src_blocks))], np.arange(len(src_blocks)) % CV_GROUPS))
        m["cv_group"] = np.where(m.role == "source", m.block.map(grp).fillna(-1), -1).astype(int)
        d = os.path.join(outdir, fold); os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "membership.parquet"); m.to_parquet(p, index=False); summary["files"][p] = sha(p)
        role_of = pd.Series(m.role.values, index=pd.MultiIndex.from_arrays([m.geofence_id, m.urn]))
        rs = role_of.reindex(pd.MultiIndex.from_arrays([edges.geofence_id, edges.src])).values
        rd = role_of.reindex(pd.MultiIndex.from_arrays([edges.geofence_id, edges.dst])).values
        unknown = int(pd.isna(rs).sum() + pd.isna(rd).sum())
        if unknown: raise SystemExit(f"{fold}: {unknown} edge ends name no exported entity")
        es, et = edges[(rs == "source") & (rd == "source")], edges[(rs == "target") & (rd == "target")]
        cut = edges[~(((rs == "source") & (rd == "source")) | ((rs == "target") & (rd == "target")))]
        if ((rs == "source") & (rd == "target")).any() or ((rs == "target") & (rd == "source")).any():
            print(f"{fold}: note, {int(((rs == 'source') & (rd == 'target')).sum() + ((rs == 'target') & (rd == 'source')).sum())} edges joined source and target directly (cut)")
        for name, e in (("edges_source", es), ("edges_target", et)):
            p = os.path.join(d, f"{name}.parquet"); e.to_parquet(p, index=False); summary["files"][p] = sha(p)
        lab = labels.merge(m[["geofence_id", "urn", "role"]], on=["geofence_id", "urn"], how="left")
        if lab.role.isna().any(): raise SystemExit(f"{fold}: labels name entities missing from the export")
        counts = m.groupby(["kind", "role"]).size().unstack(fill_value=0)
        summary["folds"][fold] = {
            "held_out": held_cities,
            "entities": {k: {r: int(v) for r, v in row.items()} for k, row in counts.iterrows()},
            "source_blocks": int(len(src_blocks)),
            "target_blocks": int(m.loc[m.role == "target", "block"].nunique()),
            "edges": {"source": int(len(es)), "target": int(len(et)), "cut": int(len(cut))},
            "crashes_2021_2025": {f"{ent}/{r}": int(v) for (ent, r), v in
                                  lab.groupby(["entity", "role"]).crashes_2021_2025.sum().items()},
            "crashes_2015_2019_source": {ent: int(v) for ent, v in
                                         lab[lab.role == "source"].groupby("entity").crashes_2015_2019.sum().items()},
        }
        f = summary["folds"][fold]
        print(fold, "segments", f["entities"]["segment"], "nodes", f["entities"]["node"], flush=True)
        print("   blocks source", f["source_blocks"], "target", f["target_blocks"], "edges", f["edges"], flush=True)
        print("   crashes 2021-2025", f["crashes_2021_2025"], flush=True)
    json.dump(summary, open(os.path.join(outdir, "folds.json"), "w"), indent=1)
    print("folds.json written", flush=True)

if __name__ == "__main__":
    main()
