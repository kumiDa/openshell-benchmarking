#!/bin/bash
set -u
[ "$(tr -d ' \n' < words.txt 2>/dev/null)" = "147" ] || { echo "FAIL: got '$(cat words.txt 2>&1)', want 147"; exit 1; }
echo PASS
