"""Stage 1 rail layer. Usage: ~/geometis-venv/bin/python -u run_stage1_rail.py us-ca-contra-costa-5"""
import json
import sys

from gkg import stage1_rail

build_id, out = stage1_rail.run(sys.argv[1])
print("stage1-rail build", build_id)
print(json.dumps(out, indent=1))
