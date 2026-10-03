#!/bin/bash
set -u
python3 - <<'PY' || exit 1
import json, sys
c = json.load(open("config.json"))
want = {"name": "svc", "port": 8080, "debug": False, "hosts": ["a.local", "b.local"]}
sys.exit(0) if c == want else sys.exit(f"FAIL: config is {c}")
PY
echo PASS
