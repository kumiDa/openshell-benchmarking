#!/bin/bash
# Main unattended run: replay attacks, then the utility matrix. Resumable (re-run the same command).
set -u
cd "$(dirname "$0")"
echo "[$(date -Is)] replay start"
python3 replay.py --arms A,B,C,D --reps 20 --run-id replay-main-v1
echo "[$(date -Is)] replay done; matrix start"
python3 run_matrix.py --arms A,B,C,D --trials 20 --run-id main-utility-v1
echo "[$(date -Is)] all done"
