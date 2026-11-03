"""Build a geofence record and run Stage 1 plus its Stage 8 checks.

Usage (on the Mac mini, through the job runner):
    ~/geometis-venv/bin/python run_stage1.py geofences/us-ca-contra-costa-5.json
"""
import argparse
import json
import time
from pathlib import Path

from gkg import checks, geofence, stage1_road_network
from gkg.db import apply_schema, connect

ap = argparse.ArgumentParser()
ap.add_argument("definition")
ap.add_argument("--skip-buffer-test", action="store_true")
ap.add_argument("--max-pairs", type=int, default=None)
args = ap.parse_args()

t0 = time.time()
with connect() as conn:
    apply_schema(conn, Path(__file__).parent / "sql" / "schema.sql")
rec, singles = geofence.build_record(args.definition, run_buffer_test=not args.skip_buffer_test,
                                     max_pairs=args.max_pairs)
geofence.store([rec] + singles)
t1 = time.time()
print("geofence", rec["geofence_id"], "buffer_m", rec["buffer_m"], json.dumps(rec["buffer_test"]))
print(f"geofence records stored: {1 + len(singles)} in {t1 - t0:.0f} s")
build_id, stats = stage1_road_network.run(rec["geofence_id"])
t2 = time.time()
print("stage1 build", build_id, json.dumps(stats), f"{t2 - t1:.0f} s")
res = checks.run(rec["geofence_id"])
print("stage8", json.dumps(res), f"{time.time() - t2:.0f} s")
