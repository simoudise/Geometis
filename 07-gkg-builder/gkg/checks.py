"""Stage 8 integrity checks that apply to Stage 1 output. Each check returns aggregates only."""
import json
from collections import defaultdict

from .db import connect

CHECKS = {
    "segments_without_nodes": """
        SELECT count(*) FROM gkg.road_segment s
        WHERE s.geofence_id = %(g)s AND NOT EXISTS (
            SELECT 1 FROM gkg.intersection_node n WHERE n.geofence_id = s.geofence_id AND n.urn = s.from_node)
           OR s.geofence_id = %(g)s AND NOT EXISTS (
            SELECT 1 FROM gkg.intersection_node n WHERE n.geofence_id = s.geofence_id AND n.urn = s.to_node)""",
    "nonpositive_length": "SELECT count(*) FROM gkg.road_segment WHERE geofence_id = %(g)s AND length_m <= 0",
    "invalid_geometry": "SELECT count(*) FROM gkg.road_segment WHERE geofence_id = %(g)s AND NOT ST_IsValid(geom)",
    "self_loops": "SELECT count(*) FROM gkg.road_segment WHERE geofence_id = %(g)s AND from_node = to_node",
    "segments_outside_extent": """
        SELECT count(*) FROM gkg.road_segment s JOIN gkg.geofence f ON f.geofence_id = s.geofence_id
        WHERE s.geofence_id = %(g)s AND NOT ST_Intersects(s.geom, f.extent)""",
}


def _components(edges):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _ in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    size = defaultdict(float)
    for a, _, length in edges:
        size[find(a)] += length
    return size


def run(geofence_id):
    out = {}
    with connect() as conn:
        for name, sql in CHECKS.items():
            out[name] = conn.execute(sql, {"g": geofence_id}).fetchone()[0]
        n, km, core_km = conn.execute(
            "SELECT count(*), sum(length_m)/1000, sum(length_m) FILTER (WHERE in_core)/1000 "
            "FROM gkg.road_segment WHERE geofence_id = %s", (geofence_id,)).fetchone()
        out["segments"], out["km"], out["km_in_core"] = n, round(km or 0, 1), round(core_km or 0, 1)
        xw = conn.execute("""
            SELECT coalesce(sum(s.length_m * c.cov), 0) / nullif(sum(s.length_m), 0) FROM gkg.road_segment s
            LEFT JOIN (SELECT segment_urn, least(1, sum(seg_to_frac - seg_from_frac)) AS cov
                       FROM gkg.osm_crosswalk WHERE geofence_id = %s AND layer = 'vehicular' GROUP BY 1) c
              ON c.segment_urn = s.urn
            WHERE s.geofence_id = %s""", (geofence_id, geofence_id)).fetchone()[0]
        out["share_of_length_with_osm_crosswalk"] = round(float(xw or 0), 4)
        kinds = conn.execute("SELECT node_kind, count(*) FROM gkg.intersection_node WHERE geofence_id = %s "
                             "GROUP BY 1", (geofence_id,)).fetchall()
        out["nodes_by_kind"] = dict(kinds)
        out["classes_km"] = {c: round(k, 1) for c, k in conn.execute(
            "SELECT coalesce(road_classification,'null'), sum(length_m)/1000 FROM gkg.road_segment "
            "WHERE geofence_id = %s GROUP BY 1 ORDER BY 2 DESC", (geofence_id,)).fetchall()}
        out["share_with_speed_limit"] = round(float(conn.execute(
            "SELECT avg((speed_limit_value IS NOT NULL)::int) FROM gkg.road_segment WHERE geofence_id = %s",
            (geofence_id,)).fetchone()[0] or 0), 4)
        edges = conn.execute("SELECT from_node, to_node, length_m FROM gkg.road_segment WHERE geofence_id = %s",
                             (geofence_id,)).fetchall()
        comp = _components(edges)
        total = sum(comp.values()) or 1
        out["components"] = len(comp)
        out["largest_component_length_share"] = round(max(comp.values(), default=0) / total, 4)
        for t in ["pedestrian_edge", "pedestrian_node", "access_point"]:
            out[t] = conn.execute(f"SELECT count(*) FROM gkg.{t} WHERE geofence_id = %s", (geofence_id,)).fetchone()[0]
        hard = ["segments_without_nodes", "nonpositive_length", "invalid_geometry", "segments_outside_extent"]
        out["passed"] = all(out[h] == 0 for h in hard) and out["largest_component_length_share"] >= 0.95
        conn.execute("UPDATE gkg.build SET finished = now(), status = %s, stats = coalesce(stats, '{}'::jsonb) || "
                     "jsonb_build_object('stage8', %s::jsonb) WHERE build_id = (SELECT max(build_id) FROM gkg.build "
                     "WHERE geofence_id = %s AND stage = 'stage1')",
                     ("passed" if out["passed"] else "failed", json.dumps(out), geofence_id))
        conn.commit()
    return out
