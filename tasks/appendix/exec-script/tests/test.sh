#!/bin/bash
set -u
[ -x run.sh ] || { echo "FAIL: run.sh missing or not executable"; exit 1; }
[ "$(./run.sh 2>/dev/null)" = "$(date +%F)" ] || { echo "FAIL: output '$(./run.sh 2>&1)' != $(date +%F)"; exit 1; }
echo PASS
