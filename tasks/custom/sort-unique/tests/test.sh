#!/bin/bash
set -u
[ "$(cat unique.txt 2>/dev/null)" = "ada
bob
cyd
dee
eve
fay
gus
hal" ] || { echo "FAIL: unique.txt does not match"; exit 1; }
echo PASS
