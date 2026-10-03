"""Test the preregistered hypotheses in HYPOTHESES.md against results/raw/main-utility-*.jsonl.

  .venv-report/bin/python report/analyze.py [--run-id main-utility-v1] [--json out.json]

The unit of analysis is the task. Differences between setups are paired per task. CIs use a
two-stage cluster bootstrap (resample tasks, then trials within each task), 10,000 draws, seed 0.
Rows with `error` are excluded from success rates and reported separately (as fixed in advance).
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
NETWORK = {"git-clone", "pip-version", "pypi-download"}
B_DRAWS = 10_000


def load(run_id):
    rows = [json.loads(l) for l in open(ROOT / "results" / "raw" / f"{run_id}.jsonl") if l.strip()]
    return [r for r in rows if r.get("mode") == "agent"]


def outcomes(rows):
    """{(task, arm): np.array of 0/1} for valid rows."""
    d = defaultdict(list)
    for r in rows:
        if not r.get("error"):
            d[(r["task"], r["arm"])].append(int(bool(r["success"])))
    return {k: np.array(v) for k, v in d.items()}


def paired_diff(o, arm_x, arm_y, tasks, rng, one_sided=False):
    """Mean over tasks of (pass_x - pass_y), with a cluster-bootstrap 95% CI."""
    tasks = [t for t in tasks if (t, arm_x) in o and (t, arm_y) in o]
    if not tasks:
        return None
    point = float(np.mean([o[(t, arm_x)].mean() - o[(t, arm_y)].mean() for t in tasks]))
    draws = np.empty(B_DRAWS)
    for b in range(B_DRAWS):
        ts = rng.choice(tasks, size=len(tasks), replace=True)
        diffs = []
        for t in ts:
            x, y = o[(t, arm_x)], o[(t, arm_y)]
            diffs.append(rng.choice(x, len(x)).mean() - rng.choice(y, len(y)).mean())
        draws[b] = np.mean(diffs)
    lo, hi = (np.quantile(draws, 0.05), np.inf) if one_sided else np.quantile(draws, [0.025, 0.975])
    return {"diff_pp": 100 * point, "ci_pp": [100 * float(lo), 100 * float(hi)], "n_tasks": len(tasks),
            "trials": {t: [int(len(o[(t, arm_x)])), int(len(o[(t, arm_y)]))] for t in tasks}}


def within(res, margin_pp=10):
    return res is not None and -margin_pp <= res["ci_pp"][0] and res["ci_pp"][1] <= margin_pp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="main-utility-v1")
    ap.add_argument("--json")
    a = ap.parse_args()
    rng = np.random.default_rng(0)
    rows = load(a.run_id)
    o = outcomes(rows)
    tasks = sorted({t for t, _ in o})
    local = [t for t in tasks if t not in NETWORK]
    net = [t for t in tasks if t in NETWORK]

    hyp_hash = hashlib.sha256((ROOT / "HYPOTHESES.md").read_bytes()).hexdigest()
    frozen = (ROOT / "HYPOTHESES.sha256").read_text().split()[0]
    out = {"run_id": a.run_id, "rows": len(rows), "hypotheses_sha256_matches": hyp_hash == frozen}

    # errors per arm (reported separately, as preregistered)
    err = defaultdict(lambda: [0, 0])
    for r in rows:
        err[r["arm"]][1] += 1
        err[r["arm"]][0] += bool(r.get("error"))
    out["errors"] = {k: {"errors": v[0], "rows": v[1]} for k, v in sorted(err.items())}

    out["pass_rate"] = {arm: {t: round(float(o[(t, arm)].mean()), 3) for t in tasks if (t, arm) in o}
                        for arm in "ABCD"}
    h1 = paired_diff(o, "B", "A", tasks, rng)
    h2 = paired_diff(o, "C", "B", tasks, rng)
    h3 = paired_diff(o, "D", "C", local, rng)
    h4 = paired_diff(o, "C", "D", net, rng, one_sided=True)
    out["H1_B_minus_A"] = {**(h1 or {}), "supported": within(h1)}
    out["H2_C_minus_B"] = {**(h2 or {}), "supported": within(h2)}
    out["H3_D_minus_C_local"] = {**(h3 or {}), "supported": within(h3)}
    out["H4_C_minus_D_network_one_sided"] = {**(h4 or {}), "supported": bool(h4 and h4["ci_pp"][0] > 0),
                                              "note": "3 tasks: low power; a null is inconclusive"}

    # H5: denial shares (raw and excluding self-hostname lookups)
    import sys
    sys.path.insert(0, str(ROOT / "report"))
    from make_figures import meaningful_denials  # noqa: E402
    h5 = {}
    for arm in ("C", "D"):
        for label, ts in (("network", net), ("local", local)):
            rs = [r for r in rows if r["arm"] == arm and r["task"] in ts and not r.get("error")
                  and r.get("denials") is not None]
            if rs:
                h5[f"{arm}_{label}"] = {"share_any_denial": round(sum(r["denials"] > 0 for r in rs) / len(rs), 3),
                                        "share_meaningful_denial": round(sum(meaningful_denials(r) > 0 for r in rs) / len(rs), 3),
                                        "runs": len(rs)}
    c_all = [r for r in rows if r["arm"] == "C" and not r.get("error") and r.get("denials") is not None]
    out["H5_denials"] = {**h5, "supported_raw": bool(c_all) and sum(r["denials"] > 0 for r in c_all) / len(c_all) < 0.05
                         and h5.get("D_network", {}).get("share_any_denial", 0) > h5.get("D_local", {}).get("share_any_denial", 1),
                         "note": "raw = preregistered definition; meaningful excludes self-hostname DNS lookups (documented deviation)"}

    # H6: tool time vs wall time
    def med(arm, key):
        v = [r.get(key) for r in rows if r["arm"] == arm and not r.get("error") and r.get(key) is not None]
        return float(np.median(v)) if v else None
    h6 = {arm: {"median_wall_s": med(arm, "wall_s"), "median_tool_s": med(arm, "tool_s"),
                "median_model_s": med(arm, "model_s")} for arm in "ABCD"}
    if h6["B"]["median_wall_s"] and h6["C"]["median_tool_s"] is not None:
        extra = h6["C"]["median_tool_s"] - h6["B"]["median_tool_s"]
        out["H6_overhead_share"] = {**h6, "C_minus_B_tool_s": extra,
                                    "share_of_B_wall": extra / h6["B"]["median_wall_s"],
                                    "supported": extra / h6["B"]["median_wall_s"] < 0.10}

    print(json.dumps(out, indent=1, default=lambda x: round(x, 2) if isinstance(x, float) else x))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
