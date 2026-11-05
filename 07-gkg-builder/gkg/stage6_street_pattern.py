"""Stage 6 street-pattern measures that need no transit data, computed inside the core of a geofence.

Measures follow Boeing (2019), "Urban spatial order: street network orientation, configuration, and
entropy", Applied Network Science 4:67:
  - orientation entropy H_o over 36 bins of 10 degrees, each segment counted in both directions and
    weighted by length, and the orientation order phi = 1 - ((H_o - H_g) / (H_max - H_g))^2, with
    H_max = ln 36 (uniform) and H_g = ln 4 (a perfect grid);
  - average circuity: total segment length divided by total straight-line distance between segment ends;
  - node shares: dead ends (one street end), three-way and four-way-or-more nodes, and intersection density.

Two networks are measured: all vehicular segments, and the same without service roads and tracks
(closer to the "drive" network Boeing uses). Segments are first merged through degree-2 nodes (a simplified graph, as in Boeing); bearings and
circuity are taken from simplified-edge end to end in the metric CRS, and node shares count nodes of degree
other than 2.
"""
import json
import math

import geopandas as gpd
import numpy as np
import shapely
from shapely.ops import transform
from pyproj import Transformer

from . import config
from .db import connect
from .geofence import fetch, tiger_zip

_to_m = Transformer.from_crs(config.STORE_CRS, config.METRIC_CRS, always_xy=True).transform
H_MAX, H_GRID = math.log(36), math.log(4)
EXCLUDED = ("service", "track")


def orientation(bearings, weights):
    b = np.r_[bearings, (bearings + 180.0) % 360.0]
    w = np.r_[weights, weights]
    # Bins centred on 0, 10, ..., 350 degrees, as in Boeing (2019).
    idx = (np.floor((b + 5.0) / 10.0).astype(int)) % 36
    p = np.bincount(idx, weights=w, minlength=36)
    p = p / p.sum()
    h = float(-(p[p > 0] * np.log(p[p > 0])).sum())
    return h, 1.0 - ((h - H_GRID) / (H_MAX - H_GRID)) ** 2


def load(conn, graph_id):
    rows = conn.execute(
        "SELECT ST_X(ST_StartPoint(geom)), ST_Y(ST_StartPoint(geom)), ST_X(ST_EndPoint(geom)), "
        "ST_Y(ST_EndPoint(geom)), ST_X(ST_LineInterpolatePoint(geom, 0.5)), ST_Y(ST_LineInterpolatePoint(geom, 0.5)), "
        "length_m, from_node, to_node, coalesce(road_classification, '') FROM gkg.road_segment "
        "WHERE geofence_id = %s", (graph_id,)).fetchall()
    a = np.array([r[:7] for r in rows], dtype=float)
    return a, [r[7] for r in rows], [r[8] for r in rows], np.array([r[9] for r in rows])


def simplify(idx, a, fr, to):
    """Merge chains of segments through degree-2 nodes into single edges, as in a simplified graph.

    Returns, per simplified edge, the start and end coordinates (degrees) and the total length, plus the
    degree of every remaining node.
    """
    adj, xy = {}, {}
    for i in idx:
        adj.setdefault(fr[i], []).append(i)
        adj.setdefault(to[i], []).append(i)
        xy[fr[i]] = (a[i, 0], a[i, 1])
        xy[to[i]] = (a[i, 2], a[i, 3])
    deg = {n: len(e) for n, e in adj.items()}
    seen, edges = set(), []
    for n0, es in adj.items():
        if deg[n0] == 2:
            continue
        for e in es:
            if e in seen:
                continue
            seen.add(e)
            length, cur = a[e, 6], (to[e] if fr[e] == n0 else fr[e])
            last = e
            while deg[cur] == 2 and cur != n0:
                nxt = [x for x in adj[cur] if x != last]
                if not nxt or nxt[0] in seen:
                    break
                last = nxt[0]
                seen.add(last)
                length += a[last, 6]
                cur = to[last] if fr[last] == cur else fr[last]
            edges.append((xy[n0][0], xy[n0][1], xy[cur][0], xy[cur][1], length))
    kept = {n: d for n, d in deg.items() if d != 2}
    return np.array(edges, dtype=float), np.array(list(kept.values()))


def measures(seg, core, exclude, land_km2=None):
    a, fr, to, cls = seg
    mask = shapely.contains_xy(core, a[:, 4], a[:, 5])
    if exclude:
        mask &= ~np.isin(cls, EXCLUDED)
    idx = np.where(mask)[0]
    e, d = simplify(idx, a, fr, to)
    x0, y0 = _to_m(e[:, 0], e[:, 1])
    x1, y1 = _to_m(e[:, 2], e[:, 3])
    straight = np.hypot(x1 - x0, y1 - y0)
    length = e[:, 4]
    ok = straight >= 0.01  # self-loops have no bearing and no straight-line distance
    bearing = (np.degrees(np.arctan2(x1 - x0, y1 - y0)) + 360.0) % 360.0
    h, phi = orientation(bearing[ok], length[ok])
    area_km2 = transform(_to_m, core).area / 1e6
    # Densities divide by land area (TIGER ALAND of the member places), because place polygons can include
    # large water areas (San Francisco's covers about 600 km2, most of it bay and ocean).
    dens_km2 = land_km2 or area_km2
    return {
        "segments": int(len(idx)), "simplified_edges": int(len(e)),
        "length_km": round(float(a[idx, 6].sum()) / 1000, 1),
        "orientation_entropy": round(h, 4), "orientation_order_phi": round(phi, 4),
        "circuity_avg": round(float(length[ok].sum() / straight[ok].sum()), 4),
        "nodes": int(len(d)), "share_dead_end": round(float((d == 1).sum()) / len(d), 4),
        "share_three_way": round(float((d == 3).sum()) / len(d), 4),
        "share_four_way_plus": round(float((d >= 4).sum()) / len(d), 4),
        "intersections_per_km2_land": round(float((d >= 3).sum()) / dens_km2, 1),
        "street_km_per_km2_land": round(float(a[idx, 6].sum()) / 1000 / dens_km2, 2),
        "land_area_km2": round(dens_km2, 1),
        "core_area_km2": round(area_km2, 1),
    }


def run(geofence_id):
    """Measures for the geofence and for each one-member fingerprint record that uses its graph."""
    with connect() as conn:
        ids = [geofence_id] + [r[0] for r in conn.execute(
            "SELECT geofence_id FROM gkg.geofence WHERE graph_geofence_id = %s AND geofence_id <> %s "
            "ORDER BY 1", (geofence_id, geofence_id)).fetchall()]
        members = dict(conn.execute("SELECT geofence_id, members FROM gkg.geofence WHERE geofence_id = ANY(%s)",
                                    (ids,)).fetchall())
        names = dict(conn.execute("SELECT geofence_id, name FROM gkg.geofence WHERE geofence_id = ANY(%s)",
                                  (ids,)).fetchall())
        seg = load(conn, geofence_id)
    out = {"method": "Boeing (2019), Applied Network Science 4:67; segments whose midpoint lies in the core",
           "records": {}}
    aland = {}
    for st in sorted({m[:2] for ms in members.values() for m in ms}):
        t = gpd.read_file(f"zip://{tiger_zip('place', st)}", ignore_geometry=True)
        aland.update(dict(zip(t["GEOID"], t["ALAND"].astype(float))))
    for gid in ids:
        core, _, _ = fetch(gid)
        shapely.prepare(core)
        land = sum(aland.get(m, 0.0) for m in members[gid]) / 1e6 or None
        out["records"][gid] = {"name": names[gid], "all_vehicular": measures(seg, core, False, land),
                               "without_service_and_track": measures(seg, core, True, land)}
    with connect() as conn:
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions, stats, finished, status) "
            "VALUES (%s, 'stage6-street-pattern', %s, %s, %s, now(), 'loaded') RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION, json.dumps({"overture": config.OVERTURE_RELEASE}),
             json.dumps(out))).fetchone()[0]
        conn.commit()
    return build_id, out
