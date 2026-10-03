#!/bin/bash
set -u
python3 - <<'PY'
import csv, json, sys
want = {}
for r in csv.DictReader(open("sales.csv")):
    want[r["region"]] = want.get(r["region"], 0) + int(r["units"]) * float(r["unit_price"])
want = {k: round(v, 2) for k, v in want.items()}
try:
    got = json.load(open("summary.json"))
except Exception as e:
    sys.exit(f"FAIL: cannot read summary.json: {e}")
if set(got) != set(want) or any(abs(float(got[k]) - want[k]) > 0.011 for k in want):
    sys.exit(f"FAIL: got {got}, want {want}")
print("PASS")
PY
