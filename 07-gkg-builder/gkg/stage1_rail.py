"""Stage 1, rail layer: Overture transportation segments of subtype rail, split at shared connectors, with
URNs from the URN registry and OSM-way crosswalk rows (layer 'rail').

The road stage loads subtype road only, so rail trip legs (BART, Amtrak) found no segment to conflate to
(TLP Phase 2, job 080). This stage runs after Stage 1 and leaves the road and pedestrian tables alone.
Gap against UKO 15.5: the ontology has rail routes (uko:RailRoute, uko:SubwayRoute) but no class for a
piece of rail track, so the URN kind "RailSegment" is provisional until UKO adds one.
"""
import json
from collections import Counter

import duckdb
import shapely
from shapely.geometry import Point

from . import config
from .db import connect, copy_rows
from .geofence import fetch
from .stage1_road_network import GEOD, _hex, _osm_refs, _pieces, assign_urns, write_registry


def extract(geofence_id, extent):
    out = config.DATA_ROOT / "overture" / config.OVERTURE_RELEASE / geofence_id
    out.mkdir(parents=True, exist_ok=True)
    rail_path, con_path = out / "rail_segment.parquet", out / "connector.parquet"
    if rail_path.exists():
        return rail_path, con_path
    xmin, ymin, xmax, ymax = extent.bounds
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    tmp = out / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con.execute(f"SET memory_limit='3GB'; SET threads=4; SET preserve_insertion_order=false; SET temp_directory='{tmp}'")
    bbox = f"bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin}"
    con.execute(f"""COPY (
        SELECT id, subtype, class, subclass, names."primary" AS name, connectors, sources, ST_AsWKB(geometry) AS wkb
        FROM read_parquet('{config.OVERTURE_BASE}/type=segment/*', hive_partitioning=1)
        WHERE {bbox} AND subtype = 'rail'
    ) TO '{rail_path}.part' (FORMAT parquet)""")
    (out / "rail_segment.parquet.part").rename(rail_path)
    return rail_path, con_path


def run(geofence_id):
    core, extent, rec = fetch(geofence_id)
    rail_path, con_path = extract(geofence_id, extent)
    con = duckdb.connect()
    res = con.execute(f"SELECT * FROM read_parquet('{rail_path}')")
    cols = [d[0] for d in res.description]
    segs = [dict(zip(cols, r)) for r in res.fetchall()]
    conn_geom = {cid: shapely.from_wkb(bytes(w)) for cid, w in
                 con.execute(f"SELECT id, wkb FROM read_parquet('{con_path}')").fetchall()}
    shapely.prepare(extent)
    for s in segs:
        s["geom"] = shapely.from_wkb(bytes(s["wkb"]))
        s["connectors"] = list(s["connectors"]) if s["connectors"] is not None else []
    segs = [s for s in segs if extent.intersects(s["geom"])]
    use = Counter(c["connector_id"] for s in segs for c in s["connectors"])
    split_at = {c for c, n in use.items() if n > 1}
    pieces, dropped = [], 0
    for s in segs:
        for ca, cb, fa, fb, g in _pieces(s["geom"], s["connectors"], split_at, conn_geom):
            if not extent.intersects(g):
                dropped += 1
                continue
            pieces.append((s, ca, cb, fa, fb, g))
    with connect() as conn:
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions) "
            "VALUES (%s, 'stage1-rail', %s, %s) RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION,
             json.dumps({"overture": config.OVERTURE_RELEASE, "geofence": rec["source_versions"]}))).fetchone()[0]
        urns, reg_rows, lineage, retired, summ = assign_urns(conn, geofence_id, "rail", "RailSegment", pieces)
        write_registry(conn, reg_rows, lineage, retired, config.OVERTURE_RELEASE)
        conn.execute("DELETE FROM gkg.rail_segment WHERE geofence_id = %s", (geofence_id,))
        conn.execute("DELETE FROM gkg.osm_crosswalk WHERE geofence_id = %s AND layer = 'rail'", (geofence_id,))
        rows, xw = [], []
        for (s, ca, cb, fa, fb, g), urn in zip(pieces, urns):
            rows.append((geofence_id, urn, s["id"], fa, fb, ca, cb, s["class"], s["name"], GEOD.geometry_length(g),
                         bool(core.intersects(g)), _hex(g), build_id))
            for way, ver, a, b in _osm_refs(s["sources"]):
                lo, hi = max(a, fa), min(b, fb)
                if hi > lo:
                    xw.append((geofence_id, "rail", urn, way, ver, (lo - fa) / (fb - fa), (hi - fa) / (fb - fa), build_id))
        copy_rows(conn, "gkg.rail_segment", ["geofence_id", "urn", "gers_id", "gers_from_frac", "gers_to_frac",
                  "from_connector", "to_connector", "rail_class", "name", "length_m", "in_core", "geom", "build_id"], rows)
        copy_rows(conn, "gkg.osm_crosswalk", ["geofence_id", "layer", "segment_urn", "osm_way_id", "osm_version",
                  "seg_from_frac", "seg_to_frac", "build_id"], xw)
        by_class = dict(conn.execute(
            "SELECT coalesce(rail_class, ''), round(sum(length_m)::numeric / 1000, 1) FROM gkg.rail_segment "
            "WHERE geofence_id = %s GROUP BY 1", (geofence_id,)).fetchall())
        stats = {"source_segments": len(segs), "pieces": len(rows), "crosswalk_rows": len(xw),
                 "pieces_outside_extent_dropped": dropped, "km_by_class": {k: float(v) for k, v in by_class.items()},
                 "urn_assignment": summ}
        conn.execute("UPDATE gkg.build SET stats = %s, finished = now(), status = 'loaded' WHERE build_id = %s",
                     (json.dumps(stats), build_id))
        conn.commit()
    return build_id, stats
