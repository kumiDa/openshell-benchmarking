# Preregistered hypotheses — task-success track (Track 2)

**Written:** 2026-10-03, about 10:55 IST. The main task-success matrix (`main-utility-v1`) had started at 10:48. **No aggregate task-success results had been computed or viewed**; only the first ~13 rows were glanced at to confirm the harness worked.

**Not preregistered (disclosed):** the overhead hypotheses (Track 1) and the replay-attack results (Track 3) were already known when this was written:
- **Track 1:** M3 round trip 48.8 ms (B) vs 57–60 ms (C/D); policy reload ~10 s.
- **Track 3:** A, B, C 20/20 on S1a, S1b, S3, S4, S8, S10; D 0/20.

**Integrity:** the SHA-256 of this file was recorded at writing time (see `HYPOTHESES.sha256`). Any later edit shows up as a hash mismatch.

## Setup

`qwen2.5:3b`, the lean bash agent (`runner/agent.py`), the 10 tasks in `tasks/suite.json`, setups A/B/C/D, 20 trials per (task, setup), seed = trial index. The unit of analysis is the task; comparisons are paired per task.

## Hypotheses

| # | Hypothesis | Test | Supported if |
|---|---|---|---|
| H1 | Containerization doesn't change success: B ≈ A | Paired per-task difference in pass rate, clustered by task | 95% CI of mean (B − A) lies within ±10 pp |
| H2 | OpenShell's runtime doesn't change success when the policy permits everything the tasks use: C ≈ B | Same | 95% CI of mean (C − B) lies within ±10 pp |
| H3 | On the 7 **non-network** tasks, the strict policy doesn't change success: D ≈ C | Same, restricted to non-network tasks | 95% CI within ±10 pp |
| H4 | On the 3 **network** tasks (git-clone, pip-version, pypi-download), the strict policy *lowers* success: D < C. Expected cause: the agent uses a binary or route the least-privilege policy didn't anticipate (e.g. `curl` where only `python3.12` may reach PyPI; another host; a raw IP) | One-sided paired comparison on the 3 network tasks; plus denial samples from D rows | Mean (C − D) > 0 with the 95% CI excluding 0. *Note: only 3 tasks, so low power; a null result is inconclusive, not evidence of no effect* |
| H5 | Denials during benign tasks are rare in C and concentrated in D's network tasks | Share of runs with ≥1 denial, per setup and task | C < 5% of runs; D network-task share > D non-network share |
| H6 | Wall time per run is dominated by the model, so setup overhead adds < 10% to median wall time | Median (wall − model_s) per setup vs median wall | (C − B) tool-time difference < 10% of B's median wall |

## Analysis rules fixed in advance

- **Errors:** rows with `error` (harness failures, liveness failures, timeouts) are excluded from success rates and **reported separately per setup**. A setup's error rate is itself a reliability result.
- **No reruns based on outcome.** A row is rerun only for a documented harness bug, and every rerun is listed.
- **Multiple comparisons:** H1–H4 are reported with unadjusted CIs and labelled as such. There are four primary comparisons, which is few enough to report all of them.
