"""Stage 4 crashes from TIMS.

Usage: ~/geometis-venv/bin/python -u run_stage4_crashes.py <tims folder> <download date YYYY-MM-DD> <geofence> [...]
"""
import json
import sys

from gkg import stage4_crashes

folder, day, geofences = sys.argv[1], sys.argv[2], sys.argv[3:]
print("load", json.dumps(stage4_crashes.load_tims(folder, day)))
for g in geofences:
    build_id, out = stage4_crashes.run(g)
    print("stage4-crashes", g, "build", build_id)
    print(json.dumps(out, indent=1))
