"""Stage 4, collision analytics: injury crashes from TIMS (UC Berkeley SafeTREC's geocoded SWITRS), attached
to the road network, and counts per segment and per intersection.

Source. TIMS SWITRS exports (Crashes, Parties, Victims as CSV), one folder per county, placed by Evangelos in
the shared folder tims-incoming. TIMS carries injury crashes only (severity 1 fatal, 2 severe injury, 3 visible
injury, 4 complaint of pain); property-damage-only crashes are not in it. TIMS may revise coordinates at any
time, so every load records the download date given on the command line.

Attachment rule (per crash with a TIMS point):
  1. Intersection crashes (SWITRS INTERSECTION = 'Y') go to the nearest intersection node (degree 3 or more)
     within INTERSECTION_SNAP_M.
  2. Every crash also gets the nearest vehicular segment within SEGMENT_SNAP_M, excluding service roads, so that
     segment counts can include or exclude intersection crashes.
     Among segments within SEGMENT_SNAP_M the choice prefers, in order: a segment whose name matches the
     officer's primary or secondary road (first word after normalizing spelling and dropping direction prefixes);
     for a state-highway crash on the mainline (SWITRS location type H), a motorway or trunk segment that is not a
     ramp; for a ramp crash (location type R), a ramp (subclass link); then the nearest segment.
  3. Name check: the share of attached crashes whose chosen segment name matches the primary road measures how
     often the attachment lands on the officer's street.
"""
import csv
import json
from pathlib import Path

import psycopg

from . import config
from .db import connect, copy_rows

INTERSECTION_SNAP_M = 50.0
SEGMENT_SNAP_M = 50.0
CRASH_COLS = ["CASE_ID", "ACCIDENT_YEAR", "COLLISION_DATE", "COLLISION_TIME", "JURIS", "CITY", "COUNTY",
              "PRIMARY_RD", "SECONDARY_RD", "DISTANCE", "DIRECTION", "INTERSECTION", "STATE_HWY_IND", "STATE_ROUTE", "LOCATION_TYPE", "RAMP_INTERSECTION",
              "COLLISION_SEVERITY", "NUMBER_KILLED", "NUMBER_INJURED", "COUNT_SEVERE_INJ", "TYPE_OF_COLLISION",
              "PEDESTRIAN_ACCIDENT", "BICYCLE_ACCIDENT", "MOTORCYCLE_ACCIDENT", "TRUCK_ACCIDENT", "LIGHTING",
              "PRIMARY_COLL_FACTOR", "PCF_VIOL_CATEGORY", "POINT_X", "POINT_Y", "LATITUDE", "LONGITUDE"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS gkg.tims_crash (
    case_id text PRIMARY KEY, accident_year int, collision_date date, collision_time text, juris text, city text,
    county text, primary_rd text, secondary_rd text, distance_ft double precision, direction text,
    intersection boolean, state_hwy boolean, state_route text, location_type text, ramp_intersection text, severity int, killed int, injured int,
    severe_injured int, collision_type text, pedestrian boolean, bicycle boolean, motorcycle boolean, truck boolean,
    lighting text, pcf text, pcf_category text, geom geometry(Point, 4326), source_file text, tims_download date);
ALTER TABLE gkg.tims_crash ADD COLUMN IF NOT EXISTS location_type text, ADD COLUMN IF NOT EXISTS ramp_intersection text;
CREATE INDEX IF NOT EXISTS tims_crash_geom ON gkg.tims_crash USING gist (geom);
CREATE TABLE IF NOT EXISTS gkg.crash_attachment (
    geofence_id text NOT NULL, case_id text NOT NULL, segment_urn text, segment_snap_m double precision,
    node_urn text, node_snap_m double precision, name_match boolean, build_id integer NOT NULL,
    PRIMARY KEY (geofence_id, case_id));
"""


def _b(v):
    return {"Y": True, "N": False}.get((v or "").strip().upper())


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        x = float(v)
        return x if x != 0 else None
    except (TypeError, ValueError):
        return None


def load_tims(folder, download_date):
    """Load every Crashes*.csv under folder into gkg.tims_crash (replacing rows with the same CASE_ID)."""
    rows = []
    for f in sorted(Path(folder).glob("*/Crashes*.csv")):
        with open(f, newline="", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                x, y = _f(r["POINT_X"]), _f(r["POINT_Y"])
                d = r["COLLISION_DATE"]
                rows.append((r["CASE_ID"], _i(r["ACCIDENT_YEAR"]), d if d else None, r["COLLISION_TIME"], r["JURIS"],
                             r["CITY"], r["COUNTY"], r["PRIMARY_RD"], r["SECONDARY_RD"], _f(r["DISTANCE"]) or 0.0,
                             r["DIRECTION"], _b(r["INTERSECTION"]), _b(r["STATE_HWY_IND"]), r["STATE_ROUTE"], r["LOCATION_TYPE"], r["RAMP_INTERSECTION"],
                             _i(r["COLLISION_SEVERITY"]), _i(r["NUMBER_KILLED"]), _i(r["NUMBER_INJURED"]),
                             _i(r["COUNT_SEVERE_INJ"]), r["TYPE_OF_COLLISION"], _b(r["PEDESTRIAN_ACCIDENT"]),
                             _b(r["BICYCLE_ACCIDENT"]), _b(r["MOTORCYCLE_ACCIDENT"]), _b(r["TRUCK_ACCIDENT"]),
                             r["LIGHTING"], r["PRIMARY_COLL_FACTOR"], r["PCF_VIOL_CATEGORY"],
                             f"SRID=4326;POINT({x} {y})" if x is not None and y is not None else None,
                             f"{f.parent.name}/{f.name}", download_date))
    with connect() as conn:
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.execute("CREATE TEMP TABLE _c (LIKE gkg.tims_crash) ON COMMIT DROP")
        cols = ["case_id", "accident_year", "collision_date", "collision_time", "juris", "city", "county",
                "primary_rd", "secondary_rd", "distance_ft", "direction", "intersection", "state_hwy", "state_route", "location_type", "ramp_intersection",
                "severity", "killed", "injured", "severe_injured", "collision_type", "pedestrian", "bicycle",
                "motorcycle", "truck", "lighting", "pcf", "pcf_category", "geom", "source_file", "tims_download"]
        n = copy_rows(conn, "_c", cols, rows)
        conn.execute("DELETE FROM gkg.tims_crash WHERE case_id IN (SELECT case_id FROM _c)")
        cl = ", ".join(cols)
        conn.execute(f"INSERT INTO gkg.tims_crash ({cl}) SELECT DISTINCT ON (case_id) {cl} FROM _c ORDER BY case_id, source_file DESC")
        total = conn.execute("SELECT count(*), count(geom) FROM gkg.tims_crash").fetchone()
        conn.commit()
    return {"rows_read": n, "crashes_in_table": total[0], "with_point": total[1]}


def run(geofence_id):
    """Attach crashes inside the geofence extent to segments and intersection nodes; write per-entity counts."""
    p = {"g": geofence_id, "ns": INTERSECTION_SNAP_M, "ss": SEGMENT_SNAP_M}
    sql = [
        # First word of a street name after removing accents, punctuation, travel-direction and compass prefixes:
        # "S/B KIRKER PASS RD" -> KIRKER, "O'Hara Avenue" -> OHARA, "Cañada Valley Road" -> CANADA.
        """CREATE OR REPLACE FUNCTION gkg.road_key(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $f$
             SELECT coalesce(split_part(regexp_replace(regexp_replace(regexp_replace(
               translate(upper(coalesce(t, '')), 'ÁÉÍÓÚÑÜ''.', 'AEIOUNU'),
               '^([NSEW]/B|NB|SB|EB|WB) ', ''), '^(N|S|E|W|NORTH|SOUTH|EAST|WEST) ', ''), '[^A-Z0-9 ]', '', 'g'),
               ' ', 1), '')
           $f$""",
        "DELETE FROM gkg.crash_attachment WHERE geofence_id = %(g)s",
        """CREATE TEMP TABLE _in AS SELECT c.* FROM gkg.tims_crash c JOIN gkg.geofence g ON g.geofence_id = %(g)s
           WHERE c.geom IS NOT NULL AND ST_Intersects(c.geom, g.extent)""",
        """INSERT INTO gkg.crash_attachment (geofence_id, case_id, segment_urn, segment_snap_m, node_urn, node_snap_m,
                                            name_match, build_id)
           SELECT %(g)s, c.case_id, s.urn, s.d, n.urn, n.d,
                  CASE WHEN s.urn IS NULL OR gkg.road_key(c.primary_rd) = '' THEN NULL
                       ELSE gkg.road_key(s.name) = gkg.road_key(c.primary_rd) END,
                  %(b)s
           FROM _in c
           LEFT JOIN LATERAL (SELECT r.urn, r.name, ST_Distance(r.geom::geography, c.geom::geography) d
                              FROM gkg.road_segment r
                              WHERE r.geofence_id = %(g)s AND coalesce(r.road_classification, '') <> 'service'
                                -- Bounding-box prefilter in degrees so the spatial index is used (0.001 deg is
                                -- at least 88 m at these latitudes), then the exact distance in metres.
                                AND r.geom && ST_Expand(c.geom, 0.001)
                                AND ST_DWithin(r.geom::geography, c.geom::geography, %(ss)s)
                              ORDER BY CASE
                                WHEN gkg.road_key(r.name) <> '' AND gkg.road_key(r.name) IN
                                     (gkg.road_key(c.primary_rd), gkg.road_key(c.secondary_rd)) THEN 0
                                WHEN c.state_hwy AND c.location_type = 'H'
                                     AND r.road_classification IN ('motorway', 'trunk')
                                     AND coalesce(r.subclass, '') <> 'link' THEN 0
                                WHEN c.location_type = 'R' AND r.subclass = 'link' THEN 0
                                ELSE 1 END, r.geom <-> c.geom LIMIT 1) s ON true
           LEFT JOIN LATERAL (SELECT i.urn, ST_Distance(i.geom::geography, c.geom::geography) d
                              FROM gkg.intersection_node i
                              WHERE c.intersection AND i.geofence_id = %(g)s AND i.degree >= 3
                                AND i.geom && ST_Expand(c.geom, 0.001) AND ST_DWithin(i.geom::geography, c.geom::geography, %(ns)s)
                              ORDER BY i.geom <-> c.geom LIMIT 1) n ON true""",
        """CREATE TABLE IF NOT EXISTS gkg.segment_crash_stats (
               geofence_id text, urn text, entity text, year_from int, year_to int, crashes int, fatal int,
               severe int, ksi int, pedestrian int, bicycle int, motorcycle int, intersection_crashes int,
               build_id int, PRIMARY KEY (geofence_id, urn, year_from, year_to))""",
        "DELETE FROM gkg.segment_crash_stats WHERE geofence_id = %(g)s",
        # Segment counts exclude crashes attached to an intersection node; node counts take those.
        """INSERT INTO gkg.segment_crash_stats
           SELECT %(g)s, coalesce(a.node_urn, a.segment_urn), CASE WHEN a.node_urn IS NOT NULL THEN 'intersection'
                  ELSE 'segment' END, w.y0, w.y1, count(*), count(*) FILTER (WHERE c.severity = 1),
                  count(*) FILTER (WHERE c.severity = 2), count(*) FILTER (WHERE c.severity <= 2),
                  count(*) FILTER (WHERE c.pedestrian), count(*) FILTER (WHERE c.bicycle),
                  count(*) FILTER (WHERE c.motorcycle), count(*) FILTER (WHERE c.intersection), %(b)s
           FROM gkg.crash_attachment a JOIN _in c USING (case_id)
           CROSS JOIN (VALUES (2019, 2023), (2021, 2025), (2015, 2025)) w(y0, y1)
           WHERE a.geofence_id = %(g)s AND coalesce(a.node_urn, a.segment_urn) IS NOT NULL
             AND c.accident_year BETWEEN w.y0 AND w.y1
           GROUP BY 2, 3, 4, 5""",
    ]
    with connect() as conn:
        b = conn.execute("INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions) "
                         "VALUES (%s, 'stage4-crashes', %s, %s) RETURNING build_id",
                         (geofence_id, config.BUILDER_VERSION,
                          json.dumps({"tims": conn.execute("SELECT max(tims_download)::text FROM gkg.tims_crash")
                                      .fetchone()[0]}))).fetchone()[0]
        p["b"] = b
        # Client-side binding, so that parameters also work inside CREATE TABLE AS.
        cur = psycopg.ClientCursor(conn)
        for s in sql:
            cur.execute(s, p)
        q = lambda s: cur.execute(s, p).fetchall()
        out = {
            "snap_m": {"intersection": INTERSECTION_SNAP_M, "segment": SEGMENT_SNAP_M},
            "crashes_in_extent": q("SELECT count(*) FROM _in")[0][0],
            "by_year": dict(q("SELECT accident_year::text, count(*) FROM _in GROUP BY 1 ORDER BY 1")),
            "attached": dict(zip(["any", "to_intersection", "to_segment_only", "none"], q(
                """SELECT count(*) FILTER (WHERE segment_urn IS NOT NULL OR node_urn IS NOT NULL),
                          count(*) FILTER (WHERE node_urn IS NOT NULL),
                          count(*) FILTER (WHERE node_urn IS NULL AND segment_urn IS NOT NULL),
                          count(*) FILTER (WHERE node_urn IS NULL AND segment_urn IS NULL)
                   FROM gkg.crash_attachment WHERE geofence_id = %(g)s""")[0])),
            "intersection_crashes_without_node": q(
                """SELECT count(*) FROM gkg.crash_attachment a JOIN _in c USING (case_id)
                   WHERE a.geofence_id = %(g)s AND c.intersection AND a.node_urn IS NULL""")[0][0],
            "median_snap_m": {k: round(float(v), 1) if v is not None else None for k, v in zip(["segment", "node"], q(
                """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY segment_snap_m),
                          percentile_cont(0.5) WITHIN GROUP (ORDER BY node_snap_m)
                   FROM gkg.crash_attachment WHERE geofence_id = %(g)s""")[0])},
            "name_match_share": float(q("""SELECT round(avg(name_match::int)::numeric, 3) FROM gkg.crash_attachment
                                           WHERE geofence_id = %(g)s AND name_match IS NOT NULL""")[0][0] or 0),
            "entities_with_crashes_2021_2025": dict(q(
                """SELECT entity, count(*) FROM gkg.segment_crash_stats WHERE geofence_id = %(g)s
                   AND year_from = 2021 AND year_to = 2025 GROUP BY 1""")),
        }
        conn.execute("UPDATE gkg.build SET stats = %s, finished = now(), status = 'loaded' WHERE build_id = %s",
                     (json.dumps(out), b))
        conn.commit()
    return b, out
