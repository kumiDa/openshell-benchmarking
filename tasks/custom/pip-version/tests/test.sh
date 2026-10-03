#!/bin/bash
v=$(python3 -c 'import tabulate; print(tabulate.__version__)' 2>/dev/null) || { echo "FAIL: tabulate not importable"; exit 1; }
[ "$v" = "0.9.0" ] || { echo "FAIL: installed $v"; exit 1; }
[ "$(tr -d ' \n' < version.txt 2>/dev/null)" = "0.9.0" ] && echo PASS || { echo "FAIL: version.txt = '$(cat version.txt 2>&1)'"; exit 1; }
