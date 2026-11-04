"""Stage 6 street-pattern measures. Usage: ~/geometis-venv/bin/python -u run_stage6_street_pattern.py us-ca-contra-costa-5"""
import json
import sys

from gkg import stage6_street_pattern

build_id, out = stage6_street_pattern.run(sys.argv[1])
print("stage6-street-pattern build", build_id)
print(json.dumps(out, indent=1))
