#!/bin/bash
# Follow-up jobs, started only after runner/run_main.sh has exited (no overlap with the matrix).
set -u
cd "$(dirname "$0")"
while pgrep -f "runner/run_main.sh" >/dev/null; do sleep 30; done
echo "[$(date -Is)] main run finished; extra attacks start"
python3 replay.py --arms A,B,C,D --attacks S2,S5,S6 --reps 20 --run-id replay-main-v2-ext
for session in 2 3; do
  echo "[$(date -Is)] micro session $session"
  for arm in A B C D; do python3 ../micro/run_micro.py --arm $arm --reps 20 2>&1 | grep -E "wrote|Error|Traceback"; done
done
echo "[$(date -Is)] all follow-ups done"
