"""Build the publishable blog page from blog/draft.md + report/figures.

  .venv-report/bin/python blog/build_page.py   ->  blog/page/index.html + blog/page/figures/{light,dark}/*.png

Figure markers in the draft (`F3`, `F4`, ...) become <figure> blocks with light and dark images that
follow the reader's theme. [R#] citations link to the reference list, built from BENCHMARK_DESIGN.md §12.
"""
import html
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "blog" / "page"
FIGS = ROOT / "report" / "figures"

FIGURES = {
    "F3": ("F3_lifecycle_costs", "What each layer costs per command and per sandbox",
           "Bar chart in three panels: per-command round trip, sandbox start time and teardown time for host, "
           "Docker, permissive OpenShell and strict OpenShell. Round trip is about 1, 49, 60 and 57 ms; start "
           "about 2, 329, 772 and 753 ms; teardown about 0, 114, 5,196 and 5,214 ms."),
    "F4": ("F4_roundtrip_ecdf", "Every agent command pays the round trip",
           "Cumulative distribution of command round-trip time on a log scale. The host curve sits near 1 ms; "
           "Docker near 46 to 50 ms; both OpenShell setups near 55 to 65 ms."),
    "F5": ("F5_workload_relative", "Workload time inside OpenShell, relative to plain Docker",
           "Dot plot of eight workloads, each as a ratio to Docker. Most sit between 0.93 and 1.05; git over "
           "20,000 files and HTTPS requests to PyPI sit higher, around 1.08 to 1.19."),
    "F6": ("F6_task_success", "Task success per task and setup",
           "Dot plot with 95% intervals for ten tasks and four setups. Intervals overlap heavily for Docker and "
           "both OpenShell setups on every task; write-greeting and git-clone are near 100% everywhere."),
    "F7": ("F7_pass_k", "Reliability across repeated trials (pass^k)",
           "Line chart of pass^k from k=1 to 10 for four setups. All start between 0.5 and 0.62 and fall to "
           "between 0.16 and 0.25 at k=10; the OpenShell lines sit slightly above Docker."),
    "F8": ("F8_time_vs_success", "Time vs success, per setup",
           "Scatter of median seconds per task against success rate. Docker and both OpenShell setups cluster "
           "at 4.1 to 4.4 seconds and 0.50 to 0.55 success; the host sits at about 6 seconds and 0.62."),
    "F9": ("F9_attack_heatmap", "What got through",
           "Grid of nine attacks by four setups. Host, Docker and permissive OpenShell let every attack through "
           "20 out of 20 times, except that permissive OpenShell blocks reading the raw credential. Strict "
           "OpenShell blocks eight of nine; the secret in a GET query to an allowed host gets through."),
    "F10": ("F10_utility_vs_security", "Utility vs security",
            "Scatter of task success against share of attacks blocked. Strict OpenShell sits near 0.89 blocked "
            "at about 0.53 success; the other setups sit near zero blocked at 0.50 to 0.62 success."),
    "F11": ("F11_denials_friction", "Logged denials are mostly noise",
            "Paired bars for permissive and strict OpenShell on offline and network tasks. Any logged denial: "
            "10% to 33% of runs. Real denials, after removing the sandbox's own hostname lookups: 0% to 3.3%."),
}


SVG_FIGURES = {
    "F1": "How one agent command runs in OpenShell. The agent and model stay on the host; the command crosses "
          "the gateway into the sandbox, and every connection it makes is checked by the supervisor proxy.",
    "F2": "The four setups. Each adds one layer; below each, the measured per-command cost and how many of the "
          "nine replayed attack types it blocked.",
}


def references():
    design = (ROOT / "BENCHMARK_DESIGN.md").read_text()
    sect = design[design.index("## 12. References"):]
    items = []
    for line in sect.splitlines():
        m = re.match(r"- \*\*\[R(\d+)\]\*\* (.*)", line)
        if m:
            items.append((m.group(1), m.group(2)))
    md = "\n".join(f"- <span id=\"r{n}\" class=\"refid\">[R{n}]</span> {text}" for n, text in items)
    return markdown.markdown(md)


def preprocess(md):
    out = []
    for line in md.splitlines():
        ids = re.findall(r"`(F\d+|T\d+)`", line)
        if ids and re.match(r"^(`(F\d+|T\d+)`[,.]?\s*)+", line):
            rest = re.sub(r"^(`(F\d+|T\d+)`[,.]?\s*)+(\([^)]*\)\s*)?:?\s*", "", line).strip()
            rest = rest[0].upper() + rest[1:] if rest else rest
            # strip leading connective text like ": our headline numbers..." for table markers
            if rest:
                out.append(rest)
                out.append("")
            for i in ids:
                if i in FIGURES or i in SVG_FIGURES:
                    out += [f"[[FIG:{i}]]", ""]  # each marker its own paragraph
        else:
            out.append(line)
    return "\n".join(out)


def figure_html(fid):
    if fid in SVG_FIGURES:
        svg = (ROOT / "blog" / "diagrams" / f"{fid}.svg").read_text().strip()
        return (f'<figure class="fig diagram" id="{fid.lower()}">{svg}'
                f'<figcaption><span class="fignum">{fid}</span> {html.escape(SVG_FIGURES[fid])}</figcaption></figure>')
    stem, cap, alt = FIGURES[fid]
    a = html.escape(alt, quote=True)
    return (f'<figure class="fig" id="{fid.lower()}">'
            f'<img class="fig-light" src="figures/light/{stem}.png" alt="{a}" loading="lazy">'
            f'<img class="fig-dark" src="figures/dark/{stem}.png" alt="{a}" loading="lazy">'
            f'<figcaption><span class="fignum">{fid}</span> {html.escape(cap)}</figcaption></figure>')


def link_citations(h):
    def repl(m):
        refs = [r.strip() for r in m.group(1).split(",")]
        return "[" + ", ".join(f'<a class="cite" href="#r{r[1:]}">{r}</a>' for r in refs) + "]"
    return re.sub(r"\[((?:R\d+)(?:,\s*R\d+)*)\]", repl, h)


def main():
    md = (ROOT / "blog" / "draft.md").read_text()
    title_line, body = md.split("\n", 1)
    h1 = title_line.lstrip("# ").strip()
    body = re.sub(r"^\*Draft v1[^\n]*\*\n", "", body.lstrip("\n"))   # status line -> page meta instead
    body = body.replace("See `BENCHMARK_DESIGN.md` §12. Every borrowed number is listed in §1.2 with its verification status.",
                        "[[REFS]]")
    body = re.sub(r"^---\s*$", "", body, flags=re.M)
    content = markdown.markdown(preprocess(body), extensions=["tables", "fenced_code", "sane_lists"])
    content = re.sub(r"<p>\[\[FIG:(F\d+)\]\]</p>", lambda m: figure_html(m.group(1)), content)
    content = content.replace("<p>[[REFS]]</p>", f'<div class="refs">{references()}</div>')
    content = link_citations(content)
    content = content.replace("<h2>10. What we conclude</h2>", '<h2 id="conclusions">10. What we conclude</h2>')
    content = re.sub(r"<table>", '<div class="tablewrap"><table>', content).replace("</table>", "</table></div>")
    page = TEMPLATE.replace("{{H1}}", html.escape(h1)).replace("{{CONTENT}}", content)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(page)
    for mode in ("light", "dark"):
        d = OUT / "figures" / mode
        d.mkdir(parents=True, exist_ok=True)
        for stem, _, _ in FIGURES.values():
            shutil.copy(FIGS / mode / f"{stem}.png", d / f"{stem}.png")
    print("wrote", OUT / "index.html", f"({len(page) // 1024} KB)")
    write_pages_site(page)


SITE = ROOT / "docs"  # GitHub Pages source: branch main, folder /docs
SITE_URL = "https://kumida.github.io/openshell-benchmarking/"
DESCRIPTION = ("Four ways to give a coding agent a shell, measured on overhead, task success and nine replayed "
               "attacks: host shell, Docker, and NVIDIA OpenShell with permissive and strict policies.")


def write_pages_site(page):
    """Standalone copy for GitHub Pages: the artifact viewer supplies the document skeleton, Pages doesn't."""
    head_part, body_part = page.split('<div class="page">', 1)
    head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="description" content="{html.escape(DESCRIPTION, quote=True)}">
<meta property="og:type" content="article">
<meta property="og:title" content="What does a sandbox cost an AI agent? OpenShell vs a plain shell">
<meta property="og:description" content="{html.escape(DESCRIPTION, quote=True)}">
<meta property="og:url" content="{SITE_URL}">
<meta property="og:image" content="{SITE_URL}figures/light/F9_attack_heatmap.png">
<meta name="twitter:card" content="summary_large_image">
<style>body {{ margin: 0; }} img {{ max-width: 100%; }}</style>
{head_part.strip()}
</head>
<body>
<div class="page">{body_part}</body>
</html>
"""
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(head)
    (SITE / ".nojekyll").write_text("")  # serve files as-is, no Jekyll processing
    if (SITE / "figures").exists():
        shutil.rmtree(SITE / "figures")
    shutil.copytree(OUT / "figures", SITE / "figures")
    print("wrote", SITE / "index.html")


TEMPLATE = """<title>OpenShell vs Plain Shell</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..100,500..800&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column (~var(--measure)) for prose; figures, tables and code break out wider. Surfaces
   match the figure backgrounds so charts sit flush on the page in both themes. */
:root {
  --bg: #fcfcfb;          /* = figure surface (light) */
  --fg: #16181d;
  --muted: #565a63;
  --rule: #e2e3e6;
  --panel: #f2f4f7;
  --accent: #1c5cab;      /* ramp step used for "OpenShell, permissive" in the figures */
  --accent-soft: #e3ecf8;
  --font-display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --font-body: "Source Serif 4", Georgia, "Times New Roman", serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --show-light: block;
  --show-dark: none;
  --measure: 38rem;   /* text column; rem so headings and body share one edge */
  --wide: 46rem;      /* code blocks and tables */
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #1a1a19; --fg: #ecebe6; --muted: #aeada5; --rule: #34342f; --panel: #232321;
    --accent: #6da7ec; --accent-soft: #22324a; --show-light: none; --show-dark: block; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #1a1a19; --fg: #ecebe6; --muted: #aeada5; --rule: #34342f; --panel: #232321;
  --accent: #6da7ec; --accent-soft: #22324a; --show-light: none; --show-dark: block; color-scheme: dark;
}
body { background: var(--bg); color: var(--fg); font: 18px/1.65 var(--font-body); }
.page { max-width: 1000px; margin: 0 auto; padding-inline: 20px; padding-block: 48px 96px; }
.col, .page > article > :is(p, ul, ol, h2, h3, blockquote) { max-width: var(--measure); margin-inline: auto; }
header.masthead { max-width: var(--measure); margin: 0 auto 40px; display: grid; gap: 14px; }
.kicker { font: 600 12px/1.2 var(--font-display); letter-spacing: .12em; text-transform: uppercase; color: var(--accent); }
h1 { font: 800 clamp(30px, 5.2vw, 46px)/1.08 var(--font-display); font-stretch: 85%; letter-spacing: -.01em; margin: 0; text-wrap: balance; }
.dek { font-size: 20px; color: var(--muted); margin: 0; }
.meta { font: 13px/1.5 var(--font-mono); color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px 18px; border-top: 1px solid var(--rule); padding-top: 12px; }
.glance { max-width: var(--measure); margin: 0 auto 48px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0;
  border-block: 1px solid var(--rule); }
.glance div { padding: 16px 14px 16px 0; min-width: 0; }
.glance div + div { padding-left: 14px; border-left: 1px solid var(--rule); }
.glance b { display: block; font: 800 30px/1.1 var(--font-display); font-stretch: 80%; font-variant-numeric: tabular-nums; color: var(--accent); }
.glance span { font: 14px/1.4 var(--font-display); color: var(--muted); }
article h2 { font: 700 26px/1.2 var(--font-display); font-stretch: 90%; margin-top: 2.4em; margin-bottom: .5em; text-wrap: balance; }
article h3 { font: 700 19px/1.3 var(--font-display); margin-top: 1.8em; }
article p, article li { hyphens: auto; }
article ul { padding-left: 1.2em; }
article li { margin: .35em 0; }
article strong { font-weight: 600; }
a { color: var(--accent); text-underline-offset: 2px; }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }
code { font: .86em var(--font-mono); background: var(--panel); padding: .08em .3em; border-radius: 3px; overflow-wrap: anywhere; }
pre { max-width: var(--wide); margin: 1.4em auto; background: var(--panel); border-left: 3px solid var(--accent); padding: 14px 16px;
  overflow-x: auto; font: 13.5px/1.55 var(--font-mono); }
pre code { background: none; padding: 0; font-size: inherit; overflow-wrap: normal; }
.tablewrap { max-width: var(--wide); margin: 1.4em auto; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font: 15px/1.45 var(--font-display); font-variant-numeric: tabular-nums; }
th { text-align: left; font-weight: 700; border-bottom: 2px solid var(--fg); padding: 8px 12px 8px 0; }
td { border-bottom: 1px solid var(--rule); padding: 8px 12px 8px 0; vertical-align: top; }
figure.fig { margin: 2em auto; max-width: 960px; }
figure.fig img { width: 100%; height: auto; max-width: 100%; }
figure.diagram { overflow-x: auto; }
figure.diagram svg { display: block; width: 100%; min-width: 560px; height: auto; color: var(--fg); }
.fig-light { display: var(--show-light); }
.fig-dark { display: var(--show-dark); }
figcaption { max-width: var(--measure); margin: 8px auto 0; font: 14px/1.45 var(--font-display); color: var(--muted); }
.fignum { font-weight: 700; color: var(--fg); margin-right: 4px; }
a.cite { text-decoration: none; font-family: var(--font-mono); font-size: .82em; }
.refs ul { list-style: none; padding: 0; font-size: 15px; line-height: 1.5; }
.refs li { margin: .6em 0; overflow-wrap: anywhere; }
.refid { font: 600 13px var(--font-mono); color: var(--accent); margin-right: 4px; }
.refs li:target { background: var(--accent-soft); }
footer { max-width: var(--measure); margin: 56px auto 0; border-top: 1px solid var(--rule); padding-top: 14px;
  font: 13px/1.5 var(--font-display); color: var(--muted); }
@media (max-width: 560px) {
  body { font-size: 17px; }
  .glance { grid-template-columns: 1fr; }
  .glance div + div { padding-left: 0; border-left: 0; border-top: 1px solid var(--rule); }
}
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
<div class="page">
  <header class="masthead">
    <div class="kicker">Benchmark · draft for review</div>
    <h1>{{H1}}</h1>
    <p class="dek">Four ways to give a coding agent a shell, measured on overhead, task success and nine replayed attacks.</p>
    <div class="meta"><span>2026-10-03</span><span>OpenShell 0.1.2</span><span>qwen2.5:3b on a 4 GB GPU</span><span>800 task runs · 720 attack reps</span><a href="#conclusions">Jump to conclusions</a></div>
  </header>
  <section class="glance" aria-label="Headline numbers">
    <div><b>+10 ms</b><span>per command vs Docker; 1.1% of a typical task's time</span></div>
    <div><b>8 of 9</b><span>attack types blocked, every time, by a strict policy written for them</span></div>
    <div><b>1 in 200</b><span>benign runs where the strict policy actually got in the agent's way</span></div>
  </section>
  <article>
{{CONTENT}}
  </article>
</div>
"""

if __name__ == "__main__":
    main()
