"""Stage 5 speed limits. Usage: ~/geometis-venv/bin/python -u run_stage5_speed.py us-ca-contra-costa-5"""
import json
import sys

from gkg import stage5_speed

build_id, out = stage5_speed.run(sys.argv[1])
print("stage5-speed build", build_id)
print(json.dumps(out, indent=1))
