"""Stage 1 addition: elevation of nodes and grade of segments from the USGS 3D Elevation Program (3DEP).

Source: the 3DEP seamless DEM at 1/3 arc-second (about 10 m), in 1-degree tiles named USGS_13_n{lat}w{lon}.tif,
found through The National Map's product API. Tiles are in NAD83 geographic coordinates; the builder treats them
as WGS84, which differs from NAD83 by about a metre in California, far below the DEM's resolution.

Written per geofence:
  - intersection_node.elevation_m and pedestrian_node.elevation_m (bilinear sample at the node);
  - road_segment and pedestrian_edge: elev_from_m, elev_to_m, grade (signed rise over length, from_node to
    to_node) and max_abs_grade (largest absolute grade between samples taken every GRADE_STEP_M along the line,
    with a minimum run of GRADE_STEP_M so that DEM noise on very short pieces does not produce huge grades).
Bridges and tunnels follow the ground in a DEM, so their DEM profile is wrong. Pieces that Overture flags as
bridge or tunnel (road_flags) are marked, and their grade comes from the straight line between their ends,
which still assumes the ends sit on the ground (true for most bridges, approximately).
"""
import json
import math
import urllib.parse
import urllib.request

import duckdb
import numpy as np
import rasterio
import shapely
import shapely.ops
from pyproj import Transformer

from . import config
from .db import connect
from .geofence import fetch

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
DATASET = "National Elevation Dataset (NED) 1/3 arc-second"
GRADE_STEP_M = 20.0
_to_m = Transformer.from_crs(config.STORE_CRS, config.METRIC_CRS, always_xy=True).transform
_to_ll = Transformer.from_crs(config.METRIC_CRS, config.STORE_CRS, always_xy=True).transform


def tile_names(bounds):
    xmin, ymin, xmax, ymax = bounds
    out = []
    for lat in range(math.floor(ymin) + 1, math.floor(ymax) + 2):
        for lon in range(math.floor(-xmax) + 1, math.floor(-xmin) + 2):
            out.append(f"n{lat:02d}w{lon:03d}")
    return out


def tiles(bounds):
    """Download (once) the current 1/3 arc-second tiles covering bounds; return local paths."""
    d = config.DATA_ROOT / "dem" / "3dep13"
    d.mkdir(parents=True, exist_ok=True)
    want = set(tile_names(bounds))
    have = {p.stem.split("_")[2]: p for p in d.glob("USGS_13_*.tif")}
    if want - set(have):
        q = urllib.parse.urlencode({"datasets": DATASET, "bbox": ",".join(f"{v:.4f}" for v in bounds),
                                    "prodFormats": "GeoTIFF", "max": 50})
        items = json.load(urllib.request.urlopen(f"{TNM}?{q}", timeout=120))["items"]
        for it in items:
            url = it["downloadURL"]
            name = url.rsplit("/", 1)[-1]
            if not name.startswith("USGS_13_") or not name.endswith(".tif"):
                continue
            key = name.split("_")[2].split(".")[0]
            if key in want and key not in have:
                dest = d / f"USGS_13_{key}.tif"
                tmp = dest.with_suffix(".part")
                urllib.request.urlretrieve(url, tmp)
                tmp.rename(dest)
                have[key] = dest
    missing = want - set(have)
    if missing:
        raise RuntimeError(f"3DEP tiles not found: {sorted(missing)}")
    return [have[k] for k in sorted(want)]


class Dem:
    def __init__(self, paths):
        self.ds = [rasterio.open(p) for p in paths]

    def sample(self, lon, lat):
        """Bilinear elevation in metres for arrays of lon, lat; NaN outside every tile."""
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        out = np.full(lon.shape, np.nan)
        for ds in self.ds:
            b = ds.bounds
            m = (lon >= b.left) & (lon < b.right) & (lat > b.bottom) & (lat <= b.top) & np.isnan(out)
            if not m.any():
                continue
            inv = ~ds.transform
            col, row = inv * (lon[m], lat[m])
            c0, r0 = np.floor(col - 0.5).astype(int), np.floor(row - 0.5).astype(int)
            fc, fr = col - 0.5 - c0, row - 0.5 - r0
            win = rasterio.windows.Window(c0.min(), r0.min(), c0.max() - c0.min() + 2, r0.max() - r0.min() + 2)
            a = ds.read(1, window=win, boundless=True, fill_value=np.nan).astype(float)
            if ds.nodata is not None:
                a[a == ds.nodata] = np.nan
            cc, rr = c0 - int(win.col_off), r0 - int(win.row_off)
            z = (a[rr, cc] * (1 - fc) * (1 - fr) + a[rr, cc + 1] * fc * (1 - fr)
                 + a[rr + 1, cc] * (1 - fc) * fr + a[rr + 1, cc + 1] * fc * fr)
            out[m] = z
        return out


def _profile(dem, geoms):
    """Per line: elevation at both ends, signed grade, and max absolute grade between samples."""
    pts, owner, dist = [], [], []
    for i, g in enumerate(geoms):
        gm = shapely.ops.transform(_to_m, g)
        n = max(2, int(gm.length // GRADE_STEP_M) + 1)
        ds = np.linspace(0, gm.length, n)
        for d in ds:
            pts.append(gm.interpolate(d).coords[0])
            owner.append(i)
            dist.append(d)
    xy = np.array(pts)
    lon, lat = _to_ll(xy[:, 0], xy[:, 1])
    z = dem.sample(lon, lat)
    owner, dist = np.array(owner), np.array(dist)
    out = []
    starts = np.r_[0, np.flatnonzero(np.diff(owner)) + 1, len(owner)]
    for k in range(len(geoms)):
        s, e = starts[k], starts[k + 1]
        zz, dd = z[s:e], dist[s:e]
        L = dd[-1]
        if np.isnan(zz).any() or L <= 0:
            out.append((None, None, None, None))
            continue
        grade = (zz[-1] - zz[0]) / max(L, GRADE_STEP_M)
        steps = np.diff(dd)
        g = np.abs(np.diff(zz)) / np.maximum(steps, GRADE_STEP_M)
        out.append((float(zz[0]), float(zz[-1]), float(grade), float(g.max()) if len(g) else abs(float(grade))))
    return out


def road_flags(geofence_id, extent):
    """Bridge and tunnel ranges per Overture segment id, extracted once per release and geofence."""
    out = config.DATA_ROOT / "overture" / config.OVERTURE_RELEASE / geofence_id / "road_flags.parquet"
    con = duckdb.connect()
    if not out.exists():
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET memory_limit='3GB';")
        xmin, ymin, xmax, ymax = extent.bounds
        con.execute(f"""COPY (SELECT id, road_flags FROM read_parquet('{config.OVERTURE_BASE}/type=segment/*',
                hive_partitioning=1) WHERE bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax}
                AND bbox.ymax >= {ymin} AND subtype = 'road' AND road_flags IS NOT NULL) TO '{out}.part' (FORMAT parquet)""")
        out.with_suffix(".parquet.part").rename(out)
    flags = {}
    for sid, rf in con.execute(f"SELECT id, road_flags FROM read_parquet('{out}')").fetchall():
        for r in rf or []:
            vals = set(r.get("values") or [])
            a, b = (r.get("between") or [0.0, 1.0])[:2] if r.get("between") else (0.0, 1.0)
            for f in ("is_bridge", "is_tunnel"):
                if f in vals:
                    flags.setdefault(sid, []).append((f, a, b))
    return flags


def run(geofence_id):
    core, extent, rec = fetch(geofence_id)
    paths = tiles(extent.bounds)
    dem = Dem(paths)
    stats = {"dem": "USGS 3DEP 1/3 arc-second", "tiles": [p.name for p in paths], "grade_step_m": GRADE_STEP_M}
    with connect() as conn:
        for t in ("intersection_node", "pedestrian_node"):
            conn.execute(f"ALTER TABLE gkg.{t} ADD COLUMN IF NOT EXISTS elevation_m double precision")
        for t in ("road_segment", "pedestrian_edge"):
            for c in ("elev_from_m", "elev_to_m", "grade", "max_abs_grade"):
                conn.execute(f"ALTER TABLE gkg.{t} ADD COLUMN IF NOT EXISTS {c} double precision")
            for c in ("is_bridge", "is_tunnel"):
                conn.execute(f"ALTER TABLE gkg.{t} ADD COLUMN IF NOT EXISTS {c} boolean")
        flags = road_flags(geofence_id, extent)
        for t in ("intersection_node", "pedestrian_node"):
            rows = conn.execute(f"SELECT urn, ST_X(geom), ST_Y(geom) FROM gkg.{t} WHERE geofence_id = %s",
                                (geofence_id,)).fetchall()
            z = dem.sample([r[1] for r in rows], [r[2] for r in rows])
            with conn.cursor() as cur:
                cur.executemany(f"UPDATE gkg.{t} SET elevation_m = %s WHERE geofence_id = %s AND urn = %s",
                                [(None if np.isnan(v) else float(v), geofence_id, r[0]) for r, v in zip(rows, z)])
            stats[t] = {"nodes": len(rows), "without_elevation": int(np.isnan(z).sum()),
                        "elevation_m_p5_p50_p95": [round(float(x), 1) for x in np.nanpercentile(z, [5, 50, 95])]}
        for t in ("road_segment", "pedestrian_edge"):
            rows = conn.execute(f"SELECT urn, ST_AsBinary(geom), gers_id, gers_from_frac, gers_to_frac "
                                f"FROM gkg.{t} WHERE geofence_id = %s", (geofence_id,)).fetchall()
            prof = _profile(dem, [shapely.from_wkb(r[1]) for r in rows])
            upd, nb, nt = [], 0, 0
            for r, p in zip(rows, prof):
                fl = {f for f, a, b in flags.get(r[2], []) if min(b, r[4]) > max(a, r[3])}
                br, tu = "is_bridge" in fl, "is_tunnel" in fl
                nb += br
                nt += tu
                if (br or tu) and p[2] is not None:
                    p = (p[0], p[1], p[2], abs(p[2]))  # straight line between the ends
                upd.append((*p, br, tu, geofence_id, r[0]))
            with conn.cursor() as cur:
                cur.executemany(f"UPDATE gkg.{t} SET elev_from_m = %s, elev_to_m = %s, grade = %s, max_abs_grade = %s, "
                                f"is_bridge = %s, is_tunnel = %s WHERE geofence_id = %s AND urn = %s", upd)
            prof = [u[:4] for u in upd]
            mg = np.array([p[3] for p in prof if p[3] is not None])
            stats[t] = {"edges": len(rows), "without_grade": sum(p[3] is None for p in prof),
                        "max_abs_grade_p50_p90_p99": [round(float(x), 3) for x in np.percentile(mg, [50, 90, 99])],
                        "share_over_8_percent": round(float((mg > 0.08).mean()), 4), "bridges": nb, "tunnels": nt}
        conn.execute("INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions, stats, finished, "
                     "status) VALUES (%s, 'stage1-elevation', %s, %s, %s, now(), 'loaded')",
                     (geofence_id, config.BUILDER_VERSION, json.dumps({"dem": stats["tiles"]}), json.dumps(stats)))
        conn.commit()
    return stats
