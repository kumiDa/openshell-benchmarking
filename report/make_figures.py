"""Generate the blog figures from results/ (plan §9.2). Light and dark variants, SVG + PNG.

  .venv-report/bin/python report/make_figures.py

Colour: setups form a ladder (A host -> B docker -> C openshell-open -> D openshell-strict), so
they use a validated single-hue ORDINAL ramp (more isolation = more prominent); A2 (srt, a
different approach rather than a rung) uses categorical orange. Every setup is also direct-
labelled, so identity never rests on colour alone. Attack outcomes use the status palette with
text in every cell. Palettes validated with the dataviz skill's validate_palette.js
(--ordinal per mode; orange vs every ramp step, all-pairs, CVD dE >= 23).
Figures whose data is not in yet are skipped with a note.
"""
import glob
import json
import re
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "report" / "figures"
ARMS = ["A", "A2", "B", "C", "D"]
NETWORK_TASKS = {"git-clone", "pip-version", "pypi-download"}
ARM_LABEL = {"A": "A · host shell", "A2": "A2 · srt (bubblewrap)", "B": "B · Docker",
             "C": "C · OpenShell, permissive", "D": "D · OpenShell, strict"}
ARM_SHORT = {"A": "host", "A2": "srt", "B": "Docker", "C": "OpenShell (permissive)", "D": "OpenShell (strict)"}

THEMES = {
    "light": {"surface": "#fcfcfb", "text": "#0b0b0b", "text2": "#52514e", "grid": "#e4e3df",
              "arm": {"A": "#86b6ef", "B": "#3987e5", "C": "#1c5cab", "D": "#0d366b", "A2": "#eb6834"},
              "good": "#0ca30c", "critical": "#d03b3b", "neutral": "#c9c8c3"},
    "dark": {"surface": "#1a1a19", "text": "#ffffff", "text2": "#c3c2b7", "grid": "#33332f",
             "arm": {"A": "#184f95", "B": "#2a78d6", "C": "#6da7ec", "D": "#b7d3f6", "A2": "#d95926"},
             "good": "#0ca30c", "critical": "#d03b3b", "neutral": "#55554f"},
}


# ---------------------------------------------------------------- data loading & stats
def load_jsonl(pattern):
    rows = []
    for f in sorted(glob.glob(str(ROOT / pattern))):
        rows += [json.loads(l) for l in open(f) if l.strip()]
    return rows


def micro():
    per_arm = {}
    for f in sorted(glob.glob(str(ROOT / "results" / "micro" / "*.json"))):
        d = json.load(open(f))
        for k, v in d["metrics"].items():
            if not k.startswith("M5_fio"):
                per_arm.setdefault(d["arm"], {})[k] = v
    return per_arm


def wilson(k, n, z=1.96):
    if n == 0:
        return (math.nan, math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def pass_hat_k(c, n, k):
    """tau-bench pass^k: P(all k of k i.i.d. trials succeed), unbiased estimate C(c,k)/C(n,k)."""
    return math.comb(c, k) / math.comb(n, k) if n >= k else math.nan


# ---------------------------------------------------------------- styling helpers
def fig_ax(t, w=7.2, h=3.8, ncols=1):
    fig, axes = plt.subplots(1, ncols, figsize=(w, h), squeeze=False)
    fig.patch.set_facecolor(t["surface"])
    for ax in axes[0]:
        ax.set_facecolor(t["surface"])
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(t["grid"])
        ax.tick_params(which="both", colors=t["text2"], labelsize=9)
        ax.xaxis.label.set_color(t["text2"])
        ax.yaxis.label.set_color(t["text2"])
        ax.grid(True, axis="x", color=t["grid"], linewidth=0.6)
        ax.set_axisbelow(True)
    return fig, axes[0]


def title(fig, t, text, sub=None):
    h = fig.get_figheight()
    fig.suptitle(text, x=0.02, y=1 - 0.12 / h, ha="left", va="top", fontsize=12, fontweight="bold", color=t["text"])
    if sub:
        fig.text(0.02, 1 - 0.40 / h, sub, ha="left", va="top", fontsize=9, color=t["text2"])


def save(fig, name, mode):
    d = OUT / mode
    d.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.62 / fig.get_figheight()))
    for ext in ("svg", "png"):
        fig.savefig(d / f"{name}.{ext}", dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)


# ---------------------------------------------------------------- figures
def f3_roundtrip(m, t, mode):
    """Per-command cost: M3 round trip, M1 cold start, M2 teardown (small multiples, own x scales)."""
    arms = [a for a in ARMS if a in m and "M3_exec_roundtrip_s" in m[a]]
    if len(arms) < 2:
        return "F3: needs M3 for >=2 setups"
    panels = [("M3_exec_roundtrip_s", "Per-command round trip (ms)"), ("M1_cold_start_s", "Sandbox start (ms)"),
              ("M2_teardown_s", "Teardown (ms)")]
    fig, axes = fig_ax(t, w=10, h=3.4, ncols=3)
    for ax, (key, lab) in zip(axes, panels):
        ys = list(range(len(arms)))[::-1]
        for y, a in zip(ys, arms):
            v = m[a].get(key)
            if not v or not v.get("n"):
                continue
            med, p95 = v["median"] * 1000, v["p95"] * 1000
            ax.barh(y, med, height=0.55, color=t["arm"][a], edgecolor=t["surface"], linewidth=2)
            ax.plot([med, p95], [y, y], color=t["text2"], linewidth=1)
            ax.text(p95, y, f"  {med:,.0f}", va="center", fontsize=8.5, color=t["text"])
        ax.set_yticks(ys, [ARM_SHORT[a] for a in arms] if ax is axes[0] else [""] * len(arms))
        ax.set_xlabel(lab)
        ax.margins(x=0.25)
    title(fig, t, "What each layer costs per command and per sandbox",
          "Median (bar) and p95 (whisker), 20+ reps. Separate scales per panel.")
    save(fig, "F3_lifecycle_costs", mode)


def f4_ecdf(m, t, mode):
    arms = [a for a in ARMS if a in m and m[a].get("M3_exec_roundtrip_s", {}).get("samples")]
    if len(arms) < 2:
        return "F4: needs M3 samples"
    fig, (ax,) = fig_ax(t, h=3.6)
    for a in arms:
        xs = np.sort(np.array(m[a]["M3_exec_roundtrip_s"]["samples"]) * 1000)
        ys = np.arange(1, len(xs) + 1) / len(xs)
        ax.step(xs, ys, where="post", color=t["arm"][a], linewidth=2, label=ARM_SHORT[a])
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xticks([1, 2, 5, 10, 20, 50, 100])
    leg = ax.legend(frameon=False, fontsize=8.5, loc="center")  # empty band between host and containers
    for txt in leg.get_texts():
        txt.set_color(t["text"])
    ax.set_xlabel("Round trip for `true`, host → environment → host (ms, log scale)")
    ax.set_ylabel("Share of commands")
    title(fig, t, "Every agent command pays the round trip", "Empirical CDF of M3.")
    save(fig, "F4_roundtrip_ecdf", mode)


def f5_workload_ratio(m, t, mode):
    keys = ["M4_spawn_1000_true_s", "M5_seq_write_256m_fsync_s", "M5_rand_rw_4k_s", "M6_git_20k_files_s",
            "M7_pip_install_cold_s", "M8_https_get_pypi_s", "M10_cpu_python_s", "M10_cpu_sha256_256m_s"]
    names = ["1,000 process spawns", "Sequential write 256 MB", "Random 4k I/O", "git, 20k files",
             "pip install (cold)", "HTTPS GET PyPI", "CPU: Python loop", "CPU: sha256 256 MB"]
    if "B" not in m:
        return "F5: needs baseline B"
    arms = [a for a in ("C", "D") if a in m]
    fig, (ax,) = fig_ax(t, h=4.2)
    ys = list(range(len(keys)))[::-1]
    for y, k in zip(ys, keys):
        base = m["B"].get(k, {}).get("median")
        for i, a in enumerate(arms):
            v = m[a].get(k, {})
            if base and v.get("n"):
                ax.plot(v["median"] / base, y + (0.12 if i == 0 else -0.12), "o", ms=8, color=t["arm"][a],
                        markeredgecolor=t["surface"], markeredgewidth=2)
    ax.axvline(1.0, color=t["text2"], linewidth=1, linestyle=(0, (3, 3)))
    ax.set_yticks(ys, names)
    ax.set_xlabel("Median time relative to plain Docker (B = 1.0)")
    handles = [plt.Line2D([], [], marker="o", ls="", color=t["arm"][a], ms=8, label=ARM_SHORT[a]) for a in arms]
    leg = ax.legend(handles=handles, frameon=False, fontsize=8.5, loc="lower right")
    for txt in leg.get_texts():
        txt.set_color(t["text"])
    title(fig, t, "Workload time inside OpenShell, relative to plain Docker",
          "Same image and kernel. Median of 20 reps, one session; repeat sessions pending.")
    save(fig, "F5_workload_relative", mode)


def f6_task_success(rows, t, mode):
    agent = [r for r in rows if r.get("mode") == "agent" and not r.get("error")]
    if not agent:
        return "F6: no utility rows yet"
    by = defaultdict(lambda: [0, 0])
    for r in agent:
        c = by[(r["task"], r["arm"])]
        c[0] += bool(r["success"])
        c[1] += 1
    tasks = sorted({k[0] for k in by})
    net = {r["task"] for r in agent if r.get("network_task")}
    arms = [a for a in ARMS if any(k[1] == a for k in by)]
    fig, (ax,) = fig_ax(t, w=7.6, h=0.42 * len(tasks) + 1.6)
    ys = {task: i for i, task in enumerate(tasks[::-1])}
    off = np.linspace(-0.25, 0.25, len(arms))
    for o, a in zip(off, arms):
        for task in tasks:
            k, n = by.get((task, a), (0, 0))
            if n:
                p, lo, hi = wilson(k, n)
                ax.plot([lo, hi], [ys[task] + o] * 2, color=t["arm"][a], linewidth=1.2, alpha=0.6)
                ax.plot(p, ys[task] + o, "o", ms=7, color=t["arm"][a], markeredgecolor=t["surface"],
                        markeredgewidth=1.5)
    ax.set_yticks(list(ys.values()), [f"{x}  (network)" if x in net else x for x in ys])
    ax.set_xlim(-0.02, 1.02)
    ax.set_xlabel("Task success rate (dot) with 95% Wilson interval")
    handles = [plt.Line2D([], [], marker="o", ls="", color=t["arm"][a], ms=7, label=ARM_SHORT[a]) for a in arms]
    leg = ax.legend(handles=handles, frameon=False, fontsize=8, ncol=len(arms), loc="upper center",
                    bbox_to_anchor=(0.5, -0.12))
    for txt in leg.get_texts():
        txt.set_color(t["text"])
    n_per = max(n for _, n in by.values())
    title(fig, t, "Does sandboxing change whether the agent succeeds?",
          f"qwen2.5:3b, {n_per} trials per task and setup. Host (A) differs in prompt path and toolchain, so compare B, C, D.")
    save(fig, "F6_task_success", mode)


def f7_pass_k(rows, t, mode):
    agent = [r for r in rows if r.get("mode") == "agent" and not r.get("error")]
    by = defaultdict(lambda: [0, 0])
    for r in agent:
        c = by[(r["task"], r["arm"])]
        c[0] += bool(r["success"])
        c[1] += 1
    arms = [a for a in ARMS if any(k[1] == a for k in by)]
    nmin = min((n for _, n in by.values()), default=0)
    if nmin < 5:
        return "F7: needs >=5 trials per task/setup"
    ks = list(range(1, min(nmin, 10) + 1))
    fig, (ax,) = fig_ax(t, h=3.6)
    for a in arms:
        vals = [np.nanmean([pass_hat_k(c, n, k) for (task, arm), (c, n) in by.items() if arm == a]) for k in ks]
        ax.plot(ks, vals, color=t["arm"][a], linewidth=2, marker="o", ms=5, label=ARM_SHORT[a])
    leg = ax.legend(frameon=False, fontsize=8.5, loc="upper right")  # curves converge: legend, not end labels
    for txt in leg.get_texts():
        txt.set_color(t["text"])
    ax.set_xlabel("k (all k independent trials must succeed)")
    ax.set_ylabel("pass^k, mean over tasks")
    ax.set_ylim(0, 1)
    ax.grid(True, axis="y", color=t["grid"], linewidth=0.6)
    title(fig, t, "Reliability, not just luck", "pass^k as in τ-bench (Yao et al., 2024).")
    save(fig, "F7_pass_k", mode)


def f8_time_vs_success(rows, t, mode):
    agent = [r for r in rows if r.get("mode") == "agent" and not r.get("error")]
    arms = [a for a in ARMS if any(r["arm"] == a for r in agent)]
    if len(arms) < 2:
        return "F8: needs >=2 setups of utility rows"
    fig, (ax,) = fig_ax(t, h=3.8)
    for a in arms:
        rs = [r for r in agent if r["arm"] == a]
        p, lo, hi = wilson(sum(bool(r["success"]) for r in rs), len(rs))
        tool = np.median([r.get("tool_s", 0) for r in rs])
        wall = np.median([r.get("wall_s", 0) for r in rs])
        ax.plot([wall, wall], [lo, hi], color=t["arm"][a], linewidth=1.2)
        ax.plot(wall, p, "o", ms=9, color=t["arm"][a], markeredgecolor=t["surface"], markeredgewidth=2)
        ax.text(wall, p, f"  {ARM_SHORT[a]} (tools {tool:.1f}s)", va="center", fontsize=8.5, color=t["text"])
    ax.set_xlabel("Median wall-clock seconds per task (model + tools)")
    ax.set_ylabel("Task success rate")
    ax.grid(True, axis="y", color=t["grid"], linewidth=0.6)
    title(fig, t, "Time vs success, per setup", "Local model, so wall time stands in for cost (Kapoor et al., 2024).")
    save(fig, "F8_time_vs_success", mode)


ATTACKS = [("S1a", "Exfiltrate secret → host listener"), ("S1b", "Exfiltrate secret → example.com"),
           ("S3", "Read ~/.ssh key outside workspace"), ("S4", "rm -rf outside workspace"),
           ("S8", "curl | sh from unapproved host"), ("S10", "Model server admin API"),
           ("S2", "Read raw API credential from env"), ("S5", "POST to allowed read-only host"),
           ("S6", "Secret in GET query to allowed host")]


def f9_attack_heatmap(rrows, t, mode):
    valid = [r for r in rrows if r.get("succeeded") is not None]
    arms = [a for a in ARMS if any(r["arm"] == a for r in valid)]
    if not arms:
        return "F9: no replay rows yet"
    fig, (ax,) = fig_ax(t, w=1.6 * len(arms) + 3.6, h=0.55 * len(ATTACKS) + 1.2)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    for j, a in enumerate(arms):
        for i, (aid, _) in enumerate(ATTACKS):
            rs = [r for r in valid if r["arm"] == a and r["attack"] == aid]
            if not rs:
                continue
            k, n = sum(r["succeeded"] for r in rs), len(rs)
            col = t["critical"] if k == n else t["good"] if k == 0 else t["neutral"]
            ax.add_patch(plt.Rectangle((j + 0.04, -i - 0.96), 0.92, 0.92, color=col, linewidth=0))
            label = ("✗ got through" if k == n else "✓ blocked" if k == 0 else "partial") + f"\n{k}/{n}"
            ax.text(j + 0.5, -i - 0.5, label, ha="center", va="center", fontsize=8, color="#ffffff",
                    fontweight="bold")
    ax.set_xlim(0, len(arms))
    ax.set_ylim(-len(ATTACKS), 0)
    ax.set_xticks([j + 0.5 for j in range(len(arms))], [ARM_SHORT[a] for a in arms], fontsize=8.5)
    ax.xaxis.tick_top()
    ax.set_yticks([-i - 0.5 for i in range(len(ATTACKS))], [n for _, n in ATTACKS], fontsize=8.5)
    ax.tick_params(length=0)
    n = max(sum(1 for r in valid if r["arm"] == arms[0] and r["attack"] == "S1a"), 1)
    title(fig, t, "What got through", f"Replayed attack commands, no model in the loop; {n} reps per cell.")
    save(fig, "F9_attack_heatmap", mode)


def f10_utility_vs_security(urows, rrows, t, mode):
    agent = [r for r in urows if r.get("mode") == "agent" and not r.get("error")]
    valid = [r for r in rrows if r.get("succeeded") is not None]
    arms = [a for a in ARMS if any(r["arm"] == a for r in agent) and any(r["arm"] == a for r in valid)]
    if len(arms) < 2:
        return "F10: needs utility and replay rows for >=2 setups"
    fig, (ax,) = fig_ax(t, h=3.8)
    for a in arms:
        u = wilson(sum(bool(r["success"]) for r in agent if r["arm"] == a), sum(1 for r in agent if r["arm"] == a))
        rs = [r for r in valid if r["arm"] == a]
        blocked = 1 - sum(r["succeeded"] for r in rs) / len(rs)
        ax.plot([u[1], u[2]], [blocked, blocked], color=t["arm"][a], linewidth=1.2)
        ax.plot(u[0], blocked, "o", ms=9, color=t["arm"][a], markeredgecolor=t["surface"], markeredgewidth=2)
        below = blocked < 0.05  # bottom row: label under the point so it can't collide with rows above
        ax.annotate(ARM_SHORT[a], (u[0], blocked), xytext=(0, -15 if below else 9), textcoords="offset points",
                    ha="center", fontsize=8.5, color=t["text"])
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.14, 1.12)
    ax.set_xlabel("Task success rate (utility)")
    ax.set_ylabel("Share of attacks blocked")
    ax.grid(True, axis="y", color=t["grid"], linewidth=0.6)
    title(fig, t, "Utility vs security", "Layout after AgentDojo (Debenedetti et al., 2024).")
    save(fig, "F10_utility_vs_security", mode)


SELF_HOSTNAME_DENIAL = re.compile(r"DENIED [0-9a-f]{12} \[reason:policy_dns_ineligible\]")


def meaningful_denials(r):
    """Denials excluding lookups of the sandbox's own container hostname (12 hex chars), which tools
    like git resolve for a default identity. Those are logged as DENIED but are noise, not friction.
    Rows without `denial_sample` (written before the field existed) fall back to the raw count."""
    sample = r.get("denial_sample")
    if sample is None:
        return r.get("denials") or 0
    return sum(1 for x in sample if not SELF_HOSTNAME_DENIAL.search(x)) + max(0, (r.get("denials") or 0) - len(sample))


def f11_denials(rows, t, mode):
    """Logged denials vs real friction on benign tasks. Most logged denials are the sandbox resolving
    its own container hostname (git's default identity), which is noise, not a blocked action."""
    rs = [r for r in rows if r.get("mode") == "agent" and r.get("arm") in ("C", "D") and not r.get("error")
          and r.get("denials") is not None]
    if not rs:
        return "F11: no OpenShell utility rows yet"
    groups = [(arm, net) for arm in ("C", "D") for net in (False, True)]
    fig, (ax,) = fig_ax(t, h=3.4)
    ys = list(range(len(groups)))[::-1]
    for y, (arm, net) in zip(ys, groups):
        g = [r for r in rs if r["arm"] == arm and (r["task"] in NETWORK_TASKS) == net]
        raw = sum(r["denials"] > 0 for r in g) / len(g)
        real = sum(meaningful_denials(r) > 0 for r in g) / len(g)
        ax.barh(y + 0.17, raw, height=0.32, color=t["neutral"], edgecolor=t["surface"], linewidth=2)
        ax.barh(y - 0.17, real, height=0.32, color=t["arm"][arm], edgecolor=t["surface"], linewidth=2)
        ax.text(raw, y + 0.17, f"  {raw:.0%} any logged denial", va="center", fontsize=8, color=t["text2"])
        ax.text(real, y - 0.17, f"  {real:.1%} real denial ({sum(meaningful_denials(r) > 0 for r in g)}/{len(g)})",
                va="center", fontsize=8, color=t["text"])
    ax.set_yticks(ys, [f"{ARM_SHORT[a]}\n{'network tasks' if n else 'offline tasks'}" for a, n in groups], fontsize=8.5)
    ax.set_xlim(0, 0.62)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("Share of benign task runs")
    title(fig, t, "Logged denials are mostly noise",
          "Gray: any DENIED event. Colour: excluding the sandbox resolving its own hostname (git identity lookups).")
    save(fig, "F11_denials_friction", mode)


def main():
    m = micro()
    urows = load_jsonl("results/raw/main-utility-*.jsonl")
    rrows = load_jsonl("results/replay/replay-main-*.jsonl")
    notes = []
    for mode, t in THEMES.items():
        for fn, args in ((f3_roundtrip, (m,)), (f4_ecdf, (m,)), (f5_workload_ratio, (m,)),
                         (f6_task_success, (urows,)), (f7_pass_k, (urows,)), (f8_time_vs_success, (urows,)),
                         (f9_attack_heatmap, (rrows,)), (f10_utility_vs_security, (urows, rrows)),
                         (f11_denials, (urows,))):
            msg = fn(*args, t, mode)
            if msg and mode == "light":
                notes.append(msg)
    print("figures ->", OUT)
    for n in notes:
        print("skipped:", n)


if __name__ == "__main__":
    main()
