"""Build and store geofence records (task A1, geofence input spec).

A geofence record holds a core (the union of Census place boundaries) and an extent (the core
buffered far enough to contain the routes between the core's tracts). Every loader reads only
this record for its geography.
"""
import json
import random
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
import shapely
from shapely.geometry import LineString, MultiPolygon
from shapely.ops import transform
from pyproj import Transformer

from . import config
from .db import connect, copy_rows

_to_metric = Transformer.from_crs(config.STORE_CRS, config.METRIC_CRS, always_xy=True).transform
_to_store = Transformer.from_crs(config.METRIC_CRS, config.STORE_CRS, always_xy=True).transform


def tiger_zip(layer, state_fips):
    """Download a TIGER/Line state file once and return its local path."""
    v = config.TIGER_VINTAGE
    dest = config.DATA_ROOT / "tiger" / str(v) / f"tl_{v}_{state_fips}_{layer}.zip"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = config.TIGER_URL.format(v=v, layer_upper=layer.upper(), state=state_fips, layer=layer)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(r.content)
        zipfile.ZipFile(tmp).testzip()
        tmp.rename(dest)
    return dest


def _as_multi(geom):
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    return geom


def load_definition(path):
    d = json.loads(Path(path).read_text())
    d["geoids"] = [m["geoid"] for m in d["members"]]
    return d


def build_core(defn):
    """Union of the member places, checked against the expected names."""
    places = gpd.read_file(f"zip://{tiger_zip('place', defn['state_fips'])}").to_crs(config.STORE_CRS)
    sel = places[places["GEOID"].isin(defn["geoids"])]
    found = dict(zip(sel["GEOID"], sel["NAME"]))
    for m in defn["members"]:
        if found.get(m["geoid"]) != m["name"]:
            raise ValueError(f"GEOID {m['geoid']} is {found.get(m['geoid'])!r} in TIGER, expected {m['name']!r}")
    members = {g: _as_multi(shapely.make_valid(geom)) for g, geom in zip(sel["GEOID"], sel.geometry)}
    core = _as_multi(shapely.union_all(list(members.values())))
    return core, members


def tract_points(core, state_fips):
    """One interior point per tract that intersects the core, kept only if the point lies in the core."""
    tracts = gpd.read_file(f"zip://{tiger_zip('tract', state_fips)}").to_crs(config.STORE_CRS)
    tracts = tracts[tracts.intersects(core)]
    pts = tracts.geometry.representative_point()
    return [p for p in pts if core.contains(p)]


def _route(session, a, b):
    url = f"{config.OSRM_CAR_URL}/route/v1/driving/{a.x},{a.y};{b.x},{b.y}?overview=full&geometries=geojson"
    try:
        r = session.get(url, timeout=30)
        j = r.json()
    except Exception:
        return None
    if j.get("code") != "Ok" or not j.get("routes"):
        return None
    # A point far from any road (an island, open water) snaps to a distant road, and its routes then run far
    # outside the core for reasons unrelated to how residents travel; such pairs are left out of the test.
    if max(w.get("distance", 0) for w in j.get("waypoints", [])) > config.BUFFER_MAX_SNAP_M:
        return "far"
    coords = j["routes"][0]["geometry"]["coordinates"]
    return LineString(coords) if len(coords) >= 2 else None


def buffer_test(core, points, max_pairs=None, seed=20261103):
    """Find the smallest buffer for which less than the threshold share of route length falls outside.

    Routes are computed once by car on the local OSRM server between every pair of tract points
    (one direction per pair); each candidate buffer is then tested against the same routes.
    """
    pairs = [(i, j) for i in range(len(points)) for j in range(i + 1, len(points))]
    if max_pairs and len(pairs) > max_pairs:
        random.Random(seed).shuffle(pairs)
        pairs = pairs[:max_pairs]
    print(f"buffer test: {len(points)} tract points, {len(pairs)} pairs", flush=True)
    with requests.Session() as s, ThreadPoolExecutor(8) as ex:
        routes = list(ex.map(lambda p: _route(s, points[p[0]], points[p[1]]), pairs))
    far = sum(1 for r in routes if isinstance(r, str))
    ok = [transform(_to_metric, r) for r in routes if r is not None and not isinstance(r, str)]
    result = {"tract_points": len(points), "pairs": len(pairs), "routed": len(ok),
              "pairs_dropped_point_far_from_road": far, "max_snap_m": config.BUFFER_MAX_SNAP_M,
              "threshold": config.BUFFER_OUTSIDE_THRESHOLD, "osrm": config.OSRM_REGION, "steps": []}
    if len(ok) < 0.9 * max(1, len(pairs) - far):
        result["status"] = "not_run: fewer than 90 per cent of pairs routed (outside the OSRM extract?)"
        return config.BUFFER_START_M, result
    routes_m = shapely.simplify(np.array(ok, dtype=object), 5.0)
    total = float(shapely.length(routes_m).sum())
    core_m = transform(_to_metric, core)
    b = config.BUFFER_START_M
    while True:
        ext = core_m.buffer(b)
        shapely.prepare(ext)
        inside = float(shapely.length(shapely.intersection(routes_m, ext)).sum())
        outside = (total - inside) / total
        result["steps"].append({"buffer_m": b, "outside_share": round(outside, 6)})
        if outside < config.BUFFER_OUTSIDE_THRESHOLD:
            result["status"] = "passed"
            return b, result
        if b >= config.BUFFER_MAX_M:
            result["status"] = f"stopped at the {config.BUFFER_MAX_M} m cap without passing"
            return b, result
        b += config.BUFFER_STEP_M


def derive_states_counties(extent, state_fips):
    """States and counties that the extent touches, read from the national TIGER county file."""
    v = config.TIGER_VINTAGE
    dest = config.DATA_ROOT / "tiger" / str(v) / f"tl_{v}_us_county.zip"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(f"https://www2.census.gov/geo/tiger/TIGER{v}/COUNTY/tl_{v}_us_county.zip", timeout=600)
        r.raise_for_status()
        dest.write_bytes(r.content)
    counties = gpd.read_file(f"zip://{dest}", bbox=tuple(extent.bounds)).to_crs(config.STORE_CRS)
    counties = counties[counties.intersects(extent)]
    states = sorted(set(counties["STATEFP"]))
    return states, sorted(set(counties["STATEFP"] + counties["COUNTYFP"]))


def build_record(defn_path, run_buffer_test=True, max_pairs=None):
    defn = load_definition(defn_path)
    core, members = build_core(defn)
    print(f"core built from {len(members)} places", flush=True)
    if run_buffer_test:
        pts = tract_points(core, defn["state_fips"])
        buffer_m, test = buffer_test(core, pts, max_pairs=max_pairs)
    else:
        buffer_m, test = config.BUFFER_START_M, {"status": "not_run: disabled"}
    extent = _as_multi(transform(_to_store, transform(_to_metric, core).buffer(buffer_m)))
    print(f"buffer {buffer_m} m: {test.get('status')}", flush=True)
    states, counties = derive_states_counties(extent, defn["state_fips"])
    versions = {"tiger": config.TIGER_VINTAGE, "overture": config.OVERTURE_RELEASE,
                "builder": config.BUILDER_VERSION}
    rec = dict(geofence_id=defn["geofence_id"], name=defn["name"], members=defn["geoids"],
               graph_geofence_id=defn["geofence_id"], core=core, buffer_m=buffer_m, buffer_test=test,
               extent=extent, states=states, counties=counties, source_versions=versions)
    singles = []
    if defn.get("fingerprint_records") and len(members) > 1:
        names = {m["geoid"]: m["name"] for m in defn["members"]}
        for g, geom in members.items():
            singles.append(dict(geofence_id=f"{defn['geofence_id']}--{g}", name=names[g], members=[g],
                                graph_geofence_id=defn["geofence_id"], core=geom, buffer_m=None,
                                buffer_test=None, extent=None, states=states, counties=None,
                                source_versions=versions))
    return rec, singles


def _hex(geom):
    return None if geom is None else shapely.to_wkb(shapely.set_srid(geom, 4326), hex=True, include_srid=True)


def store(records):
    cols = ["geofence_id", "name", "members", "graph_geofence_id", "boundary_source", "core", "buffer_m",
            "buffer_test", "extent", "states", "counties", "source_versions", "spec_version"]
    with connect() as conn:
        ids = [r["geofence_id"] for r in records]
        conn.execute("DELETE FROM gkg.geofence WHERE geofence_id = ANY(%s)", (ids,))
        rows = [(r["geofence_id"], r["name"], r["members"], r["graph_geofence_id"],
                 f"Census TIGER/Line Places {config.TIGER_VINTAGE}", _hex(r["core"]), r["buffer_m"],
                 None if r["buffer_test"] is None else json.dumps(r["buffer_test"]), _hex(r["extent"]),
                 r["states"], r["counties"], json.dumps(r["source_versions"]), config.SPEC_VERSION)
                for r in records]
        copy_rows(conn, "gkg.geofence", cols, rows)
        conn.commit()


def fetch(geofence_id):
    """Return (core, extent, record dict) for a stored geofence."""
    with connect() as conn:
        row = conn.execute(
            "SELECT ST_AsBinary(core), ST_AsBinary(extent), graph_geofence_id, buffer_m, source_versions "
            "FROM gkg.geofence WHERE geofence_id = %s", (geofence_id,)).fetchone()
    if row is None:
        raise KeyError(geofence_id)
    return shapely.from_wkb(row[0]), shapely.from_wkb(row[1]), {"graph_geofence_id": row[2], "buffer_m": row[3],
                                                                 "source_versions": row[4]}
