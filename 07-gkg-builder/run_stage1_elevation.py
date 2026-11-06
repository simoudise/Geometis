"""Elevation and grade for a stored geofence. Usage: ~/geometis-venv/bin/python -u run_stage1_elevation.py <geofence_id>"""
import json
import sys
import time

from gkg import stage1_elevation

t0 = time.time()
print("stage1-elevation", json.dumps(stage1_elevation.run(sys.argv[1])), f"{time.time() - t0:.0f} s")
