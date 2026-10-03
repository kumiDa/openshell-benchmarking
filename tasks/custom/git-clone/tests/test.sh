#!/bin/bash
set -u
git -C hello rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "FAIL: hello is not a git repository"; exit 1; }
git -C hello remote get-url origin | grep -q "octocat/Hello-World" || { echo "FAIL: wrong origin"; exit 1; }
[ -f hello/README ] || { echo "FAIL: hello/README missing"; exit 1; }
echo PASS
