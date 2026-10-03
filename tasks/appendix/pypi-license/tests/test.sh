#!/bin/bash
set -u
[ "$(tr -d '\n' < license.txt 2>/dev/null)" = "MIT" ] || { echo "FAIL: license.txt = '$(cat license.txt 2>&1)'"; exit 1; }
echo PASS
