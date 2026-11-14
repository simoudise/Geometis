"""Test 2: Urban Network Analysis (UNA) reach and betweenness metrics for every road and pedestrian entity.

python network_metrics.py EXPORTDIR OUTDIR
Runs on the Mac mini (needs python-igraph). Reads the export of export.py and writes, per geofence,
OUTDIR/<geofence>/<kind>.parquet (urn plus metric columns) for kinds segment, node, ped_edge, ped_node, and
OUTDIR/manifest.json, which lists each metric with its definition and tier and the SHA-256 of each file.

Why: v19 Section 9.4 lists "the UNA reach/betweenness metrics" among the RoadSegment raw features, and Stage 6
(UNA) specifies walkshed reach with distance decay and betweenness/closeness over the pedestrian and vehicular
layers (Sevtsuk and Mekonnen, 2012, "Urban network analysis: a new toolbox for ArcGIS", Revue internationale de
geomatique 22(2)). The test plan (Test 2, B1) requires B1 to include reach and betweenness. The GKG has no
per-entity UNA metrics yet, so this script computes them from Tier P inputs only. Every metric is a fixed
function of the graph: nothing is fitted, and no label is read.

Networks, as in Test 1's reference code:
  road: every road segment, undirected, weight = length in meters.
  walk: road segments other than motorways, pedestrian edges, and access points (length 0) joining intersection
        nodes to pedestrian nodes, undirected.
Metrics (radius = network distance cutoff, as in UNA):
  btw_road_1000, btw_road_5000  shortest-path betweenness on the road network, counting only paths of at most
                                1 km or 5 km (edge betweenness for segments, vertex betweenness for nodes)
  hc_road_1000                  harmonic closeness on the road network within 1 km (nodes; a segment takes the
                                mean of its two end nodes)
  btw_walk_800                  betweenness on the walk network within 800 m (segments other than motorways,
                                pedestrian edges, intersection and pedestrian nodes)
  reach_place_800               places within 800 m on the walk network, each weighted exp(-0.002 d), where d is
                                the network distance plus the straight-line snap distance; the decay is
                                config.WALKSHED_BETA, the walkshed setting of Stage 3. A node takes its own value;
                                a segment or pedestrian edge takes the larger value of its two end nodes.
  reach_stop_400                transit stops within 400 m on the walk network, unweighted (same snapping rule).
Places and stops snap to the nearest walk-network node of the largest connected component. Motorway segments have
no walk-network metric (null); entities outside the largest component get reach 0 and their computed betweenness.
"""
import hashlib, json, os, sys, time
import numpy as np
import pandas as pd
import igraph as ig
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree

GEOFENCES = ["us-ca-contra-costa-5", "us-ca-san-francisco"]
BETA = 0.002
DEFS = {
    "btw_road_1000": "road-network betweenness, paths up to 1 km",
    "btw_road_5000": "road-network betweenness, paths up to 5 km",
    "hc_road_1000": "road-network harmonic closeness within 1 km",
    "btw_walk_800": "walk-network betweenness, paths up to 800 m",
    "reach_place_800": "places within 800 m walk, weighted exp(-0.002 d)",
    "reach_stop_400": "transit stops within 400 m walk",
}

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()

def ends(edges, rel):
    """Return a frame urn, a, b (end node urns) for line entities of relation rel."""
    e = edges[edges.rel == rel].sort_values(["src", "dst"])
    g = e.groupby("src").dst.agg(list)
    g = g[g.map(len) == 2]
    return pd.DataFrame({"urn": g.index, "a": g.map(lambda v: v[0]).values, "b": g.map(lambda v: v[1]).values})

def graph(node_urns, lines):
    """lines: frame urn, a, b, w. Returns igraph Graph, node index dict, and kept line frame (no self loops)."""
    idx = {u: i for i, u in enumerate(node_urns)}
    L = lines[lines.a.isin(idx) & lines.b.isin(idx) & (lines.a != lines.b)].copy()
    L["ia"], L["ib"] = L.a.map(idx).astype(int), L.b.map(idx).astype(int)
    G = ig.Graph(n=len(node_urns), edges=list(zip(L.ia, L.ib)), directed=False)
    G.es["w"] = np.maximum(L.w.values.astype(float), 0.01).tolist()
    return G, idx, L

def reach(n, L, xy, targets_xy, radius, weighted):
    """Per node: sum over targets within radius of exp(-beta d) (weighted) or count."""
    m = coo_matrix((np.r_[L.w, L.w].clip(0.01), (np.r_[L.ia, L.ib], np.r_[L.ib, L.ia])), shape=(n, n)).tocsr()
    _, lab = connected_components(m, directed=False)
    deg = np.bincount(np.r_[L.ia, L.ib], minlength=n)
    main = np.where((lab == np.bincount(lab).argmax()) & (deg > 0))[0]
    sd, si = cKDTree(xy[main]).query(targets_xy, k=1)
    tnode = main[si]
    # Group targets by node so that each node's Dijkstra runs once.
    tdf = pd.DataFrame({"node": tnode, "snap": sd}).groupby("node").snap.agg(list)
    src_nodes = tdf.index.values
    out = np.zeros(n)
    for k in range(0, len(src_nodes), 256):
        chunk = src_nodes[k:k + 256]
        D = dijkstra(m, directed=False, indices=chunk, limit=radius)
        for j, s in enumerate(chunk):
            near = np.nonzero(D[j] <= radius)[0]
            dn = D[j][near]
            for snap in tdf.loc[s]:
                d = dn + snap
                ok = d <= radius
                out[near[ok]] += np.exp(-BETA * d[ok]) if weighted else 1.0
    return out

def run(exportdir, gf):
    rd = lambda k, cols=None: pd.read_parquet(os.path.join(exportdir, gf, f"{k}.parquet"), columns=cols)
    seg, node = rd("segment", ["urn", "length_m", "road_classification"]), rd("node", ["urn", "x", "y"])
    ped, pnode = rd("ped_edge", ["urn", "length_m"]), rd("ped_node", ["urn", "x", "y"])
    place, stop = rd("place", ["x", "y"]), rd("stop", ["x", "y"])
    edges = rd("edges")
    se = ends(edges, "segment_node").merge(seg, on="urn")
    pe = ends(edges, "pededge_pednode").merge(ped, on="urn")
    ap = edges[edges.rel == "node_pednode"].rename(columns={"src": "a", "dst": "b"})[["a", "b"]].copy()
    ap["urn"], ap["w"] = "access", 0.0
    out = {"segment": seg[["urn"]].copy(), "node": node[["urn"]].copy(),
           "ped_edge": ped[["urn"]].copy(), "ped_node": pnode[["urn"]].copy()}
    t = time.time()
    # Road network.
    G, idx, L = graph(node.urn.tolist(), se.rename(columns={"length_m": "w"}))
    for r in (1000, 5000):
        eb = pd.Series(G.edge_betweenness(directed=False, weights="w", cutoff=r), index=L.urn.values)
        out["segment"][f"btw_road_{r}"] = out["segment"].urn.map(eb.groupby(level=0).max())
        out["node"][f"btw_road_{r}"] = G.betweenness(directed=False, weights="w", cutoff=r)
        print(gf, "road betweenness", r, round(time.time() - t), "s", flush=True)
    hc = np.array(G.harmonic_centrality(weights="w", cutoff=1000, normalized=False))
    out["node"]["hc_road_1000"] = hc
    h = pd.Series(hc, index=node.urn.values)
    out["segment"]["hc_road_1000"] = out["segment"].urn.map(((se.set_index("urn").a.map(h) + se.set_index("urn").b.map(h)) / 2))
    # Walk network.
    wnodes = node.urn.tolist() + pnode.urn.tolist()
    wxy = np.r_[node[["x", "y"]].values, pnode[["x", "y"]].values]
    wl = pd.concat([se[se.road_classification.fillna("") != "motorway"].rename(columns={"length_m": "w"})[["urn", "a", "b", "w"]],
                    pe.rename(columns={"length_m": "w"})[["urn", "a", "b", "w"]], ap[["urn", "a", "b", "w"]]], ignore_index=True)
    G, idx, L = graph(wnodes, wl)
    eb = pd.Series(G.edge_betweenness(directed=False, weights="w", cutoff=800), index=L.urn.values)
    eb = eb[eb.index != "access"].groupby(level=0).max()
    vb = pd.Series(G.betweenness(directed=False, weights="w", cutoff=800), index=wnodes)
    print(gf, "walk betweenness", round(time.time() - t), "s", flush=True)
    rp = pd.Series(reach(len(wnodes), L, wxy, place[["x", "y"]].values, 800, True), index=wnodes)
    rs = pd.Series(reach(len(wnodes), L, wxy, stop[["x", "y"]].values, 400, False), index=wnodes)
    print(gf, "reach", round(time.time() - t), "s", flush=True)
    for kind, lines in (("segment", se), ("ped_edge", pe)):
        o = out[kind]
        o["btw_walk_800"] = o.urn.map(eb)
        li = lines.set_index("urn")
        for col, s in (("reach_place_800", rp), ("reach_stop_400", rs)):
            o[col] = o.urn.map(np.maximum(li.a.map(s), li.b.map(s)))
        if kind == "segment":
            mot = o.urn.isin(seg.urn[seg.road_classification.fillna("") == "motorway"])
            o.loc[mot, ["btw_walk_800", "reach_place_800", "reach_stop_400"]] = np.nan
    for kind in ("node", "ped_node"):
        o = out[kind]
        o["btw_walk_800"], o["reach_place_800"], o["reach_stop_400"] = o.urn.map(vb), o.urn.map(rp), o.urn.map(rs)
    return out

def main():
    exportdir, outdir = sys.argv[1], sys.argv[2]
    man = {"definitions": DEFS, "tier": "P", "source": "export.py graph (Overture, OSM, GTFS); no labels read", "files": {}}
    for gf in GEOFENCES:
        d = os.path.join(outdir, gf); os.makedirs(d, exist_ok=True)
        for kind, df in run(exportdir, gf).items():
            if any("crash" in c for c in df.columns): raise SystemExit("lineage: crash column")
            p = os.path.join(d, f"{kind}.parquet"); df.to_parquet(p, index=False)
            man["files"][p] = {"rows": len(df), "sha256": sha(p)}
            desc = {c: [round(float(v), 2) for v in df[c].quantile([.05, .5, .95])] + [round(float(df[c].isna().mean()), 3)]
                    for c in df.columns if c != "urn"}
            print(gf, kind, len(df), "q05/q50/q95/null:", desc, flush=True)
    json.dump(man, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)
    print("manifest written", flush=True)

if __name__ == "__main__":
    main()
