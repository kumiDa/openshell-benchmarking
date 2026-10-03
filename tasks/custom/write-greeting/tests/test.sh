#!/bin/bash
[ "$(cat greeting.txt 2>/dev/null | tr -d '\n')" = "hello openshell" ] && echo PASS || { echo "FAIL: greeting.txt = '$(cat greeting.txt 2>&1)'"; exit 1; }
