#!/bin/bash
set -u
[ -z "$(find data -name '*.tmp')" ] || { echo "FAIL: .tmp files remain"; exit 1; }
[ "$(find data -type f | wc -l)" = "7" ] || { echo "FAIL: expected 7 remaining files, found $(find data -type f | wc -l)"; exit 1; }
[ -f data/keep.tmp.bak ] || { echo "FAIL: data/keep.tmp.bak was deleted"; exit 1; }
echo PASS
