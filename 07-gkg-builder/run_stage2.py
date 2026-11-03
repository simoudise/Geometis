"""Run Stage 2 (Census tracts and ACS) for a stored geofence, then its checks.

Usage: ~/geometis-venv/bin/python -u run_stage2.py us-ca-contra-costa-5
"""
import json
import sys
import time
from pathlib import Path

from gkg import stage2_demographics
from gkg.db import apply_schema, connect

gid = sys.argv[1]
t0 = time.time()
with connect() as conn:
    apply_schema(conn, Path(__file__).parent / "sql" / "schema.sql")
build_id, stats = stage2_demographics.run(gid)
print("stage2 build", build_id, json.dumps(stats), f"{time.time() - t0:.0f} s", flush=True)

with connect() as conn:
    q = lambda sql: conn.execute(sql, (gid,)).fetchone()
    chk = {
        "tracts": q("SELECT count(*) FROM gkg.census_tract WHERE geofence_id = %s")[0],
        "core_area_covered_share": round(float(q("""
            SELECT ST_Area(ST_Transform(ST_Intersection(f.core, u.g), 5070)) / ST_Area(ST_Transform(f.core, 5070))
            FROM gkg.geofence f JOIN (SELECT geofence_id, ST_Union(geom) AS g FROM gkg.census_tract GROUP BY 1) u
              USING (geofence_id) WHERE geofence_id = %s""")[0]), 5),
        "population_weighted_by_share": round(float(q(
            "SELECT sum(population * share_in_core) FROM gkg.census_tract WHERE geofence_id = %s")[0] or 0)),
        "tracts_null_population": q("SELECT count(*) FROM gkg.census_tract WHERE geofence_id = %s AND population IS NULL")[0],
        "tracts_null_income": q("SELECT count(*) FROM gkg.census_tract WHERE geofence_id = %s AND median_household_income IS NULL")[0],
        "segments_in_a_tract": q("SELECT count(*) FROM gkg.segment_within_tract WHERE geofence_id = %s")[0],
        "segments_in_core": q("SELECT count(*) FROM gkg.road_segment WHERE geofence_id = %s AND in_core")[0],
    }
    chk["passed"] = chk["core_area_covered_share"] >= 0.999 and chk["tracts_null_population"] == 0
    conn.execute("UPDATE gkg.build SET finished = now(), status = %s, stats = stats || jsonb_build_object('stage8', %s::jsonb) "
                 "WHERE build_id = %s", ("passed" if chk["passed"] else "failed", json.dumps(chk), build_id))
    conn.commit()
print("stage8", json.dumps(chk), flush=True)
