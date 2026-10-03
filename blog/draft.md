# What does a sandbox cost an AI agent? Benchmarking NVIDIA OpenShell against a plain shell

*Draft v1, 2026-10-03. Every number comes from `results/`. Figures come from `report/make_figures.py`. Sources are in the reference list at the end.*

---

## 1. Why this matters

Coding agents work by running shell commands. The usual choices are poor ones. You can give the agent your own shell, or you can ask the user to approve every command. Anthropic reports that users approved about 93% of Claude Code's permission prompts, and that people pay less attention the more prompts they see [R2]. Classifier-based approval gates miss risky actions as well: in a stress test of Claude Code's auto mode, the end-to-end false-negative rate was 81% [R8]. Container walls are not airtight either. In SandboxEscapeBench, frontier models escaped deliberately misconfigured containers about half the time [R7].

NVIDIA OpenShell takes a different approach. Instead of asking the agent to behave, it puts the agent's commands in a sandbox governed by a declarative policy. Landlock limits the filesystem, seccomp limits system calls, and a supervisor process outside the sandbox checks every network connection against the policy [R10]. We (Claude & me :P) wanted to know what that costs and what it buys.

`F1`

## 2. What we compared

`F2` (ladder diagram): each setup adds one layer.

| Setup | What the agent's commands run in |
|---|---|
| A · host shell | your machine |
| B · Docker | a plain container |
| C · OpenShell, permissive | OpenShell with the loosest policy it can express |
| D · OpenShell, strict | OpenShell with a least-privilege policy for each task |

Claude Code's own bubblewrap sandbox (`srt`) was planned as a fifth setup. It is set aside for now: on Ubuntu 24.04 and later it needs a kernel hardening setting turned off (`kernel.apparmor_restrict_unprivileged_userns=0`, per `srt`'s own README). That requirement is itself a deployment difference worth knowing about.

One finding came before any measurement. **OpenShell cannot be switched off.** Its policy language has no "allow all network" and no "any program" setting; an empty list of allowed programs means none are allowed. So setup C is the loosest policy we could write: every host our tasks use, no request inspection, programs matched by wildcard paths.

## 3. How we tested

- **Model:** `qwen2.5:3b` served by Ollama on a 4 GB laptop GPU (Quadro T2000). Anyone can reproduce this at no API cost. The price is that absolute success rates are small-model numbers; they say nothing about frontier agents.
- **Agent:** a short bash-only agent loop with identical code in every setup. It runs on the host, and every command executes inside the setup under test (the pattern Harbor and Terminal-Bench use [R5, R6]).
- **Tasks:** 10 short shell tasks, 3 of which need network access. Task format follows Terminal-Bench (instruction, environment, hidden test, reference solution). Graders use expected values fixed when the tasks are generated, never values computed from files the agent can modify.
- **Attacks:** fixed command sequences replayed in every setup with no model involved, so the result reflects the environment rather than the model. Success is detected with fake canary secrets and marker files, following AgentDojo's utility/security framing [R3].
- **Statistics:** 20 trials per task per setup, Wilson intervals, pass^k [R9], comparisons paired per task [R12].

## 4. Result 1: what each layer costs

`F3`, `F4`, `F5`. Medians of three separate sessions, 20+ repetitions each.

- **Per command.** Every command the agent runs pays a round trip: **1.2 ms** on the host, **46.3 ms** through `docker exec`, **56–57 ms** through `openshell sandbox exec`. OpenShell adds about **10–11 ms per command** on top of Docker. Over a whole task that hardly matters: across 800 agent runs, command execution added **0.05 s to a ~4.3 s median run (1.1%)**. The model's thinking time dominates.
- **Under load, the gap grows.** With 16 sandboxes running, Docker's round trip stays at 46.7 ms; OpenShell's rises to **79–81 ms**.
- **Lifecycle.** Starting a sandbox takes **0.74 s** (Docker: 0.30 s). Deleting one takes **5.2 s** (Docker: 0.11 s). That's fine for long agent sessions and noticeable for one sandbox per short task.
- **Policy changes.** A network-policy update on a running sandbox took **10.1 s** to take effect, every time, in every session. If your agent waits on a human to widen a policy, that's ten seconds per round.
- **Inside the sandbox,** CPU work runs within 4% of Docker. git over 20k files is 8–9% slower and HTTPS requests 8–10 ms slower. Checking requests at the HTTP level (strict policy) cost nothing measurable compared with uninspected traffic (permissive policy).

## 5. Result 2: does the agent still get its work done?

`F6`, `F7`, `F8`. 10 tasks × 4 setups × 20 trials = 800 runs, 0 harness errors.

| Setup | Mean task success |
|---|---|
| Docker (B) | 0.51 |
| OpenShell, permissive (C) | 0.55 |
| OpenShell, strict (D) | 0.53 |

We wrote our hypotheses down, with a hash, before analysing a single result (`HYPOTHESES.md`). Against them:

- **OpenShell vs Docker:** +4.5 points (95% CI −6.0 to +15.0). No sign that the sandbox hurts. We had set the bar at proving the difference lies *within ±10 points*, and 200 runs per setup aren't enough to show that.
- **Strict vs permissive, offline tasks:** −5.0 points (CI −16.4 to +5.7). Inconclusive.
- **Strict vs permissive, network tasks:** we predicted the strict policy would *hurt*, because a small model tends to wander (another tool, another mirror). It didn't: the strict setup scored 5 points *higher* (one-sided bound −16.7 for the predicted direction), and the strict policy **really blocked the agent in 0 of 60 network-task runs**. The narrow rules (read-only PyPI for `python3`; two git endpoints for one repository) covered everything this agent did. This is a small model on small tasks; a more inventive agent would hit the walls more often.
- **The host shell can't be compared directly.** It scored 0.62, but its prompt contains a different working-directory path and it runs a different toolchain and locale. A 3B model at a fixed seed is sensitive to both. We report it and don't draw conclusions from it.

## 6. Result 3: what got through

`F9`, `F10`. Nine attacks, each replayed 20 times per setup, with no model involved. These numbers describe the environment, not an AI's intentions.

Read these results as an enforcement check, not a security rating. We wrote both the attacks and the strict policy, knowing each task's needs in advance. So the strict column shows that OpenShell enforces what its policy says, consistently, 20 times out of 20. It doesn't show how well a policy written without that knowledge holds up against an attacker who goes looking for gaps.

- **Host shell and plain Docker: everything got through,** 9 out of 9 attacks, 20/20 every time.
- **Permissive OpenShell blocked one thing: the raw credential.** With a provider attached, the process sees `openshell:resolve:env:…_CANARY_API_TOKEN`, a placeholder that the proxy only swaps for the real token on requests to the declared host and path. Everything else got through, because the policy allowed it.
- **Strict OpenShell blocked 8 of 9, every time:**
  - exfiltration to an unapproved host (refused at connection);
  - reading `~/.ssh` and `rm -rf` outside the workspace (`Permission denied` from Landlock);
  - `curl | sh`;
  - the model server's admin API;
  - the raw credential;
  - a POST to an allowed host whose rules permit only reads (HTTP 403, logged).
- **What it didn't stop: a secret smuggled in a GET query string to an allowed host** (20/20 got through). The secret came from a `.env` file in the workspace, and the policy allowed `python3` to send GET requests to PyPI on any path. Method and path rules don't look at query strings. OpenShell's built-in regex middleware doesn't help here either: per the documentation, it inspects request bodies and WebSocket messages, not URLs.

## 7. Result 4: living with a strict policy

`F11`

- The strict policy really blocked the agent in **1 of 200 benign runs (0.5%)**.
- But the audit log *looked* far busier: **11–33% of runs had a DENIED event**. Almost all were the sandbox looking up its own container hostname, which `git` does to build a default identity. If you alert on denials, filter those first.
- The strict `git clone` policy needed two rules (`GET …/info/refs`, `POST …/git-upload-pack`). Push and every other repository stay denied.

```yaml
# tasks/custom/git-clone/policy.yaml (network part): clone one repository, nothing else
github_clone_hello_world:
  endpoints:
  - host: github.com
    port: 443
    protocol: rest
    enforcement: enforce
    rules:
    - allow: { method: GET,  path: /octocat/Hello-World.git/info/refs }
    - allow: { method: POST, path: /octocat/Hello-World.git/git-upload-pack }
  binaries:
  - path: /usr/bin/git
  - path: /usr/lib/git-core/git-remote-http
```

## 8. Things that surprised us (operational notes)

- **Default-deny out of the box.** With no policy at all, OpenShell blocks all egress and allows writes only to the workspace and `/tmp`.
- **Network denials are logged in detail, filesystem denials are not.** Every refused connection becomes an OCSF event naming the program, the destination and the reason. Blocked file reads and writes leave no log entry; the process just gets `Permission denied`.

```text
[sandbox] [OCSF] NET:OPEN [MED] DENIED /usr/bin/curl(0) -> 172.17.0.1:18080 [reason:transparent_tcp_policy_denied]
[sandbox] [OCSF] NET:REFUSE [MED] DENIED example.com [reason:policy_dns_ineligible]
```
- **The seccomp filter blocks `nice()`.** fio failed for this reason, and so would anything that calls `nice`.
- **The image's `ENV` doesn't reach the sandbox** through `sandbox exec`. Our pip setting worked in Docker and silently disappeared in OpenShell until we moved it into `/etc/pip.conf`.
- **`host.openshell.internal` resolves to loopback,** which OpenShell always blocks. Reaching host services needs an `allowed_ips` rule.
- **Smaller papercuts:** sandbox names are limited to 19 characters; `upload` nests directories differently from `docker cp`; `sandbox exec` occasionally hung until our timeout fired.

## 9. How this compares with other work

None of these are directly comparable: different models, tasks and threat models. They show where this fits.

| Finding | Source | Comparable? |
|---|---|---|
| Users approved ~93% of Claude Code permission prompts | Anthropic [R2] | No. It's the motivation: prompts don't make people careful |
| OS-level sandbox cut permission prompts by 84% | Anthropic [R1] | No. Different metric, but the same idea: move the boundary into the environment |
| Auto-mode classifier missed 81% of risky actions in a stress test | Ji et al. [R8] | No. A classifier gate, not a sandbox |
| Frontier models escaped misconfigured containers ~50% of the time | Marchand et al. [R7] | No. We didn't test escapes; it's why "plain Docker" isn't a security boundary by default |
| Highest average attack success rate across agent attacks: 84.3% | Zhang et al. [R4] | No. It measures model susceptibility; we measure what the environment lets through |
| **This work:** strict OpenShell blocked 8 of 9 replayed attack types (160 of 180 reps) under a policy we wrote knowing the attacks. It missed query-string exfiltration to an allowed host. This is an enforcement check, not a security rating | — | — |

## 10. What we conclude

These conclusions hold for what we measured: a small local model, short shell tasks, one machine, OpenShell 0.1.2. Section 11 says where they could break.

**1. The protection comes from the policy, not from the sandbox.** Run with a loose policy, OpenShell stopped one attack in nine, only one more than plain Docker. Run with a least-privilege policy, it stopped eight of our nine, a policy we wrote with the attacks in front of us. Adopting OpenShell without writing tight policies buys almost nothing beyond credential hiding. Its default with no policy at all is deny-everything, so the easy path is to start strict and open up only what tasks need.

**2. Least privilege was cheaper than we expected.** We predicted the strict policy would trip the agent on network tasks. It didn't: it got in the way in 1 of 200 benign runs, and 0 of 60 network-task runs. Task success under the strict policy was statistically indistinguishable from the permissive one. Two caveats. Our intervals are too wide to rule out a drop of up to about 16 points. And a more capable, more inventive agent will reach for tools and hosts a narrow policy didn't anticipate, so expect more friction with frontier agents.

**3. Per-command overhead is not the cost to worry about.** About 10 ms per command over Docker came to 1.1% of a task's time, because the model's thinking dominates. The costs that matter are elsewhere:
- **Deleting a sandbox:** 5.2 s.
- **Applying a policy change to a running sandbox:** 10 s.
- **Concurrency:** the per-command gap grows to ~33 ms with 16 sandboxes running.

In practice: reuse sandboxes across steps rather than creating one per command, and batch policy changes rather than widening them one denial at a time.

**4. Hold credentials in providers, and keep secrets out of the workspace.** Providers were the one protection that worked even under the loose policy. The process only ever saw a placeholder; the real token was added in the proxy, on the way to the one host allowed to receive it. But a provider protects only the credentials it holds. The secret that leaked in our test sat in a `.env` file in the workspace, where the agent could read it like any other file. Move such secrets into providers, or keep them out of the sandbox entirely. We didn't test whether an allowed host that echoes request headers back could reveal the real token; treat that as an open question.

**5. An allowed host is still an exit.** A secret placed in a GET query to PyPI went out 20 times out of 20 under the strict policy, because method and path rules don't read query strings. Network policy narrows *where* data can go, not *what* goes there. The built-in regex middleware inspects request bodies and WebSocket messages, not URLs, so it wouldn't have caught this. What does help:
- keep secrets unreadable to the agent (point 4);
- scope allowed paths as tightly as the tool allows (for pip, the package index and file-download paths, not the whole host);
- route the hosts that matter through an inspection layer of your own that sees full URLs.

**6. Plan for integration and observability work.** None of these is a blocker, but together they're real effort:
- The image's `ENV` isn't passed into the sandbox.
- seccomp blocks `nice()`.
- Sandbox names are capped at 19 characters.
- `upload` behaves differently from `docker cp`.
- `exec` occasionally hangs.

On observability:
- Most logged denials were the sandbox resolving its own hostname, so filter those before you alert.
- Blocked file access isn't logged at all, so if you need to see filesystem attempts you'll need another source.

**Bottom line.** For an agent that holds credentials or can reach the network, a default Docker container isn't a security boundary: it let every attack through. A hardened container would have stopped some of them; we didn't test one. Strict OpenShell reliably enforced a least-privilege policy, blocking eight of our nine attack types, at a cost we could barely measure in task time. The value is in the policy you write and in keeping secrets out of the agent's reach. Budget for lifecycle latency and the operational rough edges of alpha software.

## 11. Limitations

- A 3B model on easy tasks; one machine; OpenShell 0.1.2 is alpha software.
- The agent runs on the host, so the per-command round trip is part of the cost. An agent running inside the sandbox would pay it differently.
- The host's toolchain differs from the container image's, so host workload timings are reported for lifecycle and network only.
- Replayed attacks measure the environment, not whether a model would attempt the attack.

## 12. Reproduce it

Everything is in the repository, [github.com/kumiDa/openshell-benchmarking](https://github.com/kumiDa/openshell-benchmarking): `README.md` has the commands, `HYPOTHESES.md` the hypotheses we wrote down before analysing any task-success results, and `results/` the raw rows behind every figure.

## References

See `BENCHMARK_DESIGN.md` §12. Every borrowed number is listed in §1.2 with its verification status.
