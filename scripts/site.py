#!/usr/bin/env python3
"""Regenerate the parts of the landing page that are program output, from the built programs, so that they cannot drift from them.

    python3 scripts/site.py            # rewrite the generated regions and files
    python3 scripts/site.py --check    # change nothing; exit 1 if a file differs

The mechanism is cancho-ml's (scripts/site.py there), at the size of one page. A generated region is a pair of comment lines in docs/index.html,

    <!-- gen:NAME -->
    ...whatever this script writes...
    <!-- /gen:NAME -->

and nothing outside a pair is touched, except the figures marked `data-n="NAME"`, which are rewritten from the sources. What is generated:

    replay        docs/index.html    three runs of the real programs on a small access log: record a step and check it, a record that goes stale,
                                     refusals. Each command ran once, in a scratch directory, with `flow` and `flow-records` as found on PATH.
    figures       data-n="NAME"      computed here from the sources (the gates, the rule tables, the committed manifests)
    docs/agents.md, docs/llms.txt, docs/robots.txt, docs/sitemap.xml   written whole

The demo programs directory holds `digest` (scripts/site/digest, a script of this repository, so that every id and oid on the page is the same on
every machine) and links to cut, sort, uniq, sh and sleep. `flow` and `flow-records` are built for it by scripts/flow_build.py into build/site/
($CANCHO, and `cancho install` must have run). Standard library only.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE = ROOT / "build" / "site"
URL = "https://alpibrusl.github.io/cancho-flow/"

LOG = ["10.0.0.7 GET /index 200", "10.0.0.3 GET /index 200", "10.0.0.7 GET /docs 200", "10.0.0.9 POST /login 401",
       "10.0.0.7 GET /docs 200", "10.0.0.3 GET /index 304", "10.0.0.9 POST /login 200", "10.0.0.7 GET /index 200"]
MORE = ["10.0.0.3 GET /docs 200", "10.0.0.3 GET /docs 200"]
STEP = ["flow", "step", "--record", "records", "--in", "access.log", "--out", "digest.txt", "--deterministic", "--", "digest", "access.log", "digest.txt"]


# ---- the programs and the runs -------------------------------------------------

def build_programs(rebuild=False):
    """build/site/{programs,bin}: the demo programs directory, and `flow` and `flow-records` built for it, as found on PATH."""
    programs, bindir = SITE / "programs", SITE / "bin"
    if rebuild and SITE.exists():
        shutil.rmtree(SITE)
    if (bindir / "flow").exists() and (bindir / "flow-records").exists():
        return bindir
    programs.mkdir(parents=True, exist_ok=True)
    bindir.mkdir(parents=True, exist_ok=True)
    for name in ("cut", "sort", "uniq", "sh", "sleep"):
        link = programs / name
        if link.is_symlink() or link.exists():
            link.unlink()
        found = shutil.which(name)
        if not found:
            sys.exit("site.py needs %s on PATH" % name)
        link.symlink_to(os.path.realpath(found))
    shutil.copy(ROOT / "scripts" / "site" / "digest", programs / "digest")
    os.chmod(programs / "digest", 0o755)
    for which in ("flow", "flow-records"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "flow_build.py"), "--programs", str(programs), "--out", str(bindir / which), "--bin", which],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("could not build %s for the demo programs directory:\n%s%s" % (which, r.stdout, r.stderr))
    return bindir


def tidy(text):
    """A 64-digit hash is shown as its first twelve digits and an ellipsis, and a timing is not shown (it varies between runs)."""
    text = re.sub(r'"milliseconds":\d+', '"milliseconds":N', text)
    return re.sub(r"\b([0-9a-f]{12})[0-9a-f]{52}\b", r"\1…", text)


def cut(line, n=330):
    return line if len(line) <= n else line[:n].rstrip() + " …"


class Session:
    def __init__(self, bindir):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="flowsite-"))
        (self.dir / "records").mkdir()
        (self.dir / "access.log").write_text("".join(l + "\n" for l in LOG))
        self.env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ.get("PATH", "")))
        self.lines = []

    def comment(self, text):
        self.lines.append(("d", "# " + text))

    def command(self, words, shown=None):
        """Run `words` (a flow command), show it, and show what it printed: the one JSON line, tidied, and its exit status."""
        self.lines.append(("a", "$ " + (shown or " ".join(shell_word(w) for w in words))))
        p = subprocess.run(words, cwd=self.dir, env=self.env, capture_output=True, text=True)
        out = p.stdout.strip()
        self.last = json.loads(out) if out.startswith("{") else None
        if out:
            self.lines.append(("b" if p.returncode else "g", cut(tidy(out))))
        if p.returncode:
            self.lines.append(("b", "# exit status %d" % p.returncode))
        return p

    def note(self, words, text, cls=""):
        self.lines.append(("a", "$ " + words))
        self.lines.append((cls, text))


def shell_word(w):
    return w if re.fullmatch(r"[A-Za-z0-9_./:=,@%+-]+", w) else "'" + w.replace("'", "'\\''") + "'"


def refusal(line_json):
    """A refusal shown by its rule, message and hint: the parts that do not change between runs of the same fault."""
    e = line_json["error"]
    return '{"ok":false,"error":{"rule":"%s","message":"%s","hint":"%s", …}}' % (e["rule"], e["message"], e["hint"])


def run_demos(bindir):
    panels = {}
    s = Session(bindir)
    # 1. record a step and check it
    s.comment("a log digest: the step reads access.log and writes digest.txt; `digest` is a program of the programs directory")
    p = s.command(STEP)
    first = s.last
    rid = first["data"]["record"]["id"]
    out_entry = first["data"]["outcome"]["out"][0]
    s.note("cat digest.txt", (s.dir / "digest.txt").read_text().rstrip("\n"))
    s.comment("the same step again is the same record: nothing is written")
    s.command(STEP)
    s.comment("the records, and a check that the program and every declared file still match (ID is the id above)")
    s.command(["flow-records", "list", "records"])
    s.command(["flow-records", "check", "records", rid], shown="flow-records check records ID")
    record_bytes = len((s.dir / "records" / first["data"]["record"]["file"]).read_bytes())
    panels["record"] = s.lines

    # 2. the digest goes stale
    s.lines = []
    s.comment("two more requests are appended to the log")
    with open(s.dir / "access.log", "a") as f:
        f.write("".join(l + "\n" for l in MORE))
    s.lines.append(("a", "$ printf '10.0.0.3 GET /docs 200\\n10.0.0.3 GET /docs 200\\n' >> access.log"))
    s.command(["flow-records", "check", "records", rid], shown="flow-records check records ID")
    s.comment("the step on the new log is another step: another id, another record. The first stays as it was")
    s.command(STEP)
    new = s.last["data"]["record"]["id"]
    s.command(["flow-records", "list", "records"])
    s.command(["flow-records", "check", "records", new], shown="flow-records check records ID2")
    s.comment("the old record is still a true statement about the old log, and says so")
    s.command(["flow-records", "check", "records", rid], shown="flow-records check records ID")
    panels["stale"] = s.lines

    # 3. refusals are data
    s.lines = []
    s.comment("a step whose program fails: the record is written, and the answer is a refusal")
    s.lines.append(("a", "$ flow step --record records -- sh -c 'exit 3'"))
    p = subprocess.run(["flow", "step", "--record", "records", "--", "sh", "-c", "exit 3"], cwd=s.dir, env=s.env, capture_output=True, text=True)
    s.lines.append(("b", cut(refusal(json.loads(p.stdout)))))
    s.lines.append(("b", "# exit status %d" % p.returncode))
    s.comment("a step whose job is to say no: --allow-failure")
    s.lines.append(("a", "$ flow step --record records --allow-failure -- sh -c 'exit 3'"))
    p = subprocess.run(["flow", "step", "--record", "records", "--allow-failure", "--", "sh", "-c", "exit 3"], cwd=s.dir, env=s.env, capture_output=True, text=True)
    ok = json.loads(p.stdout)
    s.lines.append(("g", '{"ok":%s,"data":{"record":{…},"outcome":{"exit":%d, …}}}' % ("true" if ok["ok"] else "false", ok["data"]["outcome"]["exit"])))
    s.comment("a deadline: the program is killed, and the timeout is recorded")
    s.lines.append(("a", "$ flow step --record records --timeout-ms 300 -- sleep 5"))
    p = subprocess.run(["flow", "step", "--record", "records", "--timeout-ms", "300", "--", "sleep", "5"], cwd=s.dir, env=s.env, capture_output=True, text=True)
    s.lines.append(("b", cut(refusal(json.loads(p.stdout)))))
    s.lines.append(("b", "# exit status %d" % p.returncode))
    s.comment("a claim that is false: declared deterministic, and the program prints its own process id")
    s.lines.append(("a", "$ flow step --record records --deterministic -- sh -c 'echo $$'      (twice)"))
    subprocess.run(["flow", "step", "--record", "records", "--deterministic", "--", "sh", "-c", "echo $$"], cwd=s.dir, env=s.env, capture_output=True)
    p = subprocess.run(["flow", "step", "--record", "records", "--deterministic", "--", "sh", "-c", "echo $$"], cwd=s.dir, env=s.env, capture_output=True, text=True)
    s.lines.append(("b", cut(refusal(json.loads(p.stdout)))))
    s.lines.append(("b", "# exit status %d" % p.returncode))
    s.comment("a program that is not in the directory")
    s.lines.append(("a", "$ flow step --record records -- rm"))
    p = subprocess.run(["flow", "step", "--record", "records", "--", "rm"], cwd=s.dir, env=s.env, capture_output=True, text=True)
    s.lines.append(("b", cut(refusal(json.loads(p.stdout)))))
    s.lines.append(("b", "# exit status %d" % p.returncode))
    panels["refuse"] = s.lines
    shutil.rmtree(s.dir, ignore_errors=True)
    return panels, {"record_bytes": record_bytes}


# ---- rendering -------------------------------------------------------------------

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


TABS = [("record", "Record a step and check it"), ("stale", "A digest that went stale"), ("refuse", "Refusals are data")]


def replay_html(panels):
    out = ['<div class="tabs" role="tablist" aria-label="Replayed runs" hidden>']
    for i, (key, label) in enumerate(TABS):
        out.append('<button type="button" role="tab" id="tab-%s" aria-controls="screen-%s" aria-selected="%s" tabindex="%d">%s</button>' % (key, key, "true" if i == 0 else "false", 0 if i == 0 else -1, label))
    out.append("</div>")
    for key, label in TABS:
        out.append('<div class="plabel">%s</div>' % label)
        body = "\n".join('<span%s>%s</span>' % (' class="%s"' % c if c else "", esc(t)) for c, t in panels[key])
        out.append('<pre id="screen-%s" class="screen" role="tabpanel" aria-labelledby="tab-%s" tabindex="0">%s</pre>' % (key, key, body))
    return "\n".join(out)


# ---- the figures -----------------------------------------------------------------

def introspect(bindir, which):
    return json.loads(subprocess.run([str(bindir / which), "introspect"], capture_output=True, text=True).stdout)


def figures(bindir, extra):
    """The figures of the page. `damaged` is read from docs/design.md section 13.1 (the gate's record, not the demo's); the others are counted
    from the sources and the built programs."""
    design = (ROOT / "docs" / "design.md").read_text()
    m = re.search(r"\*\*([\d,]+) cases, all refused as `flow.record.damaged`", design)
    if not m:
        sys.exit("docs/design.md section 13.1 no longer says how many damaged copies G2 refuses")
    mut = (ROOT / "scripts" / "mutants.py").read_text()
    gates = (ROOT / "tests" / "gates.py").read_text()
    rules = set()
    labels = {}
    for which in ("flow", "flow-records"):
        d = introspect(bindir, which)
        rules |= {r["rule"] for r in d["rules"]}
        labels[which] = len(d["authority"]["labels"])
    return {"damaged": m.group(1), "fixtures": str(len(re.findall(r'^    f\["', gates, re.M))), "mutants": str(len(re.findall(r"^    \(", mut, re.M))),
            "rules": str(len(rules)), "labels_flow": str(labels["flow"]), "labels_records": str(labels["flow-records"])}


def set_figures(html, figs):
    def sub(m):
        name = m.group(2)
        if name not in figs:
            sys.exit("the page has a figure data-n=%s that site.py does not compute" % name)
        return m.group(1) + figs[name] + m.group(3)
    return re.sub(r'(<(?:b|span) data-n="([a-z_]+)">)[^<]*(</(?:b|span)>)', sub, html)


def region(html, name, new):
    pat = re.compile(r"(<!-- gen:%s -->\n).*?(\n<!-- /gen:%s -->)" % (re.escape(name), re.escape(name)), re.S)
    if not pat.search(html):
        sys.exit("docs/index.html has no region gen:%s" % name)
    return pat.sub(lambda m: m.group(1) + new + m.group(2), html)


# ---- the agent view ----------------------------------------------------------------

def agents_md(bindir):
    f, r = introspect(bindir, "flow"), introspect(bindir, "flow-records")

    def labels(d):
        return ", ".join(l["name"] + ('("%s")' % l["argument"] if l["argument"] else "") for l in d["authority"]["labels"])
    lines = ["# cancho-flow", "", "> A run is a claim you can check. `flow step` runs one program as a recorded step; `flow-records` reads the records back.",
             "> Generated by scripts/site.py from the built programs; the same facts as " + URL + ".", "", "## What it does", "",
             "- `flow step` starts one program from a directory baked into the binary, with exact arguments, no shell, an environment that holds only `PATH`, a deadline and an output cap.",
             "- It hashes the program's own file and every file named by `--in` before, and every file named by `--out` after, and writes a canonical record `DIR/<id>.<oid>.json`:",
             "  `id` is the SHA-256 of what determined the outcome, `oid` of the outcome, and a `check` covers every byte. No clock time, host, absolute path or payload is recorded.",
             "- `flow-records list|show|check` reads them; `check` says which of the program, the inputs and the outputs no longer match.",
             "- Not built: `replay`, `compare`, memoisation, `--keep-output`, plans (docs/design.md section 11). It is not a scheduler, a shell or a sandbox.", "",
             "## Commands", "", "```", f["usage"], r["usage"], "```", "",
             "Answers are one JSON line, schema `flow.v1`: `{ok, command, schema, data, error, errors, meta}`. Match on `error.rule`, never on `message`.", "",
             "## Authority (derived by the compiler)", "", "- `flow`: " + labels(f), "- `flow-records`: " + labels(r),
             "- `flow-records` has no `exec`, no `clock` and no write: scripts/manifest.py fails it otherwise.", "",
             "## Refusal rules", ""]
    seen = {}
    for d in (f, r):
        for rule in d["rules"]:
            seen.setdefault(rule["rule"], rule)
    for tag in sorted(seen):
        lines.append("- `%s` (exit %d): %s" % (tag, seen[tag]["exit"], seen[tag]["summary"]))
    lines += ["", "## Honest limits", "",
              "- It records what the caller declares and cannot see a file a program reads or writes without being told; a cached step (when memoisation exists) can then be wrong.",
              "- A secret in an argument is recorded: keep secrets in files named with `--in`, where only a hash is recorded.",
              "- Tested on Linux x86-64 only; \"the same bytes on every platform\" is open until a fingerprint is checked on more than one.",
              "- One counted user so far (cancho-consulting).", "", "## Build", "", "See " + URL + "#try and README.md.", ""]
    return "\n".join(lines)


def llms_txt():
    return "\n".join(["# cancho-flow", "", "> A run is a claim you can check: one program, recorded as a canonical content-addressed record, read back and checked.", "",
                      "- [This page, as Markdown](%sagents.md): commands, authority, rules, limits" % URL,
                      "- [Design](https://github.com/alpibrusl/cancho-flow/blob/main/docs/design.md): decisions, gates and results",
                      "- [Repository](https://github.com/alpibrusl/cancho-flow)", ""])


def sitemap():
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n  <url><loc>%s</loc></url>\n  <url><loc>%sagents.md</loc></url>\n</urlset>\n' % (URL, URL)


def robots():
    return "User-agent: *\nAllow: /\nSitemap: %ssitemap.xml\n" % URL


# ---- main ---------------------------------------------------------------------------

def generate(rebuild=False):
    bindir = build_programs(rebuild)
    panels, extra = run_demos(bindir)
    figs = figures(bindir, extra)
    html = (DOCS / "index.html").read_text()
    html = region(html, "replay", replay_html(panels))
    html = set_figures(html, figs)
    return {DOCS / "index.html": html, DOCS / "agents.md": agents_md(bindir), DOCS / "llms.txt": llms_txt(), DOCS / "sitemap.xml": sitemap(),
            DOCS / "robots.txt": robots()}, panels, figs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the demo programs")
    a = ap.parse_args()
    files, panels, figs = generate(a.rebuild)
    bad = 0
    for path, text in files.items():
        if a.check:
            if not path.exists() or path.read_text() != text:
                print("FAIL %s is not what scripts/site.py writes" % path.relative_to(ROOT))
                bad += 1
        else:
            path.write_text(text)
            print("wrote %s" % path.relative_to(ROOT))
    if a.check and not bad:
        print("site: ok (%d files, figures %s)" % (len(files), figs))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
