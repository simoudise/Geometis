"""Stage 3 building footprints. Usage: ~/geometis-venv/bin/python -u run_stage3_buildings.py us-ca-contra-costa-5"""
import json
import sys

from gkg import stage3_buildings

build_id, out = stage3_buildings.run(sys.argv[1])
print("stage3-buildings build", build_id)
print(json.dumps(out, indent=1))
