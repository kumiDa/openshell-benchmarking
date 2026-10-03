"""Generate OpenShell policies for arms C (permissive) and D (strict, per task).

  python3 policies/make_policies.py

Arm C — policies/open.yaml: the loosest policy OpenShell's model allows. OpenShell has no
"allow all egress" and no "any binary" (schema: an empty binaries list matches none), so
"permissive" = every host any task or attack uses, L4 only (no method/path inspection),
binary globs over the system bin dirs, and a broad filesystem.

Arm D — tasks/custom/<task>/policy.yaml: least privilege. Workspace + /tmp writable, system
dirs read-only, $HOME and everything else inaccessible; egress only to the task's declared
hosts, L7-inspected (`protocol: rest`) with read-only presets or exact rules, bound to the
specific binaries that need them. Tasks without network get no network_policies at all.
"""
import json
from pathlib import Path

import yaml


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def dump(obj):
    return yaml.dump(obj, Dumper=_NoAliasDumper, sort_keys=False)

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks" / "custom"
HOST_BRIDGE = "172.17.0.1/32"  # docker0: canary listener (18080) and Ollama (11434) on the host

SYSTEM_RO = ["/bin", "/usr", "/lib", "/proc", "/dev/urandom", "/etc", "/var/log"]
PY = [{"path": "/usr/bin/python3.12"}]
CURL = [{"path": "/usr/bin/curl"}]
GIT = [{"path": "/usr/bin/git"}, {"path": "/usr/lib/git-core/git-remote-http"}]

# Exact L7 scope per network task (D). Hosts must match the task's meta.json egress list.
STRICT_NETWORK = {
    "pip-version": {
        "pypi_readonly": {
            "endpoints": [
                {"host": "pypi.org", "port": 443, "protocol": "rest", "enforcement": "enforce", "access": "read-only"},
                {"host": "files.pythonhosted.org", "port": 443, "protocol": "rest", "enforcement": "enforce",
                 "access": "read-only"},
            ],
            "binaries": PY,
        },
    },
    "pip-tabulate": "pip-version",
    "pypi-download": {
        "pypi_tabulate_metadata": {
            "endpoints": [{"host": "pypi.org", "port": 443, "protocol": "rest", "enforcement": "enforce",
                           "rules": [{"allow": {"method": "GET", "path": "/pypi/tabulate/**"}}]}],
            "binaries": CURL + PY,
        },
    },
    "git-clone": {
        "github_clone_hello_world": {
            # Smart-HTTP clone = GET info/refs + POST git-upload-pack; push (receive-pack) stays denied.
            "endpoints": [{"host": "github.com", "port": 443, "protocol": "rest", "enforcement": "enforce",
                           "rules": [
                               {"allow": {"method": "GET", "path": "/octocat/Hello-World.git/info/refs"}},
                               {"allow": {"method": "POST", "path": "/octocat/Hello-World.git/git-upload-pack"}},
                           ]}],
            "binaries": GIT,
        },
    },
}


def strict_policy(task):
    net = STRICT_NETWORK.get(task, {})
    if isinstance(net, str):
        net = STRICT_NETWORK[net]
    policy = {
        "version": 1,
        "filesystem_policy": {"include_workdir": True, "read_only": SYSTEM_RO, "read_write": ["/tmp", "/dev/null"]},
        "landlock": {"compatibility": "best_effort"},
    }
    if net:
        policy["network_policies"] = {k: {"name": k, **v} for k, v in net.items()}
    return policy


def open_policy():
    any_bin = [{"path": "/usr/bin/*"}, {"path": "/usr/local/bin/*"}, {"path": "/usr/lib/git-core/*"},
               {"path": "/bin/*"}]
    hosts = sorted({h.split(":")[0] for t in TASKS.iterdir() if (t / "meta.json").exists()
                    for h in json.loads((t / "meta.json").read_text()).get("egress", [])} | {"example.com"})
    return {
        "version": 1,
        "filesystem_policy": {
            "include_workdir": True,
            "read_only": ["/"],
            "read_write": ["/tmp", "/dev/null", "/home", "/sandbox"],
        },
        "landlock": {"compatibility": "best_effort"},
        "network_policies": {
            "all_task_hosts_l4": {"name": "all_task_hosts_l4",
                                  "endpoints": [{"host": h, "port": p} for h in hosts for p in (80, 443)],
                                  "binaries": any_bin},
            "host_services_l4": {"name": "host_services_l4",
                                 "endpoints": [{"port": 18080, "allowed_ips": [HOST_BRIDGE]},
                                               {"port": 11434, "allowed_ips": [HOST_BRIDGE]}],
                                 "binaries": any_bin},
        },
    }


def micro_strict_policy():
    """Arm D for micro-benchmarks: D's filesystem scope (+ readable /dev/zero) and L7-inspected,
    read-only PyPI for curl and python, so M7/M8 measure inspection cost rather than a denial."""
    p = strict_policy("none")
    p["filesystem_policy"]["read_only"] = SYSTEM_RO + ["/dev/zero"]
    ep = lambda h: {"host": h, "port": 443, "protocol": "rest", "enforcement": "enforce", "access": "read-only"}
    p["network_policies"] = {"pypi_readonly": {"name": "pypi_readonly",
                                               "endpoints": [ep("pypi.org"), ep("files.pythonhosted.org")],
                                               "binaries": CURL + PY}}
    return p


def main():
    header = "# Generated by policies/make_policies.py — do not edit by hand.\n"
    (ROOT / "policies" / "open.yaml").write_text(header + dump(open_policy()))
    (ROOT / "policies" / "micro-strict.yaml").write_text(header + dump(micro_strict_policy()))
    for t in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        meta = json.loads((t / "meta.json").read_text())
        if meta.get("network") and t.name not in STRICT_NETWORK:
            raise SystemExit(f"{t.name}: network task without a strict L7 scope in STRICT_NETWORK")
        (t / "policy.yaml").write_text(header + dump(strict_policy(t.name)))
    print("wrote policies/open.yaml and", len(list(TASKS.glob("*/policy.yaml"))), "strict task policies")


if __name__ == "__main__":
    main()
