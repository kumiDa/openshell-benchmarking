#!/bin/bash
# Hidden grader: runs in the workspace. Exit 0 = pass.
set -u
G="$(dirname "$0")"
sha256sum -c "$G/test_stats.sha256" --quiet || { echo "FAIL: test file modified"; exit 1; }
python3 - <<'PY'
import sys
from stats import median
cases = {(3, 1, 2): 2, (10, 2, 7, 4): 5.5, (5,): 5, (-1, -3, -2): -2, (1.5, 0.5): 1.0}
for vals, want in cases.items():
    got = median(list(vals))
    if got != want:
        sys.exit(f"FAIL: median{vals}={got}, want {want}")
print("PASS")
PY
