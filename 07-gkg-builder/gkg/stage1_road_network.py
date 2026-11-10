"""Knowledge Builder Stage 1: base road network and pedestrian multiplex (v19 section 9.3, Stage 1).

Input: one stored geofence record. The loader reads Overture transportation segments and
connectors inside the record's extent, splits segments at shared connectors, mints URNs,
flags entities inside the core, builds the OpenStreetMap-to-URN crosswalk, and couples the
vehicular and pedestrian layers through shared connectors.
"""
import json
import uuid
from collections import Counter, defaultdict

import duckdb
import shapely
from pyproj import Geod
from shapely.geometry import Point
from shapely.ops import substring

from pyproj import Transformer
from shapely.ops import transform

from . import config, urn_registry
from .db import connect, copy_rows
from .geofence import fetch

GEOD = Geod(ellps="WGS84")
URN_NS = uuid.UUID("6f1c2a5e-3b7d-4e8a-9c41-0d2b7e5f9a10")  # fixed namespace for minted GeoMetis ids


def mint(kind, *parts):
    return f"urn:urban-kg:{kind}:overture:{uuid.uuid5(URN_NS, '|'.join(str(p) for p in parts))}"


_to_m = Transformer.from_crs(config.STORE_CRS, config.METRIC_CRS, always_xy=True).transform


def assign_urns(conn, geofence_id, layer, kind, pieces):
    """URN for each piece: reuse through the URN registry when an earlier build of this geofence exists.

    Returns (list of URNs aligned with pieces, list of registry rows, lineage rows, retired URNs, summary).
    """
    table = {"vehicular": "road_segment", "pedestrian": "pedestrian_edge", "rail": "rail_segment"}[layer]
    release = config.OVERTURE_RELEASE
    keys = [f"{s['id']}|{fa:.6f}|{fb:.6f}" for s, ca, cb, fa, fb, g in pieces]
    prev = conn.execute(
        f"SELECT t.urn, t.gers_id, t.gers_from_frac, t.gers_to_frac, ST_AsBinary(t.geom), "
        f"b.source_versions->>'overture' FROM gkg.{table} t JOIN gkg.build b USING (build_id) "
        f"WHERE t.geofence_id = %s", (geofence_id,)).fetchall()
    known = dict(conn.execute("SELECT piece_key, urn FROM gkg.urn_registry WHERE kind = %s "
                              "AND retired_release IS NULL AND piece_key = ANY(%s)", (kind, keys)).fetchall())
    prev_release = prev[0][5] if prev else None
    lineage, retired = [], []
    if not prev:
        urns = [known.get(k) or mint(kind, *k.split("|")) for k in keys]
        how = ["kept" if k in known else "minted" for k in keys]
    else:
        old = [urn_registry.Piece(f"{g}|{fa:.6f}|{fb:.6f}", g, transform(_to_m, shapely.from_wkb(w)), u)
               for u, g, fa, fb, w, _ in prev]
        new = [urn_registry.Piece(k, s["id"], transform(_to_m, g)) for k, (s, ca, cb, fa, fb, g) in zip(keys, pieces)]
        a = urn_registry.assign(old, new, release, kind=kind)
        used = {o.urn for o in old}
        urns, how = [], []
        for k in keys:
            st = a.status[k]
            if k in known:
                u, st = known[k], "kept"
            elif st in ("kept", "rematched"):
                u = a.urns[k]
            else:
                # Split, merge and added pieces get the usual deterministic URN, unless that URN already named
                # an earlier piece; then the release is added so a new entity never takes an old entity's URN.
                u = mint(kind, *k.split("|"))
                if u in used:
                    u = mint(kind, *k.split("|"), release)
            urns.append(u)
            how.append(st)
        remap = {a.urns[k]: u for k, u in zip(keys, urns)}
        lineage = [(o, remap.get(n, n), r) for o, n, r in a.lineage]
        retired = a.retired if prev_release != release else []
    reg_rows = [(u, kind, k.split("|")[0], k, release, release, None, h, json.dumps(
        {"end_m": config.URN_MATCH_END_M, "hausdorff_m": config.URN_MATCH_HAUSDORFF_M,
         "length_share": config.URN_MATCH_LENGTH_SHARE})) for u, k, h in zip(urns, keys, how)]
    summary = dict(Counter(how), retired=len(retired), lineage=len(lineage), previous_release=prev_release)
    return urns, reg_rows, lineage, retired, summary


def write_registry(conn, reg_rows, lineage, retired, release):
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _reg (LIKE gkg.urn_registry) ON COMMIT DROP")
    conn.execute("TRUNCATE _reg")
    copy_rows(conn, "_reg", ["urn", "kind", "gers_id", "piece_key", "release_first", "release_last",
                             "retired_release", "how_assigned", "tolerance"], reg_rows)
    conn.execute("""INSERT INTO gkg.urn_registry SELECT DISTINCT ON (urn) * FROM _reg
                    ON CONFLICT (urn) DO UPDATE SET release_last = EXCLUDED.release_last, retired_release = NULL""")
    if retired:
        conn.execute("UPDATE gkg.urn_registry SET retired_release = %s WHERE urn = ANY(%s)", (release, retired))
    for o, n, r in lineage:
        conn.execute("INSERT INTO gkg.urn_lineage VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (o, n, r, release))


def extract(geofence_id, extent):
    """Download the segments and connectors in the extent once, as local Parquet pinned to the release."""
    out = config.DATA_ROOT / "overture" / config.OVERTURE_RELEASE / geofence_id
    out.mkdir(parents=True, exist_ok=True)
    seg_path, con_path = out / "segment.parquet", out / "connector.parquet"
    if seg_path.exists() and con_path.exists():
        return seg_path, con_path
    xmin, ymin, xmax, ymax = extent.bounds
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    # Keep DuckDB small: the Mac mini also runs PostgreSQL and OSRM, and its disk is nearly full.
    tmp = out / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con.execute(f"SET memory_limit='3GB'; SET threads=4; SET preserve_insertion_order=false; "
                f"SET temp_directory='{tmp}'")
    wkt = extent.wkt
    bbox = f"bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin}"
    con.execute(f"""COPY (
        SELECT id, subtype, class, subclass, names."primary" AS name, connectors, road_surface,
               speed_limits, access_restrictions, sources, ST_AsWKB(geometry) AS wkb
        FROM read_parquet('{config.OVERTURE_BASE}/type=segment/*', hive_partitioning=1)
        WHERE {bbox} AND subtype = 'road'
    ) TO '{seg_path}.part' (FORMAT parquet)""")
    con.execute(f"""COPY (
        SELECT id, ST_AsWKB(geometry) AS wkb
        FROM read_parquet('{config.OVERTURE_BASE}/type=connector/*', hive_partitioning=1)
        WHERE {bbox}
    ) TO '{con_path}.part' (FORMAT parquet)""")
    (out / "segment.parquet.part").rename(seg_path)
    (out / "connector.parquet.part").rename(con_path)
    return seg_path, con_path


def _first_value(rules):
    for r in rules or []:
        if r.get("value") is not None:
            return r["value"]
    return None


def _speed(limits):
    """The first unconditional maximum speed, as (value, unit)."""
    for s in limits or []:
        if s.get("when") is None and s.get("max_speed"):
            return s["max_speed"]["value"], s["max_speed"]["unit"]
    return None, None


def _osm_refs(sources):
    refs = []
    for s in sources or []:
        rid = s.get("record_id") or ""
        if s.get("dataset") == "OpenStreetMap" and rid.startswith("w"):
            way, _, ver = rid[1:].partition("@")
            if way.isdigit():
                b = s.get("between") or [0.0, 1.0]
                refs.append((int(way), int(ver) if ver.isdigit() else None, b[0], b[1]))
    return refs


def _pieces(line, connectors, split_at, conn_geom):
    """Split a segment at the interior connectors that belong to split_at.

    Returns (from_connector, to_connector, from_frac, to_frac, geometry) with fractions on the parent.
    Positions come from projecting the connector point onto the line; Overture's "at" is the fallback.
    """
    cs = []
    for c in connectors or []:
        cid = c["connector_id"]
        p = conn_geom.get(cid)
        frac = line.project(p, normalized=True) if p is not None else c["at"]
        cs.append((frac, cid))
    cs.sort()
    if not cs:
        return []
    stops = [cs[0]] + [c for c in cs[1:-1] if c[1] in split_at] + [cs[-1]]
    out = []
    for (fa, ca), (fb, cb) in zip(stops, stops[1:]):
        if fb - fa <= 1e-9:
            continue
        g = substring(line, fa, fb, normalized=True)
        if g.geom_type == "LineString" and g.length > 0:
            out.append((ca, cb, fa, fb, g))
    return out


def _hex(g):
    return shapely.to_wkb(shapely.set_srid(g, 4326), hex=True, include_srid=True)


def run(geofence_id):
    core, extent, rec = fetch(geofence_id)
    seg_path, con_path = extract(geofence_id, extent)
    print("overture extract ready", flush=True)
    con = duckdb.connect()
    res = con.execute(f"SELECT * FROM read_parquet('{seg_path}')")
    cols = [d[0] for d in res.description]
    segs = [dict(zip(cols, row)) for row in res.fetchall()]
    conn_rows = con.execute(f"SELECT id, wkb FROM read_parquet('{con_path}')").fetchall()
    conn_geom = {cid: shapely.from_wkb(bytes(w)) for cid, w in conn_rows}

    shapely.prepare(extent)
    for s in segs:
        s["geom"] = shapely.from_wkb(bytes(s["wkb"]))
    segs = [s for s in segs if extent.intersects(s["geom"])]
    for s in segs:
        s["layer"] = "pedestrian" if s["class"] in config.PEDESTRIAN_CLASSES else "vehicular"
        s["connectors"] = list(s["connectors"]) if s["connectors"] is not None else []

    # A connector is a split point when more than one segment uses it, or when a segment passes
    # through it and another ends there. Connectors used by a single segment are shape points.
    use = Counter()
    for s in segs:
        for c in s["connectors"]:
            use[c["connector_id"]] += 1
    split_at = {c for c, n in use.items() if n > 1}

    print(f"{len(segs)} source segments, {len(conn_geom)} connectors", flush=True)
    pieces = {"vehicular": [], "pedestrian": []}
    dropped = 0
    for s in segs:
        for ca, cb, fa, fb, g in _pieces(s["geom"], s["connectors"], split_at, conn_geom):
            # A source segment that crosses the extent's edge yields pieces outside it; drop those.
            if not extent.intersects(g):
                dropped += 1
                continue
            pieces[s["layer"]].append((s, ca, cb, fa, fb, g))
            # Connectors beyond the extent's bounding box were not extracted; use the piece's end point.
            conn_geom.setdefault(ca, Point(g.coords[0]))
            conn_geom.setdefault(cb, Point(g.coords[-1]))

    with connect() as conn:
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions) "
            "VALUES (%s, 'stage1', %s, %s) RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION,
             json.dumps({"overture": config.OVERTURE_RELEASE, "geofence": rec["source_versions"]}))).fetchone()[0]
        piece_urns, urn_stats = {}, {}
        for layer, kind in [("vehicular", "RoadSegment"), ("pedestrian", "PedestrianNetworkEdge")]:
            urns, reg_rows, lineage, retired, summ = assign_urns(conn, geofence_id, layer, kind, pieces[layer])
            piece_urns[layer] = urns
            urn_stats[layer] = summ
            write_registry(conn, reg_rows, lineage, retired, config.OVERTURE_RELEASE)
        print(f"URN assignment: {json.dumps(urn_stats)}", flush=True)
        for t in ["road_segment", "intersection_node", "pedestrian_edge", "pedestrian_node", "access_point"]:
            conn.execute(f"DELETE FROM gkg.{t} WHERE geofence_id = %s", (geofence_id,))
        # The rail layer (stage1_rail) keeps its own crosswalk rows.
        conn.execute("DELETE FROM gkg.osm_crosswalk WHERE geofence_id = %s AND layer IN ('vehicular', 'pedestrian')",
                     (geofence_id,))

        node_urn = {"vehicular": {}, "pedestrian": {}}
        node_kind = {"vehicular": "IntersectionNode", "pedestrian": "PedestrianNetworkNode"}
        stats = {}
        for layer in ["vehicular", "pedestrian"]:
            degree = Counter()
            for _, ca, cb, *_ in pieces[layer]:
                degree[ca] += 1
                degree[cb] += 1
            for c in degree:
                node_urn[layer][c] = mint(node_kind[layer], c)
            edge_rows, xw_rows = [], []
            kind = "RoadSegment" if layer == "vehicular" else "PedestrianNetworkEdge"
            for (s, ca, cb, fa, fb, g), urn in zip(pieces[layer], piece_urns[layer]):
                length = GEOD.geometry_length(g)
                in_core = bool(core.intersects(g))
                surface = _first_value(s["road_surface"])
                if layer == "vehicular":
                    spd, unit = _speed(s["speed_limits"])
                    acc = s["access_restrictions"]
                    edge_rows.append((geofence_id, urn, s["id"], fa, fb, node_urn[layer][ca], node_urn[layer][cb],
                                      s["class"], s["subclass"], spd, unit, surface, s["name"], length, in_core,
                                      json.dumps(list(acc), default=str) if acc is not None else None, _hex(g),
                                      build_id))
                else:
                    edge_rows.append((geofence_id, urn, s["id"], fa, fb, node_urn[layer][ca], node_urn[layer][cb],
                                      s["class"], s["subclass"], surface, length, in_core, _hex(g), build_id))
                # Crosswalk: map each OSM way's range on the parent segment to the piece's own 0-1 range.
                for way, ver, a, b in _osm_refs(s["sources"]):
                    lo, hi = max(a, fa), min(b, fb)
                    if hi > lo:
                        xw_rows.append((geofence_id, layer, urn, way, ver, (lo - fa) / (fb - fa),
                                        (hi - fa) / (fb - fa), build_id))
            if layer == "vehicular":
                copy_rows(conn, "gkg.road_segment",
                          ["geofence_id", "urn", "gers_id", "gers_from_frac", "gers_to_frac", "from_node", "to_node",
                           "road_classification", "subclass", "speed_limit_value", "speed_limit_unit", "surface_type",
                           "name", "length_m", "in_core", "access_restrictions", "geom", "build_id"], edge_rows)
                node_rows = [(geofence_id, node_urn[layer][c], c, d,
                              "intersection" if d >= 3 else "dead_end" if d == 1 else "through",
                              bool(core.intersects(conn_geom[c])), _hex(conn_geom[c]), build_id)
                             for c, d in degree.items() if c in conn_geom]
                copy_rows(conn, "gkg.intersection_node",
                          ["geofence_id", "urn", "connector_id", "degree", "node_kind", "in_core", "geom", "build_id"],
                          node_rows)
            else:
                copy_rows(conn, "gkg.pedestrian_edge",
                          ["geofence_id", "urn", "gers_id", "gers_from_frac", "gers_to_frac", "from_node", "to_node",
                           "edge_class", "subclass", "surface_type", "length_m", "in_core", "geom", "build_id"],
                          edge_rows)
                node_rows = [(geofence_id, node_urn[layer][c], c, d, bool(core.intersects(conn_geom[c])),
                              _hex(conn_geom[c]), build_id) for c, d in degree.items() if c in conn_geom]
                copy_rows(conn, "gkg.pedestrian_node",
                          ["geofence_id", "urn", "connector_id", "degree", "in_core", "geom", "build_id"], node_rows)
            copy_rows(conn, "gkg.osm_crosswalk",
                      ["geofence_id", "layer", "segment_urn", "osm_way_id", "osm_version", "seg_from_frac",
                       "seg_to_frac", "build_id"], xw_rows)
            stats[layer] = {"source_segments": sum(1 for s in segs if s["layer"] == layer),
                            "edges": len(edge_rows), "nodes": len(node_rows),
                            "missing_connector_geometry": sum(1 for c in degree if c not in conn_geom)}

        shared = set(node_urn["vehicular"]) & set(node_urn["pedestrian"])
        ap_rows = [(geofence_id, mint("AccessPoint", c), node_urn["vehicular"][c], node_urn["pedestrian"][c],
                    _hex(conn_geom[c]), build_id) for c in shared if c in conn_geom]
        copy_rows(conn, "gkg.access_point",
                  ["geofence_id", "urn", "intersection_node", "pedestrian_node", "geom", "build_id"], ap_rows)
        stats["access_points"] = len(ap_rows)
        stats["pieces_outside_extent_dropped"] = dropped
        stats["urn_assignment"] = urn_stats
        conn.execute("UPDATE gkg.build SET stats = %s WHERE build_id = %s", (json.dumps(stats), build_id))
        conn.commit()
    return build_id, stats
