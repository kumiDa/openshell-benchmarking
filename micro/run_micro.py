"""Track 1 micro-benchmarks (no LLM). One JSON file per arm in results/micro/.

  python3 micro/run_micro.py --arm B [--reps 20] [--only M3,M4]

Do NOT run while the model server is generating: it competes for CPU.
Timings for in-sandbox workloads are taken *inside* the arm (date +%s%N), so they
exclude the host->sandbox exec round trip, which M3 measures separately.
"""
import argparse
import json
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runner"))
from arms import ROOT, make_arm  # noqa: E402

OUT = ROOT / "results" / "micro"
PYPI_PROBE = "https://pypi.org/simple/tabulate/"  # allowed egress in every arm's policy


def timed_inside(arm, work, timeout=600):
    """Run `work` in the arm, timing it inside the arm. Returns seconds or None on failure."""
    # pipefail: a failing producer (e.g. unreadable /dev/zero under a strict policy) must not be
    # masked by a succeeding consumer and recorded as a bogus fast success.
    script = f'set -o pipefail; s=$(date +%s%N); {{ {work} ; }} >/dev/null 2>&1; rc=$?; e=$(date +%s%N); echo "__T $rc $(( (e-s) ))"'
    rc, out, _ = arm.exec(script, timeout=timeout)
    for line in out.splitlines():
        if line.startswith("__T "):
            _, wrc, ns = line.split()
            return int(ns) / 1e9 if wrc == "0" else None
    return None


def summarize(samples):
    xs = sorted(x for x in samples if x is not None)
    if not xs:
        return {"n": 0, "failures": len(samples)}
    q = lambda p: xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]
    return {"n": len(xs), "failures": len(samples) - len(xs), "median": statistics.median(xs),
            "p95": q(0.95), "p99": q(0.99), "min": xs[0], "max": xs[-1],
            "stdev": statistics.stdev(xs) if len(xs) > 1 else 0.0, "samples": xs}


def m1_m2_lifecycle(arm_id, reps, tiny_repo):
    up, down = [], []
    for i in range(reps):
        arm = make_arm(arm_id, f"micro-life-{arm_id.lower()}-{i}", ROOT / "tasks" / "custom" / "fix-median")
        t0 = time.monotonic()
        arm.setup(tiny_repo)
        rc, _, _ = arm.exec("true", timeout=120)  # ready = first successful exec
        up.append(time.monotonic() - t0 if rc == 0 else None)
        t0 = time.monotonic()
        arm.teardown()
        down.append(time.monotonic() - t0)
    return {"M1_cold_start_s": summarize(up), "M2_teardown_s": summarize(down)}


def m3_roundtrip(arm, reps):
    """hyperfine over the host-side argv that runs `true` in the arm."""
    cmd = shlex.join(arm.argv("true"))
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        subprocess.run(["hyperfine", "-N", "--warmup", "5", "--runs", str(reps), "--export-json", f.name, cmd],
                       capture_output=True, check=True)
        times = json.load(open(f.name))["results"][0]["times"]
    return {"M3_exec_roundtrip_s": summarize(times)}


def workloads():
    return {
        "M4_spawn_1000_true_s": "for i in $(seq 1000); do /bin/true; done",
        # fio is not usable here: it calls nice() at startup, which OpenShell's seccomp filter denies
        # (EPERM). These equivalents run identically in every arm.
        "M5_seq_write_256m_fsync_s": "dd if=/dev/zero of=io.dat bs=1M count=256 conv=fsync status=none && rm -f io.dat",
        "M5_rand_rw_4k_s": "python3 -c \"import os,random;r=random.Random(1);fd=os.open('io.dat',os.O_RDWR|os.O_CREAT);"
                           "os.ftruncate(fd,64<<20);b=os.urandom(4096);"
                           "[os.pwrite(fd,b,r.randrange(16384)*4096) if i%2 else os.pread(fd,4096,r.randrange(16384)*4096) for i in range(20000)];"
                           "os.fsync(fd);os.close(fd);os.remove('io.dat')\"",
        "M6_git_20k_files_s": "rm -rf g && mkdir g && cd g && git init -q && "
                              "for d in $(seq 100); do mkdir d$d; for f in $(seq 200); do echo $d$f > d$d/f$f; done; done && "
                              "git add -A && git -c user.email=b@b -c user.name=b commit -qm init && git status --short | wc -l && cd .. && rm -rf g",
        "M7_pip_install_cold_s": "python3 -m pip install --user --no-cache-dir -q --force-reinstall tabulate==0.9.0",
        "M8_https_get_pypi_s": f"curl -fsS -o /dev/null {PYPI_PROBE}",
        "M10_cpu_python_s": "python3 -c 'sum(i*i for i in range(5_000_000))'",
        "M10_cpu_sha256_256m_s": "head -c 268435456 /dev/zero | sha256sum",
    }


def m9_transfer(arm, reps):
    res = {}
    with tempfile.TemporaryDirectory() as d:
        big, small = Path(d) / "big", Path(d) / "small"
        big.mkdir(); small.mkdir()
        (big / "blob.bin").write_bytes(b"\0" * 10 * 1024 * 1024)
        for i in range(1000):
            (small / f"f{i}.txt").write_text(str(i))
        for label, src in (("M9_upload_10mb_s", big), ("M9_upload_1k_files_s", small)):
            xs = []
            for i in range(reps):
                dest = str(Path(arm.workdir) / f"up{i}")  # inside the workspace: writable in every arm
                t0 = time.monotonic()
                try:
                    arm.upload(str(src), dest)
                    xs.append(time.monotonic() - t0)
                except Exception:
                    xs.append(None)
                arm.exec(f"rm -rf {shlex.quote(dest)}")
            res[label] = summarize(xs)
    return res


def m11_policy_reload(arm, reps):
    """OpenShell only: wall time of `policy set --wait` until the sandbox reports the revision loaded.
    Alternates between two equivalent policies so every set is a real new revision."""
    import yaml
    base = yaml.safe_load(arm.policy.read_text())
    xs = []
    with tempfile.TemporaryDirectory() as d:
        variants = []
        for i in range(2):
            # Semantically different but inert: a nonexistent binary may reach an unresolvable .invalid
            # host. (A YAML comment alone may hash identically and not create a new revision.)
            pol = dict(base)
            pol["network_policies"] = {**(base.get("network_policies") or {}), f"reload_probe_{i}": {
                "name": f"reload_probe_{i}",
                "endpoints": [{"host": f"reload-probe-{i}.example.invalid", "port": 443}],
                "binaries": [{"path": "/nonexistent/reload-probe"}]}}
            p = Path(d) / f"p{i}.yaml"
            p.write_text(yaml.safe_dump(pol, sort_keys=False))
            variants.append(p)
        for r in range(reps):
            t0 = time.monotonic()
            rc = subprocess.run(["openshell", "policy", "set", arm.sbx, "--policy", str(variants[r % 2]), "--wait"],
                                capture_output=True, text=True).returncode
            xs.append(time.monotonic() - t0 if rc == 0 else None)
    return {"M11_policy_reload_s": summarize(xs)}


def m12_concurrency(arm_id, reps, tiny_repo):
    """M3 round-trip latency while N sandboxes/containers of this arm are running."""
    res = {}
    for n in (1, 4, 16):
        arms = []
        try:
            for i in range(n):
                arms.append(make_arm(arm_id, f"micro-conc-{arm_id.lower()}-{n}-{i}",
                                     ROOT / "tasks" / "custom" / "pip-version").setup(tiny_repo))
            res[f"M12_roundtrip_with_{n}_running_s"] = m3_roundtrip(arms[0], reps)["M3_exec_roundtrip_s"]
        finally:
            for a in arms:
                a.teardown()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["A", "A2", "B", "C", "D"])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--lifecycle-reps", type=int, default=10)
    ap.add_argument("--only", default="", help="comma list of metric prefixes, e.g. M3,M4")
    a = ap.parse_args()
    want = lambda key: not a.only or any(key.startswith(p) for p in a.only.split(","))

    tiny = Path(tempfile.mkdtemp()); (tiny / "README").write_text("micro\n")
    task_dir = ROOT / "tasks" / "custom" / "pip-tabulate"  # its policy/egress allows PyPI for M7/M8
    results = {"arm": a.arm, "started": datetime.now(timezone.utc).isoformat(), "metrics": {}}

    if want("M1") or want("M2"):
        results["metrics"].update(m1_m2_lifecycle(a.arm, a.lifecycle_reps, str(tiny)))

    arm = make_arm(a.arm, f"micro-{a.arm.lower()}", task_dir)
    if a.arm == "D":
        # Micro-benchmarks measure enforcement *cost*, so D gets a strict policy that still permits the
        # workloads: L7-inspected read-only PyPI for curl+python (M7/M8) and readable /dev/zero.
        arm.policy = ROOT / "policies" / "micro-strict.yaml"
    arm.setup(str(tiny))
    try:
        results["versions"] = arm.versions()
        if want("M3"):
            results["metrics"].update(m3_roundtrip(arm, max(a.reps, 50)))
        for key, work in workloads().items():
            if want(key):
                reps = 5 if key.startswith(("M5", "M6", "M7")) else a.reps
                results["metrics"][key] = summarize([timed_inside(arm, work) for _ in range(reps)])
                print(key, {k: round(v, 4) for k, v in results["metrics"][key].items()
                            if isinstance(v, float)}, flush=True)
        if want("M9") and a.arm not in ("A", "A2"):
            results["metrics"].update(m9_transfer(arm, 5))
        if want("M11") and a.arm in ("C", "D"):
            results["metrics"].update(m11_policy_reload(arm, 10))
    finally:
        arm.teardown()
    if want("M12") and a.arm in ("B", "C", "D"):
        results["metrics"].update(m12_concurrency(a.arm, 30, str(tiny)))

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{a.arm}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(results, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
