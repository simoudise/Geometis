"""Test 2 export: Tier P node features, graph edges, crash labels and city cores for SPECTRA v0.

python export.py OUTDIR
Runs on the Mac mini. Writes per geofence: one parquet file per node type, edges.parquet, labels.parquet,
cores.parquet, and manifest.json (the M7d lineage manifest). Outputs stay on the Mac mini.

Rules (docs/test-plan-2026-11.md, Test 2, "Leakage controls"):
- Feature files hold Tier P properties only. Every feature column is listed in FEATURES with its source and tier;
  the export fails if a feature column is missing from FEATURES or traces to a tier other than P.
- Nothing derived from crashes enters a feature file. segment_crash_stats is never read.
- Labels come from gkg.tims_crash joined to gkg.crash_attachment: 2015-2019 (for L_aux) and 2021-2025 (target).
  Segment counts leave out crashes matched to an intersection.
- No names or URNs are features; URNs are kept only as row keys.
- Raw values are exported without fitted transforms or imputation: anything fitted (class-median speed limits,
  feature means, scalers) is computed per fold on source entities only.
"""
import json, os, sys, hashlib
import pandas as pd
import psycopg

GEOFENCES = ["us-ca-contra-costa-5", "us-ca-san-francisco"]
CORES = ["Antioch", "Concord", "Pittsburg", "Pleasant Hill", "Walnut Creek", "San Francisco city"]

# column -> (source, tier). Keys are ids or coordinates, not features: listed in KEYS.
FEATURES = {
    "segment": {
        "length_m": ("road_segment.length_m (Overture geometry)", "P"),
        "road_classification": ("road_segment.road_classification (Overture)", "P"),
        "is_link": ("road_segment.subclass = 'link' (Overture)", "P"),
        "speed_limit_mph": ("road_segment.speed_limit_mph where source is posted or statutory (OSM tag or state rule)", "P"),
        "speed_limit_source": ("road_segment.speed_limit_source, class_median reset to null (fitted per fold)", "P"),
        "grade": ("road_segment.grade (USGS elevation)", "P"),
        "max_abs_grade": ("road_segment.max_abs_grade (USGS elevation)", "P"),
        "is_bridge": ("road_segment.is_bridge (Overture)", "P"),
        "is_tunnel": ("road_segment.is_tunnel (Overture)", "P"),
        "sinuosity": ("length over end-to-end distance, from geometry", "P"),
        "bearing_deg": ("end-to-end bearing modulo 180, from geometry", "P"),
    },
    "node": {
        "degree": ("intersection_node.degree (Overture connectors)", "P"),
        "node_kind": ("intersection_node.node_kind", "P"),
        "elevation_m": ("intersection_node.elevation_m (USGS elevation)", "P"),
    },
    "place": {
        "uko_class": ("place.uko_class (Overture category crosswalk)", "P"),
        "basic_category": ("place.basic_category (Overture)", "P"),
        "has_brand": ("place.brand is not null (Overture)", "P"),
        "confidence": ("place.confidence (Overture)", "P"),
    },
    "ped_edge": {
        "length_m": ("pedestrian_edge.length_m", "P"),
        "edge_class": ("pedestrian_edge.edge_class (Overture/OSM)", "P"),
        "subclass": ("pedestrian_edge.subclass (Overture/OSM)", "P"),
    },
    "ped_node": {
        "degree": ("pedestrian_node.degree", "P"),
    },
    "stop": {
        "uko_class": ("transit_stop.uko_class (GTFS)", "P"),
        "location_type": ("transit_stop.location_type (GTFS)", "P"),
        "departures": ("transit_stop.departures_on_service_day (GTFS)", "P"),
        "route_count": ("cardinality(transit_stop.route_urns) (GTFS)", "P"),
    },
    "tract": {
        "population": ("census_tract.population (ACS 2020-2024)", "P"),
        "households": ("census_tract.households (ACS)", "P"),
        "zero_vehicle_share": ("census_tract.zero_vehicle_share (ACS)", "P"),
        "median_household_income": ("census_tract.median_household_income (ACS)", "P"),
        "share_below_35k": ("households_below_35k / households (ACS)", "P"),
        "share_100k_plus": ("households_100k_plus / households (ACS)", "P"),
        "area_km2": ("land area from geometry", "P"),
    },
}
KEYS = {"urn", "x", "y", "geofence_id"}

def q(conn, sql, args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)

XY = "ST_X(ST_Transform(ST_Centroid(geom),3310)) x, ST_Y(ST_Transform(ST_Centroid(geom),3310)) y"

def nodes(conn, gf):
    a = {"g": gf}
    out = {}
    out["segment"] = q(conn, f"""select urn, {XY}, length_m, road_classification, coalesce(subclass,'')='link' is_link,
        case when speed_limit_source in ('posted','statutory') then speed_limit_mph end speed_limit_mph,
        case when speed_limit_source in ('posted','statutory') then speed_limit_source end speed_limit_source,
        grade, max_abs_grade, coalesce(is_bridge,false) is_bridge, coalesce(is_tunnel,false) is_tunnel,
        length_m / greatest(ST_Distance(ST_Transform(ST_StartPoint(geom),3310), ST_Transform(ST_EndPoint(geom),3310)), 1) sinuosity,
        mod(degrees(ST_Azimuth(ST_Transform(ST_StartPoint(geom),3310), ST_Transform(ST_EndPoint(geom),3310)))::numeric, 180)::float bearing_deg
        from gkg.road_segment where geofence_id=%(g)s""", a)
    out["node"] = q(conn, f"select urn, {XY}, degree, node_kind, elevation_m from gkg.intersection_node where geofence_id=%(g)s", a)
    out["place"] = q(conn, f"""select urn, {XY}, uko_class, basic_category, brand is not null has_brand, confidence
        from gkg.place where geofence_id=%(g)s""", a)
    out["ped_edge"] = q(conn, f"select urn, {XY}, length_m, edge_class, subclass from gkg.pedestrian_edge where geofence_id=%(g)s", a)
    out["ped_node"] = q(conn, f"select urn, {XY}, degree from gkg.pedestrian_node where geofence_id=%(g)s", a)
    out["stop"] = q(conn, f"""select urn, {XY}, uko_class, location_type, departures_on_service_day departures,
        coalesce(cardinality(route_urns),0) route_count from gkg.transit_stop where geofence_id=%(g)s""", a)
    out["tract"] = q(conn, f"""select geoid urn, {XY}, population, households, zero_vehicle_share, median_household_income,
        households_below_35k::float / nullif(households,0) share_below_35k, households_100k_plus::float / nullif(households,0) share_100k_plus,
        ST_Area(ST_Transform(geom,3310)) / 1e6 area_km2 from gkg.census_tract where geofence_id=%(g)s""", a)
    return out

def edges(conn, gf):
    a = {"g": gf}
    parts = [
        q(conn, "select urn src, from_node dst, 'segment_node' rel from gkg.road_segment where geofence_id=%(g)s and from_node is not null "
                "union all select urn, to_node, 'segment_node' from gkg.road_segment where geofence_id=%(g)s and to_node is not null", a),
        q(conn, "select urn src, from_node dst, 'pededge_pednode' rel from gkg.pedestrian_edge where geofence_id=%(g)s "
                "union all select urn, to_node, 'pededge_pednode' from gkg.pedestrian_edge where geofence_id=%(g)s", a),
        q(conn, "select intersection_node src, pedestrian_node dst, 'node_pednode' rel from gkg.access_point where geofence_id=%(g)s", a),
        q(conn, "select stop_urn src, segment_urn dst, 'stop_segment' rel from gkg.stop_road where geofence_id=%(g)s", a),
        # Each place to its nearest road segment within 100 m (geometry only).
        q(conn, """select p.urn src, s.urn dst, 'place_segment' rel from gkg.place p cross join lateral (
                   select urn from gkg.road_segment r where r.geofence_id=p.geofence_id and ST_DWithin(r.geom, p.geom, 0.0012)
                   order by r.geom <-> p.geom limit 1) s where p.geofence_id=%(g)s""", a),
        # Segments, places and stops to the tract containing their centroid.
        q(conn, """select s.urn src, t.geoid dst, 'segment_tract' rel from gkg.road_segment s join gkg.census_tract t
                   on t.geofence_id=s.geofence_id and ST_Contains(t.geom, ST_Centroid(s.geom)) where s.geofence_id=%(g)s""", a),
        q(conn, """select p.urn src, t.geoid dst, 'place_tract' rel from gkg.place p join gkg.census_tract t
                   on t.geofence_id=p.geofence_id and ST_Contains(t.geom, p.geom) where p.geofence_id=%(g)s""", a),
        q(conn, """select p.urn src, t.geoid dst, 'stop_tract' rel from gkg.transit_stop p join gkg.census_tract t
                   on t.geofence_id=p.geofence_id and ST_Contains(t.geom, p.geom) where p.geofence_id=%(g)s""", a),
    ]
    return pd.concat(parts, ignore_index=True)

def labels(conn, gf):
    """Injury-crash counts (Tier R): never written into a feature file."""
    a = {"g": gf}
    return q(conn, """
        with c as (select a.segment_urn, a.node_urn, t.accident_year y from gkg.crash_attachment a
                   join gkg.tims_crash t on t.case_id = a.case_id where a.geofence_id=%(g)s and t.accident_year between 2015 and 2025)
        select segment_urn urn, 'segment' entity,
               count(*) filter (where y between 2015 and 2019) crashes_2015_2019,
               count(*) filter (where y between 2021 and 2025) crashes_2021_2025
          from c where node_urn is null and segment_urn is not null group by 1
        union all
        select node_urn, 'intersection',
               count(*) filter (where y between 2015 and 2019), count(*) filter (where y between 2021 and 2025)
          from c where node_urn is not null group by 1""", a)

def cores(conn):
    return q(conn, "select name, ST_AsBinary(ST_Transform(core,3310)) wkb from gkg.geofence where name = any(%(c)s)", {"c": CORES})

def check_lineage(kind, df):
    for col in df.columns:
        if col in KEYS: continue
        if col not in FEATURES[kind]:
            raise SystemExit(f"lineage: {kind}.{col} is not listed in FEATURES")
        if FEATURES[kind][col][1] != "P":
            raise SystemExit(f"lineage: {kind}.{col} traces to tier {FEATURES[kind][col][1]}")
    if any("crash" in c or "ksi" in c for c in df.columns):
        raise SystemExit(f"lineage: crash-derived column in {kind}")

def sha(path):
    h = hashlib.sha256(); h.update(open(path, "rb").read()); return h.hexdigest()

def main():
    out = sys.argv[1]
    conn = psycopg.connect("dbname=geometis", options="-c statement_timeout=1800000 -c default_transaction_read_only=on")
    manifest = {"features": {k: {c: {"source": s, "tier": t} for c, (s, t) in v.items()} for k, v in FEATURES.items()},
                "labels": {"source": "gkg.tims_crash + gkg.crash_attachment", "tier": "R",
                           "windows": {"aux": "2015-2019", "target": "2021-2025"}},
                "files": {}}
    for gf in GEOFENCES:
        d = os.path.join(out, gf); os.makedirs(d, exist_ok=True)
        for kind, df in nodes(conn, gf).items():
            check_lineage(kind, df)
            p = os.path.join(d, f"{kind}.parquet"); df.to_parquet(p, index=False)
            manifest["files"][p] = {"rows": len(df), "sha256": sha(p), "tier": "P"}
            print(gf, kind, len(df), flush=True)
        e = edges(conn, gf); p = os.path.join(d, "edges.parquet"); e.to_parquet(p, index=False)
        manifest["files"][p] = {"rows": len(e), "sha256": sha(p), "tier": "P"}
        print(gf, "edges", e.groupby("rel").size().to_dict(), flush=True)
        lab = labels(conn, gf); p = os.path.join(d, "labels.parquet"); lab.to_parquet(p, index=False)
        manifest["files"][p] = {"rows": len(lab), "sha256": sha(p), "tier": "R"}
        print(gf, "labels", lab.groupby("entity")[["crashes_2015_2019", "crashes_2021_2025"]].sum().to_dict(), flush=True)
    c = cores(conn); p = os.path.join(out, "cores.parquet"); c.to_parquet(p, index=False)
    manifest["files"][p] = {"rows": len(c), "sha256": sha(p), "tier": "P"}
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    print("manifest written", flush=True)

if __name__ == "__main__":
    main()
