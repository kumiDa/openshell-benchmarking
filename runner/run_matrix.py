"""Track 2 main matrix: every (task, arm, trial) once, in a seeded random order, resumable.

  python3 runner/run_matrix.py --arms A,B,C,D --trials 20 --run-id main-utility-v1

Order is shuffled (seed 0) so drift in GPU temperature, network or gateway state spreads across
arms instead of biasing one. Rows already present in results/raw/<run_id>.jsonl are skipped, so
an interrupted run can be resumed with the same command.
"""
import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def done_keys(path):
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
            keys.add((r["task"], r["arm"], r["trial"]))
        except (json.JSONDecodeError, KeyError):
            pass
    return keys


def cleanup_leftovers(task, arm, trial):
    """A killed run skips its teardown. Runs are serial, so whatever matches this run's naming is its own."""
    prefix = f"{task}-{arm.lower()}-{trial}-"
    names = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    for n in names.split():
        if n.startswith(prefix):
            subprocess.run(["docker", "rm", "-f", n], capture_output=True)
    if arm in ("C", "D"):
        listing = subprocess.run(["openshell", "sandbox", "list"], capture_output=True, text=True).stdout
        for line in listing.splitlines():
            first = line.split()[0] if line.split() else ""
            if first.startswith(("osc-", "osd-")):
                subprocess.run(["openshell", "sandbox", "delete", first], capture_output=True, timeout=120)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="A,B,C,D")
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--tasks", default="", help="comma list; default = tasks/suite.json main")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--per-run-timeout", type=int, default=600)
    a = ap.parse_args()

    tasks = a.tasks.split(",") if a.tasks else json.loads((ROOT / "tasks" / "suite.json").read_text())["main"]
    combos = [(t, arm, k) for t in tasks for arm in a.arms.split(",") for k in range(a.trials)]
    random.Random(0).shuffle(combos)
    out = ROOT / "results" / "raw" / f"{a.run_id}.jsonl"
    done = done_keys(out)
    todo = [c for c in combos if c not in done]
    print(f"{len(combos)} combos, {len(done)} done, {len(todo)} to run -> {out}", flush=True)

    t_start = time.monotonic()
    for i, (task, arm, trial) in enumerate(todo, 1):
        cmd = [sys.executable, str(ROOT / "runner" / "run_one.py"), "--task", task, "--arm", arm,
               "--trial", str(trial), "--run-id", a.run_id]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=a.per_run_timeout)
        except subprocess.TimeoutExpired:
            cleanup_leftovers(task, arm, trial)
            # run_one never wrote its row: record the timeout so it isn't silently missing
            with open(out, "a") as f:
                f.write(json.dumps({"run_id": a.run_id, "track": "utility", "task": task, "arm": arm,
                                    "trial": trial, "mode": "agent", "success": False,
                                    "error": f"harness timeout after {a.per_run_timeout}s"}) + "\n")
        if i % 25 == 0 or i == len(todo):
            el = time.monotonic() - t_start
            print(f"[{i}/{len(todo)}] elapsed {el / 60:.1f} min, eta {el / i * (len(todo) - i) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
