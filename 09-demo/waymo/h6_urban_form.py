"""H6: which tracts of the five Contra Costa cities resemble San Francisco tracts in urban form, and which resemble none.

Unit: census tract, clipped to land inside each city core (tracts at least half inside the core).
Form: intersection density, share of 4+ leg intersections, dead-end share, mean block (segment) length,
street km per km2, share of street length 25 mph or less, share of steep street length.
Function: place density, place-mix entropy across seven groups, shares of food-and-drink and office places.
Transit: weekday departures per km2. People: population density.
Features are standardized over all tracts of both geofences. Each Contra Costa tract gets its nearest San
Francisco tract (Euclidean distance on standardized features). A tract "resembles none" when that distance
exceeds the 90th percentile of nearest-neighbor distances among San Francisco tracts themselves.
Public data only. Writes CSV and PNG to OUT.
"""
import os, numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from features import core, streets, nodes, places, stops, tracts, street_node_degree, land_mask, GROUPS

OUT = os.path.expanduser("~/Geometis-mini/work/demo/waymo/h6"); os.makedirs(OUT, exist_ok=True)
CITIES = {"us-ca-contra-costa-5": ["Antioch", "Concord", "Pittsburg", "Pleasant Hill", "Walnut Creek"],
          "us-ca-san-francisco": ["San Francisco city"]}
rows = []
for gid, names in CITIES.items():
    st, nd, pl, sp, tr = streets(gid), nodes(gid), places(gid), stops(gid), tracts(gid)
    deg = street_node_degree(st); nd["legs"] = nd.urn.map(deg).fillna(0)
    nd = nd[nd.legs > 0]
    grp = {c: g for g, cl in GROUPS.items() for c in cl}; pl["grp"] = pl.uko_class.map(grp)
    land = land_mask(st)
    for city in names:
        cg = core(city).geometry.iloc[0].intersection(land)
        t = tr[tr.intersects(cg)].copy()
        t["geometry"] = t.geometry.intersection(cg)
        t["land_km2"] = t.area / 1e6
        t = t[(t.land_km2 > 0.2) & (t.share_in_core >= 0.5)]
        for _, r in t.iterrows():
            g = r.geometry; A = r.land_km2
            s = st[st.intersects(g)].copy(); s["L"] = s.geometry.intersection(g).length
            n = nd[nd.within(g)]; p = pl[pl.within(g)]; q = sp[sp.within(g)]
            inter = n[n.legs >= 3]
            L = s.L.sum()
            mix = p.grp.value_counts(normalize=True)
            rows.append({"geoid": r.geoid, "city": city.replace(" city", ""), "land_km2": round(A, 3),
                "intersections_per_km2": len(inter) / A,
                "four_way_share": (inter.legs >= 4).mean() if len(inter) else 0,
                "dead_end_share": (n.legs == 1).mean() if len(n) else 0,
                "mean_segment_m": s.L.mean() if len(s) else 0,
                "street_km_per_km2": L / 1000 / A,
                "slow_street_share": s.loc[s.speed_limit_mph <= 25, "L"].sum() / L if L else 0,
                "steep_share": s.loc[s.grade.abs() > 0.10, "L"].sum() / L if L else 0,
                "places_per_km2": len(p) / A,
                "place_mix_entropy": float(-(mix * np.log(mix)).sum()) if len(mix) else 0,
                "food_drink_share": (p.grp == "food_drink").mean() if len(p) else 0,
                "office_share": (p.grp == "office").mean() if len(p) else 0,
                "departures_per_km2": q.dep.fillna(0).sum() / A,
                "pop_per_km2": (r.population or 0) * min(1.0, 1.0) / A,
                "geometry": g})
df = gpd.GeoDataFrame(rows, crs=3310)
F = ["intersections_per_km2", "four_way_share", "dead_end_share", "mean_segment_m", "street_km_per_km2",
     "slow_street_share", "steep_share", "places_per_km2", "place_mix_entropy", "food_drink_share",
     "office_share", "departures_per_km2", "pop_per_km2"]
X = df[F].copy()
for c in ["places_per_km2", "departures_per_km2", "pop_per_km2", "intersections_per_km2"]:
    X[c] = np.log1p(X[c])
Z = (X - X.mean()) / X.std()
sf = df.city == "San Francisco"
# k-means urban-form types over all tracts (numpy, 20 restarts, fixed seed)
rng = np.random.default_rng(7); Zv = Z.values; K = 6; best = None
for _ in range(20):
    C = Zv[rng.choice(len(Zv), K, replace=False)]
    for _ in range(100):
        lab = ((Zv[:, None] - C[None]) ** 2).sum(-1).argmin(1)
        C2 = np.array([Zv[lab == k].mean(0) if (lab == k).any() else C[k] for k in range(K)])
        if np.allclose(C, C2): break
        C = C2
    sse = ((Zv - C[lab]) ** 2).sum()
    if best is None or sse < best[0]: best = (sse, lab.copy())
df["form_type"] = best[1]
prof = df.groupby("form_type")[F].mean().round(2)
prof["tracts_SF"] = df[sf].groupby("form_type").size(); prof["tracts_CC"] = df[~sf].groupby("form_type").size()
prof = prof.fillna(0)
prof.to_csv(os.path.join(OUT, "form_types.csv"))
print("urban-form types (feature means):"); print(prof.T.to_string())
print("\ntracts per type and city:"); print(pd.crosstab(df.city, df.form_type).to_string())
# nearest SF tract for each Contra Costa tract (SF targets: at least 1,000 residents per km2)
tgt = sf & (df.pop_per_km2 >= 1000)
Zs, Zc = Z[tgt].values, Z[~sf].values
D = np.sqrt(((Zc[:, None, :] - Zs[None, :, :]) ** 2).sum(-1))
Dss = np.sqrt(((Zs[:, None, :] - Zs[None, :, :]) ** 2).sum(-1)); np.fill_diagonal(Dss, np.inf)
nn_sf = Dss.min(1)
cc = df[~sf].copy()
cc["nearest_sf_tract"] = df[tgt].geoid.values[D.argmin(1)]
cc["dist"] = D.min(1).round(2)
cc["pct_of_sf_pairs"] = [round((nn_sf <= d).mean(), 2) for d in cc.dist]
cc["top_differences"] = [", ".join(np.array(F)[np.argsort(-np.abs(Zc[i] - Zs[D[i].argmin()]))[:3]]) for i in range(len(cc))]
out = cc.drop(columns="geometry").sort_values("dist")
out.to_csv(os.path.join(OUT, "contra_costa_matches.csv"), index=False)
df.drop(columns="geometry").to_csv(os.path.join(OUT, "tract_features.csv"), index=False)
print(f"\nSF nearest-neighbor distance: median {np.median(nn_sf):.2f}, 90th pct {np.percentile(nn_sf,90):.2f}")
print("Contra Costa nearest-SF distance by city:"); print(out.groupby("city").dist.describe()[["min","50%","max"]].round(2).to_string())
print("\nclosest matches:"); print(out.head(10)[["geoid","city","form_type","nearest_sf_tract","dist","pct_of_sf_pairs","top_differences"]].to_string(index=False))
# map: same type colors in both geofences
import matplotlib.colors as mc
cols = ["#0B7A8A", "#7DD4E3", "#C2410C", "#F2B880", "#5B5B5B", "#B8B8B8"]
cmap = mc.ListedColormap(cols[:K])
fig, axes = plt.subplots(1, 2, figsize=(18, 9))
for ax, sel, title in [(axes[0], ~sf, "Five Contra Costa cities"), (axes[1], sf, "San Francisco")]:
    df[sel].plot(ax=ax, column="form_type", cmap=cmap, vmin=-0.5, vmax=K-0.5, edgecolor="white", linewidth=0.4)
    ax.set_title(f"{title}: urban-form types by tract", fontsize=13); ax.set_axis_off()
from matplotlib.patches import Patch
fig.legend(handles=[Patch(color=cols[k], label=f"Type {k}: {int(prof.loc[k,'tracts_SF'])} SF, {int(prof.loc[k,'tracts_CC'])} CC tracts") for k in range(K)],
           loc="lower center", ncol=3, fontsize=11, frameon=False)
fig.tight_layout(rect=(0, 0.08, 1, 1)); fig.savefig(os.path.join(OUT, "h6_types_map.png"), dpi=150)
print("wrote", OUT)
