"""H7: propose a first automated ride service area of about 10 km2 in San Francisco.

Cells of 250 m. A cell's value is its count of short-trip destinations. Penalties: intersections with five or
more street legs, steep street length (max grade above 10 percent), and street length posted above 35 mph.
A greedy search grows a connected area from each of the 40 best seed cells and keeps the best total score;
running it for several penalty weights gives the trade-off between destinations served and the three costs.
Writes CSV, GeoJSON and PNG maps to OUT. Public data only.
"""
import os, json, numpy as np, pandas as pd, geopandas as gpd
from shapely.geometry import box
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from features import core, streets, nodes, places, street_node_degree, complex_intersections, SHORT_TRIP

OUT = os.path.expanduser("~/Geometis-mini/work/demo/waymo/h7"); os.makedirs(OUT, exist_ok=True)
GID, CITY, CELL, TARGET_KM2 = "us-ca-san-francisco", "San Francisco city", 250, 10.0

c = core(CITY); land = c.geometry.iloc[0]
st, nd, pl = streets(GID), nodes(GID), places(GID)
# land mask: only cells that touch streets (removes water and the Farallones)
st = st[st.intersects(land)]
xmin, ymin, xmax, ymax = st.total_bounds
cells = gpd.GeoDataFrame({"geometry": [box(x, y, x + CELL, y + CELL)
          for x in np.arange(xmin, xmax, CELL) for y in np.arange(ymin, ymax, CELL)]}, crs=3310)
cells["cid"] = range(len(cells))
# street features per cell
parts = gpd.overlay(st[["urn", "speed_limit_mph", "speed_limit_source", "grade", "geometry"]], cells, how="intersection", keep_geom_type=True)
parts["L"] = parts.length
g = parts.groupby("cid")
cells["street_m"] = g["L"].sum()
cells["fast_m"] = parts[parts.speed_limit_mph > 35].groupby("cid")["L"].sum()
cells["steep_m"] = parts[parts.grade.abs() > 0.10].groupby("cid")["L"].sum()
cells = cells.fillna(0)
cells = cells[cells.street_m > 300].copy()
# complex intersections: 5+ legs on the street network
cxn = complex_intersections(st)
cxn.to_file(os.path.join(OUT, "complex_intersections.geojson"), driver="GeoJSON")
cx = gpd.sjoin(cxn, cells[["cid", "geometry"]], predicate="within")
cells["complex_nodes"] = cells.cid.map(cx.groupby("cid").size()).fillna(0)
pj = gpd.sjoin(pl[pl.uko_class.isin(SHORT_TRIP)], cells[["cid", "geometry"]], predicate="within")
cells["dest"] = cells.cid.map(pj.groupby("cid").size()).fillna(0)
cells["fast_share"] = cells.fast_m / cells.street_m
cells["steep_share"] = cells.steep_m / cells.street_m
cells.to_file(os.path.join(OUT, "cells.geojson"), driver="GeoJSON")

# adjacency (rook) for connectivity
idx = {(round(b.bounds[0]), round(b.bounds[1])): cid for cid, b in zip(cells.cid, cells.geometry)}
def nbrs(cid, b):
    x, y = round(b.bounds[0]), round(b.bounds[1])
    for dx, dy in ((CELL,0),(-CELL,0),(0,CELL),(0,-CELL)):
        k = (x+dx, y+dy)
        if k in idx: yield idx[k]
geom = dict(zip(cells.cid, cells.geometry))
N = int(TARGET_KM2 * 1e6 / CELL**2)

def score_cells(w):
    d = cells.set_index("cid")
    return (d.dest - w[0]*d.complex_nodes*10 - w[1]*d.steep_share*100 - w[2]*d.fast_share*100)

def grow(seed, s):
    area, frontier = {seed}, set(nbrs(seed, geom[seed]))
    while len(area) < N and frontier:
        best = max(frontier, key=lambda c: s[c]); area.add(best); frontier.discard(best)
        frontier |= {n for n in nbrs(best, geom[best]) if n not in area}
    return area

results = []
for name, w in {"destinations only": (0,0,0), "balanced": (1,1,1), "avoid hills": (1,4,1), "strict": (3,3,3)}.items():
    s = score_cells(w)
    seeds = s.sort_values(ascending=False).index[:40]
    best = max((grow(sd, s) for sd in seeds), key=lambda a: s[list(a)].sum())
    sel = cells[cells.cid.isin(best)]
    rec = {"weights": name, "cells": len(sel), "km2": round(len(sel)*CELL**2/1e6,2),
           "destinations": int(sel.dest.sum()),
           "share_of_city_destinations": round(sel.dest.sum()/cells.dest.sum(),3),
           "complex_intersections": int(sel.complex_nodes.sum()),
           "steep_share": round(sel.steep_m.sum()/sel.street_m.sum(),3),
           "fast_share": round(sel.fast_m.sum()/sel.street_m.sum(),3)}
    results.append(rec)
    sel.dissolve().to_file(os.path.join(OUT, f"area_{name.replace(' ','_')}.geojson"), driver="GeoJSON")
city = {"weights": "whole city (reference)", "cells": len(cells), "km2": round(len(cells)*CELL**2/1e6,1),
        "destinations": int(cells.dest.sum()), "share_of_city_destinations": 1.0,
        "complex_intersections": int(cells.complex_nodes.sum()),
        "steep_share": round(cells.steep_m.sum()/cells.street_m.sum(),3),
        "fast_share": round(cells.fast_m.sum()/cells.street_m.sum(),3)}
res = pd.DataFrame(results + [city]); res.to_csv(os.path.join(OUT, "tradeoff.csv"), index=False)
print(res.to_string(index=False))

# map: one large panel per weighting, streets for context
for name in ["destinations only", "balanced", "avoid hills"]:
    fig, ax = plt.subplots(figsize=(10, 10))
    st.plot(ax=ax, color="#BBBBBB", linewidth=0.3)
    cells[cells.dest > 0].plot(ax=ax, column="dest", cmap="Greys", vmax=cells.dest.quantile(0.98), alpha=0.55, linewidth=0)
    a = gpd.read_file(os.path.join(OUT, f"area_{name.replace(' ','_')}.geojson"))
    a.boundary.plot(ax=ax, color="#0B7A8A", linewidth=3)
    cxn.plot(ax=ax, color="#C2410C", markersize=10)
    r = res[res.weights == name].iloc[0]
    ax.set_title(f"San Francisco: candidate first service area, weights '{name}'\n"
                 f"{r.km2} km2 holds {r.share_of_city_destinations:.0%} of the city's short-trip destinations; "
                 f"{r.complex_intersections} complex intersections; steep street share {r.steep_share:.1%}", fontsize=11)
    ax.set_axis_off(); fig.tight_layout()
    fig.savefig(os.path.join(OUT, f"h7_map_{name.replace(' ','_')}.png"), dpi=150); plt.close(fig)
print("wrote", OUT)
