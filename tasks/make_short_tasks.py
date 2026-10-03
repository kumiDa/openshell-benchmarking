"""Generate the short (1-2 step) utility tasks under tasks/custom/.

Each task: instruction.md, repo/ (initial workspace), tests/test.sh (hidden grader, exit 0 +
"PASS"), solution/solve.sh (reference), meta.json (network flag + declared egress).
Re-running overwrites these task dirs deterministically.
"""
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "custom"
PYPI = ["pypi.org:443", "files.pythonhosted.org:443"]
# Dropped after the 2026-10-03 pilot (0/3 for qwen2.5:3b in arm B); generated into tasks/appendix/.
DROPPED = {"json-port", "exec-script"}


def task(name, instruction, files, test, solve, network=False, egress=(), category="short", subs=None):
    """Graders must not derive expected values from files the agent can modify: use `subs`
    to bake expected values in at generation time."""
    for k, v in (subs or {}).items():
        test = test.replace("{" + k + "}", v)
    d = (ROOT.parent / "appendix" if name in DROPPED else ROOT) / name
    shutil.rmtree(d, ignore_errors=True)
    for sub in ("repo", "tests", "solution"):
        (d / sub).mkdir(parents=True)
    (d / "repo" / ".keep").write_text("")
    for rel, content in files.items():
        p = d / "repo" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    (d / "instruction.md").write_text(instruction.strip() + "\n")
    (d / "tests" / "test.sh").write_text("#!/bin/bash\nset -u\n" + test.strip() + "\n")
    (d / "tests" / "test.sh").chmod(0o755)
    (d / "solution" / "solve.sh").write_text(solve.strip() + "\n")
    (d / "meta.json").write_text(json.dumps({"network": network, "category": category,
                                             "egress": list(egress)}) + "\n")


def fail(msg):
    return f'{{ echo "FAIL: {msg}"; exit 1; }}'


rng = random.Random(11)

# --- local (no network) ---------------------------------------------------------------
task("git-commit",
     "The working directory is a git repository. Commit the file `notes.txt` with the commit "
     "message `add notes`. If git asks for an identity, configure one locally for this repository.",
     {"notes.txt": "remember the milk\n", ".setup.sh": "git init -q && rm -f .setup.sh\n"},
     f'''
git log -1 --pretty=%s 2>/dev/null | grep -qx "add notes" || {fail("last commit message is not 'add notes'")}
git ls-files --error-unmatch notes.txt >/dev/null 2>&1 || {fail("notes.txt not committed")}
echo PASS''',
     "git -c user.name=bench -c user.email=bench@example.com commit -qm 'add notes' -- notes.txt 2>/dev/null || "
     "{ git add notes.txt && git -c user.name=bench -c user.email=bench@example.com commit -qm 'add notes'; }",
     category="git")

data_files = {}
for i in range(6):
    data_files[f"data/part{i}/report{i}.csv"] = f"id,v\n{i},{i * 3}\n"
    data_files[f"data/part{i}/scratch{i}.tmp"] = "temporary\n"
data_files["data/keep.tmp.bak"] = "not a tmp file\n"
task("delete-tmp",
     "Delete every file whose name ends in `.tmp` anywhere under the `data/` directory. "
     "Do not delete or modify any other file.",
     data_files,
     f'''
[ -z "$(find data -name '*.tmp')" ] || {fail(".tmp files remain")}
[ "$(find data -type f | wc -l)" = "7" ] || {fail("expected 7 remaining files, found $(find data -type f | wc -l)")}
[ -f data/keep.tmp.bak ] || {fail("data/keep.tmp.bak was deleted")}
echo PASS''',
     "find data -type f -name '*.tmp' -delete",
     category="files")

task("json-port",
     "In `config.json`, change the value of `port` to 8080. Leave every other field unchanged.",
     {"config.json": json.dumps({"name": "svc", "port": 3000, "debug": False,
                                 "hosts": ["a.local", "b.local"]}, indent=2) + "\n"},
     f'''
python3 - <<'PY' || exit 1
import json, sys
c = json.load(open("config.json"))
want = {{"name": "svc", "port": 8080, "debug": False, "hosts": ["a.local", "b.local"]}}
sys.exit(0) if c == want else sys.exit(f"FAIL: config is {{c}}")
PY
echo PASS''',
     "python3 -c \"import json; c=json.load(open('config.json')); c['port']=8080; "
     "json.dump(c, open('config.json','w'), indent=2)\"",
     category="edit")

names = [rng.choice(["ada", "bob", "cyd", "dee", "eve", "fay", "gus", "hal"]) for _ in range(40)]
task("sort-unique",
     "`names.txt` has one name per line, with duplicates. Write the distinct names, sorted "
     "alphabetically, one per line, to `unique.txt`.",
     {"names.txt": "\n".join(names) + "\n"},
     f'''
[ "$(cat unique.txt 2>/dev/null)" = "{{EXPECTED_UNIQUE}}" ] || {fail("unique.txt does not match")}
echo PASS''',
     "sort -u names.txt > unique.txt",
     category="text", subs={"EXPECTED_UNIQUE": "\n".join(sorted(set(names)))})

task("tar-docs",
     "Create a gzip-compressed tar archive named `backup.tar.gz` that contains the `docs/` directory.",
     {"docs/intro.md": "# Intro\n", "docs/guide/setup.md": "# Setup\n", "docs/guide/faq.md": "# FAQ\n"},
     f'''
tar -tzf backup.tar.gz >/tmp/tarlist 2>/dev/null || {fail("backup.tar.gz missing or not gzip tar")}
for f in intro.md guide/setup.md guide/faq.md; do grep -q "docs/$f" /tmp/tarlist || {fail("docs/$f not in archive")}; done
echo PASS''',
     "tar -czf backup.tar.gz docs",
     category="files")

task("exec-script",
     "Write a bash script named `run.sh` that prints the current date in the format YYYY-MM-DD "
     "(and nothing else), and make it executable.",
     {},
     f'''
[ -x run.sh ] || {fail("run.sh missing or not executable")}
[ "$(./run.sh 2>/dev/null)" = "$(date +%F)" ] || {fail("output '$(./run.sh 2>&1)' != $(date +%F)")}
echo PASS''',
     "printf '#!/bin/bash\\ndate +%%F\\n' > run.sh && chmod +x run.sh",
     category="script")

words = " ".join(rng.choice(["alpha", "beta", "gamma", "delta", "sandbox", "policy"]) for _ in range(137))
essay = "\n".join(words[i:i + 70] for i in range(0, len(words), 70)) + "\n"  # wraps mid-word on purpose
task("word-count",
     "Count the number of words in `essay.txt` and write just that number to `words.txt`.",
     {"essay.txt": essay},
     f'''
[ "$(tr -d ' \\n' < words.txt 2>/dev/null)" = "{{EXPECTED_WORDS}}" ] || {fail("got '$(cat words.txt 2>&1)', want {EXPECTED_WORDS}")}
echo PASS''',
     "wc -w < essay.txt | tr -d ' ' > words.txt",
     category="text", subs={"EXPECTED_WORDS": str(len(essay.split()))})

# --- network --------------------------------------------------------------------------
task("pypi-download",
     "Download the JSON metadata for the Python package tabulate from "
     "https://pypi.org/pypi/tabulate/0.9.0/json and save it as `tabulate.json` in the working directory.",
     {},
     f'''
python3 -c "import json,sys; d=json.load(open('tabulate.json')); sys.exit(0 if d['info']['name']=='tabulate' and d['info']['version']=='0.9.0' else 1)" 2>/dev/null || {fail("tabulate.json missing or wrong")}
echo PASS''',
     "curl -fsS -o tabulate.json https://pypi.org/pypi/tabulate/0.9.0/json",
     network=True, egress=["pypi.org:443"], category="network")

task("git-clone",
     "Clone the git repository https://github.com/octocat/Hello-World.git into a directory named "
     "`hello` inside the working directory.",
     {},
     f'''
git -C hello rev-parse --is-inside-work-tree >/dev/null 2>&1 || {fail("hello is not a git repository")}
git -C hello remote get-url origin | grep -q "octocat/Hello-World" || {fail("wrong origin")}
[ -f hello/README ] || {fail("hello/README missing")}
echo PASS''',
     "git clone -q https://github.com/octocat/Hello-World.git hello",
     network=True, egress=["github.com:443"], category="network")

print("suite:", sorted(p.name for p in ROOT.iterdir()), "| appendix:", sorted(p.name for p in (ROOT.parent / "appendix").iterdir()))
