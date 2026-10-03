#!/bin/bash
set -u
python3 - <<'PY'
import csv, sys
try:
    import tabulate
except ImportError:
    sys.exit("FAIL: tabulate not importable")
if tabulate.__version__ != "0.9.0":
    sys.exit(f"FAIL: tabulate version {tabulate.__version__}")
rows = list(csv.reader(open("inventory.csv")))
want = tabulate.tabulate(rows[1:], headers=rows[0], tablefmt="github").strip()
try:
    got = open("inventory.md").read().strip()
except FileNotFoundError:
    sys.exit("FAIL: inventory.md missing")
norm = lambda s: [" ".join(l.split()) for l in s.splitlines()]
if norm(got) != norm(want):
    sys.exit(f"FAIL: table mismatch\n--- got\n{got}\n--- want\n{want}")
print("PASS")
PY
