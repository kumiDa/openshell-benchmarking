#!/bin/bash
set -u
tar -tzf backup.tar.gz >/tmp/tarlist 2>/dev/null || { echo "FAIL: backup.tar.gz missing or not gzip tar"; exit 1; }
for f in intro.md guide/setup.md guide/faq.md; do grep -q "docs/$f" /tmp/tarlist || { echo "FAIL: docs/$f not in archive"; exit 1; }; done
echo PASS
