#!/bin/bash
set -u
git log -1 --pretty=%s 2>/dev/null | grep -qx "add notes" || { echo "FAIL: last commit message is not 'add notes'"; exit 1; }
git ls-files --error-unmatch notes.txt >/dev/null 2>&1 || { echo "FAIL: notes.txt not committed"; exit 1; }
echo PASS
