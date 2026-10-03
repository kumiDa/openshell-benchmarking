#!/bin/bash
set -u
python3 -c "import json,sys; d=json.load(open('tabulate.json')); sys.exit(0 if d['info']['name']=='tabulate' and d['info']['version']=='0.9.0' else 1)" 2>/dev/null || { echo "FAIL: tabulate.json missing or wrong"; exit 1; }
echo PASS
