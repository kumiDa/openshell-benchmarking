"""Shell-environment backends (arms). Common interface:

    arm = make_arm("B", name="t1-B-0")
    arm.setup(repo_dir)              # fresh environment with repo copied to arm.workdir
    rc, output, seconds = arm.exec("ls -la", timeout=60)
    arm.upload(local_dir, remote_dir)
    arm.teardown()

A  host       local bash in a per-run directory (perf baseline; never adversarial)
A2 srt        local bash wrapped in Anthropic sandbox-runtime (bubblewrap + proxy)
B  docker     plain container, unrestricted
C  openshell  OpenShell sandbox, permissive policy
D  openshell  OpenShell sandbox, strict per-task policy
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = os.environ.get("BENCH_IMAGE", "bench-img:latest")
CPUS, MEMORY_GB = 4, 8
REMOTE_WORKDIR = "/sandbox/workspace"
# Project-local tools (rg for srt, hyperfine, fio) via a shim dir so nothing else gets shadowed.
os.environ["PATH"] = f"{ROOT / '.tools' / 'shim'}:{os.environ['PATH']}"


def _run(argv, timeout=None, input_text=None):
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input_text)
        rc, out = p.returncode, p.stdout + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
    except subprocess.TimeoutExpired as e:
        rc = 124
        out = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
        out += f"\n[timeout after {timeout}s]"
    return rc, out, time.monotonic() - t0


class Arm:
    arm_id = "?"
    workdir = REMOTE_WORKDIR
    host_alias = "127.0.0.1"          # how commands in this arm address services on the host
    sentinel_dir = "/sandbox/sentinel"  # attack-image canary dir outside the workspace (S4)
    home_dir = "/home/ubuntu"           # $HOME inside the arm (S3 canary lives in $HOME/.ssh)
    # S2: how a credential reaches the environment. Plain arms get the raw value as an env var (what
    # people do today); OpenShell arms get it through a provider, which exposes only a placeholder.
    secret_env = {}
    providers = []

    def __init__(self, name):
        self.name = name

    def setup(self, repo_dir): raise NotImplementedError
    def _wrap(self, command): raise NotImplementedError

    def argv(self, command):
        """Host-side argv that runs `command` in this arm (used by hyperfine for M3)."""
        return self._wrap(command)

    def exec(self, command, timeout=180): raise NotImplementedError
    def upload(self, local_dir, remote_dir): raise NotImplementedError
    def teardown(self): pass

    def versions(self):
        return {}


class HostArm(Arm):
    arm_id = "A"

    def setup(self, repo_dir):
        self.base = ROOT / "runs" / "host" / self.name
        shutil.rmtree(self.base, ignore_errors=True)
        self.workdir = str(self.base / "workspace")
        shutil.copytree(repo_dir, self.workdir)
        (self.base / "home").mkdir()
        self.home_dir = str(self.base / "home")
        self.sentinel_dir = str(self.base / "sentinel")
        return self

    def _inner(self, command):
        # Per-run HOME and pip user base so `pip install --user` etc. never touch the real home.
        b = shlex.quote(str(self.base))
        secrets = "".join(f"export {k}={shlex.quote(v)}; " for k, v in self.secret_env.items())
        return (secrets + f"export HOME={b}/home PYTHONUSERBASE={b}/home/.local; "
                f"cd {shlex.quote(self.workdir)} && {command}")

    def _wrap(self, command):
        return ["bash", "-c", self._inner(command)]

    def exec(self, command, timeout=180):
        return _run(self._wrap(command), timeout=timeout)

    def upload(self, local_dir, remote_dir):
        shutil.copytree(local_dir, remote_dir, dirs_exist_ok=True)

    def teardown(self):
        shutil.rmtree(self.base, ignore_errors=True)


class SrtArm(HostArm):
    """Anthropic sandbox-runtime (bubblewrap + proxy), configured to mirror arm D's strict scope:
    writes only inside the run directory, credential dirs unreadable, egress only to the task's
    declared hosts."""
    arm_id = "A2"
    DENY_READ = ["~/.ssh", "~/.aws", "~/.gnupg", "~/.config", "~/.docker", "~/.kube", "~/.netrc"]

    def __init__(self, name, task_dir=None):
        super().__init__(name)
        self.task_dir = Path(task_dir) if task_dir else None

    def setup(self, repo_dir):
        super().setup(repo_dir)
        egress = []
        if self.task_dir and (self.task_dir / "meta.json").exists():
            egress = json.loads((self.task_dir / "meta.json").read_text()).get("egress", [])
        self.settings = self.base / "srt-settings.json"
        self.settings.write_text(json.dumps({
            "filesystem": {"denyRead": self.DENY_READ + [str(self.base / "home" / ".ssh")],
                           "allowWrite": [self.workdir, str(self.base / "home"), "/tmp"], "denyWrite": [
                               str(self.base / "home" / ".ssh")]},
            "network": {"allowedDomains": sorted({h.split(":")[0] for h in egress}), "deniedDomains": []},
        }, indent=1))
        return self

    def _wrap(self, command):
        return ["srt", "--settings", str(self.settings), "-c", self._inner(command)]

    def versions(self):
        return {"srt": _run(["srt", "--version"])[1].strip()}


class DockerArm(Arm):
    arm_id = "B"
    host_alias = "host.docker.internal"

    def __init__(self, name, image=IMAGE):
        super().__init__(name)
        self.image = image

    def setup(self, repo_dir):
        _run(["docker", "rm", "-f", self.name])
        rc, out, _ = _run(["docker", "run", "-d", "--name", self.name, f"--cpus={CPUS}",
                           f"--memory={MEMORY_GB}g", "--add-host=host.docker.internal:host-gateway",
                           *[f"--env={k}={v}" for k, v in self.secret_env.items()],
                           self.image, "sleep", "infinity"])
        if rc != 0:
            raise RuntimeError(f"docker run failed: {out}")
        self.upload(repo_dir, self.workdir)
        return self

    def _wrap(self, command):
        return ["docker", "exec", "-w", self.workdir, self.name, "bash", "-c", command]

    def exec(self, command, timeout=180):
        return _run(self._wrap(command), timeout=timeout)

    def upload(self, local_dir, remote_dir):
        _run(["docker", "exec", self.name, "mkdir", "-p", remote_dir])
        rc, out, _ = _run(["docker", "cp", f"{local_dir}/.", f"{self.name}:{remote_dir}"])
        if rc != 0:
            raise RuntimeError(f"docker cp failed: {out}")
        # docker cp writes as root; hand ownership to the image's non-root user
        _run(["docker", "exec", "-u", "0", self.name, "chown", "-R", "1000:1000", remote_dir])

    def teardown(self):
        _run(["docker", "rm", "-f", self.name])

    def versions(self):
        return {"docker": _run(["docker", "version", "--format", "{{.Server.Version}}"])[1].strip()}


class OpenShellArm(Arm):
    # host.openshell.internal resolves to 127.0.0.1 at the supervisor and loopback upstreams are always
    # blocked, so host services are addressed by the docker0 IP (allowed only in policies/open.yaml).
    host_alias = "172.17.0.1"

    def __init__(self, name, arm_id, policy, image=IMAGE):
        super().__init__(name)
        self.arm_id, self.policy, self.image = arm_id, policy, image
        # OpenShell 0.1.2 limits sandbox names to 19 chars: use a stable short hash of the run name.
        self.sbx = f"os{arm_id.lower()}-" + hashlib.sha1(name.encode()).hexdigest()[:12]

    def setup(self, repo_dir):
        _run(["openshell", "sandbox", "delete", self.sbx])
        argv = ["openshell", "sandbox", "create", "--name", self.sbx, "--from", self.image,
                "--cpu", str(CPUS), "--memory", f"{MEMORY_GB}Gi", "--detach", "--no-auto-providers"]
        if self.policy:
            argv += ["--policy", str(self.policy)]
        for p in self.providers:
            argv += ["--provider", p]
        rc, out, _ = _run(argv, timeout=600)
        if rc != 0:
            raise RuntimeError(f"openshell sandbox create failed: {out}")
        self.upload(repo_dir, self.workdir)
        return self

    def _wrap(self, command):
        return ["openshell", "sandbox", "exec", "--name", self.sbx, "--workdir", self.workdir,
                "--no-tty", "--no-login-shell", "--", "bash", "-c", command]

    def exec(self, command, timeout=180):
        rc, out, dt = _run(self._wrap(command), timeout=timeout)
        if rc == 74:  # output delivery failure, not the command's own exit status
            out += "\n[harness: openshell exec output delivery failed (exit 74)]"
        return rc, out, dt

    def upload(self, local_dir, remote_dir):
        # `upload X DEST` always lands at DEST/<basename X> and merges into an existing directory of
        # that name, so stage the contents under the destination's basename and upload to its parent.
        remote = Path(remote_dir)
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / remote.name
            shutil.copytree(local_dir, stage, symlinks=True)
            rc, out, _ = _run(["openshell", "sandbox", "upload", self.sbx, str(stage), str(remote.parent),
                               "--no-git-ignore"], timeout=300)
        if rc != 0:
            raise RuntimeError(f"openshell upload failed: {out}")

    def teardown(self):
        _run(["openshell", "sandbox", "delete", self.sbx], timeout=300)

    def denials(self):
        """DENIED policy events logged for this sandbox (Track 3/4 metric)."""
        _, out, _ = _run(["openshell", "logs", self.sbx, "--source", "sandbox"], timeout=60)
        return [line for line in out.splitlines() if "DENIED" in line]

    def versions(self):
        return {"openshell": _run(["openshell", "--version"])[1].strip()}


def make_arm(arm_id, name, task_dir=None, image=IMAGE):
    if arm_id == "A":
        return HostArm(name)
    if arm_id == "A2":
        return SrtArm(name, task_dir)
    if arm_id == "B":
        return DockerArm(name, image)
    if arm_id == "C":
        return OpenShellArm(name, "C", ROOT / "policies" / "open.yaml", image)
    if arm_id == "D":
        strict = Path(task_dir) / "policy.yaml" if task_dir else None
        if not strict or not strict.exists():
            raise FileNotFoundError(f"arm D needs a strict policy at {strict}")
        return OpenShellArm(name, "D", strict, image)
    raise ValueError(f"unknown arm {arm_id}")
