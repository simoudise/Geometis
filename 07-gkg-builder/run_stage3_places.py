"""Run the places part of Stage 3 for a stored geofence.

Usage: ~/geometis-venv/bin/python -u run_stage3_places.py us-ca-contra-costa-5
"""
import json
import sys
import time
from pathlib import Path

from gkg import stage3_places
from gkg.db import apply_schema, connect

gid = sys.argv[1]
t0 = time.time()
with connect() as conn:
    apply_schema(conn, Path(__file__).parent / "sql" / "schema.sql")
build_id, stats = stage3_places.run(gid)
print("stage3-places build", build_id, json.dumps(stats), f"{time.time() - t0:.0f} s", flush=True)
