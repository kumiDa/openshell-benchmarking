"""Run one (task, arm, trial) and append a result row to results/raw/<run_id>.jsonl.

  python3 runner/run_one.py --task fix-median --arm B --trial 0 --mode agent
  python3 runner/run_one.py --task fix-median --arm B --mode reference   # sanity anchor
"""
import argparse
import json
import platform
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent import run as run_agent
from arms import ROOT, make_arm

DEFAULT_MODEL = "qwen2.5:3b"
OLLAMA_URL = "http://127.0.0.1:11434"


def prepare(arm):
    """Liveness control, then the task's optional `.setup.sh` (e.g. `git init`), which deletes itself.
    A non-functional arm raises (row gets `error`) so it is never scored as sandbox friction."""
    rc, out, _ = arm.exec("echo __alive__", timeout=60)
    if "__alive__" not in out:
        raise RuntimeError(f"arm not functional (control command failed, rc={rc}): {out.strip()[-200:]}")
    rc, out, _ = arm.exec("if [ -f .setup.sh ]; then bash .setup.sh; fi", timeout=120)
    if rc != 0:
        raise RuntimeError(f"task setup failed: {out}")


def grade(arm, task_dir):
    """Upload the hidden grader after the episode, run it in the workspace."""
    # Inside the workspace so strict policies (workspace-only filesystem) can run it; uploaded
    # only after the episode ends, so the agent never sees it.
    grader_dir = str(Path(arm.workdir) / ".grader")
    arm.upload(str(task_dir / "tests"), grader_dir)
    rc, out, _ = arm.exec(f"bash {grader_dir}/test.sh", timeout=300)
    return rc == 0 and "PASS" in out, out[-2000:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--arm", required=True, choices=["A", "A2", "B", "C", "D"])
    ap.add_argument("--trial", type=int, default=0)
    ap.add_argument("--mode", choices=["agent", "reference"], default="agent")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-turns", type=int, default=30)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ap.add_argument("--keep", action="store_true", help="skip teardown for debugging")
    a = ap.parse_args()

    task_dir = ROOT / "tasks" / "custom" / a.task
    meta = json.loads((task_dir / "meta.json").read_text())
    name = f"{a.task}-{a.arm.lower()}-{a.trial}-{uuid.uuid4().hex[:6]}"
    arm = make_arm(a.arm, name, task_dir)

    row = {"run_id": a.run_id, "track": "utility", "task": a.task, "arm": a.arm, "trial": a.trial,
           "mode": a.mode, "model": a.model if a.mode == "agent" else None, "network_task": meta.get("network"),
           "started": datetime.now(timezone.utc).isoformat()}
    trace = []
    t0 = time.monotonic()
    try:
        arm.setup(str(task_dir / "repo"))
        prepare(arm)
        row["setup_s"] = round(time.monotonic() - t0, 3)
        if a.mode == "reference":
            rc, out, dt = arm.exec((task_dir / "solution" / "solve.sh").read_text(), timeout=600)
            row.update({"solve_rc": rc, "solve_s": round(dt, 3)})
            trace.append({"type": "reference", "exit_code": rc, "output": out[-3000:]})
        else:
            instruction = (task_dir / "instruction.md").read_text()
            stats = run_agent(arm, instruction, model=a.model, base_url=OLLAMA_URL,
                              seed=a.trial, max_turns=a.max_turns, num_ctx=a.num_ctx, trace=trace)
            row["num_ctx"] = a.num_ctx
            row.update({k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()})
        row["success"], row["grader_output"] = grade(arm, task_dir)
        if hasattr(arm, "denials"):
            d = arm.denials()
            row["denials"] = len(d)
            row["denial_sample"] = [x[-220:] for x in d[:5]]
    except Exception as e:
        row["success"], row["error"] = False, repr(e)
    finally:
        row["total_s"] = round(time.monotonic() - t0, 3)
        row["versions"] = {**arm.versions(), "python": platform.python_version(), "kernel": platform.release()}
        if not a.keep:
            arm.teardown()

    out_dir = ROOT / "results" / "raw"
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{a.run_id}.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    (out_dir / "traces" / f"{name}.json").write_text(json.dumps(trace, indent=1))
    print(json.dumps({k: v for k, v in row.items() if k != "grader_output"}))


if __name__ == "__main__":
    main()
