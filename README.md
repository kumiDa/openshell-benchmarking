# OpenShell vs a plain shell for coding agents — benchmark

This benchmark measures what NVIDIA OpenShell sandboxes cost and what they buy, compared with a plain shell, for a coding agent's commands. It covers four things:
- **overhead** (micro-benchmarks),
- **task success** (an agent with a local model),
- **attack containment** (replayed attack commands),
- **policy-authoring friction**.

Repository: https://github.com/kumiDa/openshell-benchmarking

Report (GitHub Pages): https://kumida.github.io/openshell-benchmarking/ (built into `docs/` by `blog/build_page.py`)

Design, findings log and references: [`BENCHMARK_DESIGN.md`](BENCHMARK_DESIGN.md). Preregistered hypotheses: [`HYPOTHESES.md`](HYPOTHESES.md) (SHA-256 in `HYPOTHESES.sha256`). Blog draft: [`blog/draft.md`](blog/draft.md).

## Setups

| ID | Environment | Back-end |
|---|---|---|
| A | host shell (per-run `HOME`) | `HostArm` |
| A2 | Anthropic sandbox-runtime (`srt`, bubblewrap): *deferred, needs `kernel.apparmor_restrict_unprivileged_userns=0` on Ubuntu 24.04+* | `SrtArm` |
| B | plain Docker container | `DockerArm` |
| C | OpenShell, loosest expressible policy (`policies/open.yaml`) | `OpenShellArm` |
| D | OpenShell, least-privilege per-task policy (`tasks/custom/<task>/policy.yaml`) | `OpenShellArm` |

## Requirements

- Linux with Docker ≥ 28 and an NVIDIA GPU with ≥ 4 GB (tested on a Quadro T2000).
- OpenShell 0.1.2 (`install.sh` from the NVIDIA/OpenShell repo; needs sudo for the `.deb`). Gateway at `https://127.0.0.1:17670`.
- Ollama serving `qwen2.5:3b` on `:11434`.
- Python 3 with PyYAML. Report scripts use a separate venv: `python3 -m venv .venv-report && .venv-report/bin/pip install matplotlib numpy`.
- `ripgrep`, `hyperfine`, `fio`: project-local in `.tools/` via `conda create -p .tools -c conda-forge ripgrep hyperfine fio`, exposed through `.tools/shim/`.

## Build and generate

```bash
docker build -t bench-img:latest -f images/bench.Dockerfile images/
docker build -t bench-img-attack:latest -f images/attack.Dockerfile \
  --build-arg S3_TOKEN=$(jq -r .S3 canaries/tokens.json) --build-arg S4_TOKEN=$(jq -r .S4 canaries/tokens.json) images/
python3 tasks/make_short_tasks.py          # tasks + hidden graders (expected values baked in)
python3 policies/make_policies.py          # open.yaml, micro-strict.yaml, per-task strict policies
openshell profile import -f policies/canary-api-profile.yaml
CANARY_API_TOKEN=$(jq -r .S2 canaries/tokens.json) openshell provider create --name bench-canary --type canary-api --credential CANARY_API_TOKEN
```

## Run

```bash
# Sanity anchor: reference solution passes and grader rejects unsolved work, per task and setup
python3 runner/run_one.py --task pip-version --arm D --mode reference

# Track 1: micro-benchmarks (don't run while the model is generating)
python3 micro/run_micro.py --arm C --reps 20

# Track 3: replayed attacks (no model)
python3 runner/replay.py --arms A,B,C,D --reps 20 --run-id replay-main-v1

# Track 2: task-success matrix (seeded random order, resumable)
python3 runner/run_matrix.py --arms A,B,C,D --trials 20 --run-id main-utility-v1

# Everything unattended:
setsid nohup runner/run_main.sh > results/logs/main.log 2>&1 &
```

## Analyse

```bash
.venv-report/bin/python report/analyze.py          # preregistered hypotheses H1–H6
python3 report/micro_table.py                      # merged micro-benchmark table
.venv-report/bin/python report/make_figures.py     # report/figures/{light,dark}/F*.{svg,png}
```

## Layout

```
runner/   agent.py (lean bash agent), arms.py (setups), run_one.py, run_matrix.py, replay.py,
          canary_listener.py, run_main.sh, run_after.sh
micro/    run_micro.py (M1–M12)
tasks/    make_short_tasks.py, suite.json, custom/<task>/, appendix/
policies/ make_policies.py, open.yaml, micro-strict.yaml, canary-api-profile.yaml
images/   bench.Dockerfile, attack.Dockerfile
canaries/ tokens.json (fake values)
results/  raw/ (task rows + traces), replay/, micro/, logs/
report/   analyze.py, make_figures.py, micro_table.py, figures/
blog/     draft.md
```

## Safety

Canary values in `canaries/tokens.json` are fake and exist only to detect leaks. Raw result rows and traces contain the original host paths from the test machine.

Attack payloads are fixed and harmless by construction. They target planted **fake** canaries, the run's own directory, a local listener, Ollama's read-only model list, `example.com` (an IANA test domain) and two harmless requests to PyPI. Nothing reads real credentials or touches files outside the run directories.

## License

MIT, see [`LICENSE`](LICENSE).
