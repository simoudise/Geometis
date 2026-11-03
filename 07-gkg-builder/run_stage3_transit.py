"""Run the transit part of Stage 3 for a stored geofence.

Usage (MOBILITY_DB_TOKEN must be set):
    . ~/.geometis-env; ~/geometis-venv/bin/python -u run_stage3_transit.py us-ca-contra-costa-5
"""
import json
import sys
import time
from pathlib import Path

from gkg import stage3_transit
from gkg.db import apply_schema, connect

gid = sys.argv[1]
t0 = time.time()
with connect() as conn:
    apply_schema(conn, Path(__file__).parent / "sql" / "schema.sql")
build_id, stats, feeds = stage3_transit.run(gid, sys.argv[2] if len(sys.argv) > 2 else None)
print("stage3-transit build", build_id, json.dumps(stats, default=str), f"{time.time() - t0:.0f} s", flush=True)
for f in feeds:
    print(json.dumps(f, default=str))
