"""Merge micro-benchmark result files per arm (newest file wins per metric) and print a table.

  python3 report/micro_table.py [--json out.json]

Superseded metrics (fio-based M5, replaced because fio calls nice(), which OpenShell's seccomp
filter denies) are excluded.
"""
import argparse
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUPERSEDED = {"M5_fio_randrw_4k_s", "M5_fio_seq_1m_s"}
ARMS = ["A", "A2", "B", "C", "D"]


def merged():
    per_arm = {}
    for f in sorted(glob.glob(str(ROOT / "results" / "micro" / "*.json"))):  # names sort by timestamp
        d = json.load(open(f))
        for k, v in d["metrics"].items():
            if k not in SUPERSEDED:
                per_arm.setdefault(d["arm"], {})[k] = {**v, "source": Path(f).name}
    return per_arm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    m = merged()
    arms = [x for x in ARMS if x in m]
    keys = sorted({k for v in m.values() for k in v}, key=lambda k: (int(k.split("_")[0][1:]), k))
    print(f"{'metric (median ms, [p95])':34}" + "".join(f"{x:>18}" for x in arms))
    for k in keys:
        row = f"{k:34}"
        for x in arms:
            v = m[x].get(k)
            row += (f"{v['median'] * 1000:>10.1f} [{v['p95'] * 1000:>5.0f}]" if v and v.get("n")
                    else f"{('fail ' + str(v.get('failures'))) if v else '—':>18}")
        print(row)
    if a.json:
        Path(a.json).write_text(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
