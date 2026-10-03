#!/bin/bash
want=83;  # fixed at generation: never derive from agent-modifiable files
 got=$(tr -d ' \n' < count.txt 2>/dev/null)
[ "$got" = "$want" ] && echo PASS || { echo "FAIL: got '$got' want '$want'"; exit 1; }
