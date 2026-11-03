#!/usr/bin/env python3
"""Check docs/index.html against what it promises, without trusting scripts/site.py.

    python3 scripts/check_landing.py            # check the page
    python3 scripts/check_landing.py --selftest # break a copy of the page in ten ways; each must fail the check (exit 1 if one passes)

What is checked: one h1 and a title of 20 to 70 characters; a canonical URL, a description, a skip link and one main; no external script, stylesheet,
image or font (a link to another site is allowed, a request to one is not); size budgets (page 32 KB, inline script 3 KB, assets/home.js 8 KB);
every local href and src exists; the ids assets/home.js looks for exist; every replay tab has a panel and every panel a tab, and no panel shows a
64-digit hash or a timing; every `data-n` figure equals a value computed here from the sources (the gate fixtures, the mutant table, docs/design.md
section 13.1) or, for the rule and label counts, from `flow introspect` of a binary named by $FLOW_BIN and $RECORDS_BIN when they are set;
docs/agents.md says the same rule count as the page; docs/bench/contrast.txt exists and every row ends in ok. Standard library only.
"""
import html.parser
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def figures_from_sources():
    design = (ROOT / "docs" / "design.md").read_text()
    m = re.search(r"\*\*([\d,]+) cases, all refused as `flow.record.damaged`", design)
    gates = (ROOT / "tests" / "gates.py").read_text()
    mut = (ROOT / "scripts" / "mutants.py").read_text()
    figs = {"damaged": m.group(1) if m else "?",
            "fixtures": str(sum(1 for l in gates.splitlines() if l.startswith('    f["'))),
            "mutants": str(sum(1 for l in mut.splitlines() if l.startswith("    (")))}
    return figs


def figures_from_binaries():
    import json
    out = {}
    fb, rb = os.environ.get("FLOW_BIN"), os.environ.get("RECORDS_BIN")
    if fb and rb:
        d = [json.loads(subprocess.run([b, "introspect"], capture_output=True, text=True).stdout) for b in (fb, rb)]
        out["rules"] = str(len({r["rule"] for x in d for r in x["rules"]}))
        out["labels_flow"] = str(len(d[0]["authority"]["labels"]))
        out["labels_records"] = str(len(d[1]["authority"]["labels"]))
    return out


class Scan(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1 = 0
        self.title = ""
        self.in_title = False
        self.main = 0
        self.refs = []
        self.ids = set()
        self.tabs = []
        self.panels = []
        self.meta = {}
        self.canonical = None
        self.skip = False
        self.inline = 0
        self.in_script = False
        self.figs = []
        self.fig_name = None
        self.fig_text = ""
        self.pre = None
        self.pre_text = {}
        self.external = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "h1":
            self.h1 += 1
        if tag == "title" and "id" not in a:  # the document title, not an svg's
            self.in_title = True
        if tag == "main":
            self.main += 1
        if tag == "meta" and a.get("name"):
            self.meta[a["name"]] = a.get("content", "")
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        if tag == "a" and a.get("class") == "skip" and a.get("href") == "#main":
            self.skip = True
        if tag == "script":
            if a.get("src"):
                self.refs.append(a["src"])
                if re.match(r"(https?:)?//", a["src"]):
                    self.external.append(a["src"])
            elif a.get("type") != "application/ld+json":
                self.in_script = True
        if tag == "link" and a.get("href") and a.get("rel") in ("stylesheet", "icon", "alternate"):
            self.refs.append(a["href"])
            if re.match(r"(https?:)?//", a["href"]) and a.get("rel") != "alternate":
                self.external.append(a["href"])
        if tag in ("img", "source", "video", "iframe") and a.get("src"):
            self.external.append(a["src"]) if re.match(r"(https?:)?//", a["src"]) else self.refs.append(a["src"])
        if tag == "a" and a.get("href") and not re.match(r"(https?:|#|mailto:)", a["href"]):
            self.refs.append(a["href"])
        if tag == "button" and a.get("role") == "tab":
            self.tabs.append((a.get("id"), a.get("aria-controls")))
        if tag == "pre" and a.get("role") == "tabpanel":
            self.panels.append((a.get("id"), a.get("aria-labelledby")))
            self.pre = a.get("id")
            self.pre_text[self.pre] = ""
        if "data-n" in a:
            self.fig_name, self.fig_text = a["data-n"], ""

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script":
            self.in_script = False
        if tag == "pre":
            self.pre = None
        if tag in ("b", "span") and self.fig_name is not None:
            self.figs.append((self.fig_name, self.fig_text))
            self.fig_name = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_script:
            self.inline += len(data.encode())
        if self.fig_name is not None:
            self.fig_text += data
        if self.pre:
            self.pre_text[self.pre] += data


def check(page, agents, home_js, contrast):
    bad = []
    s = Scan()
    s.feed(page)
    if s.h1 != 1:
        bad.append("the page has %d h1 (want 1)" % s.h1)
    if not 20 <= len(s.title.strip()) <= 70:
        bad.append("title is %d characters (want 20 to 70)" % len(s.title.strip()))
    if not s.meta.get("description") or not 60 <= len(s.meta["description"]) <= 200:
        bad.append("description missing or not 60 to 200 characters")
    if s.canonical != "https://alpibrusl.github.io/cancho-flow/":
        bad.append("canonical URL is %r" % s.canonical)
    if not s.skip:
        bad.append("no skip link to #main")
    if s.main != 1:
        bad.append("%d main elements (want 1)" % s.main)
    for e in s.external:
        bad.append("an external request: %s" % e)
    if len(page.encode()) > 32 * 1024:
        bad.append("page is %d bytes (budget 32768)" % len(page.encode()))
    if s.inline > 3 * 1024:
        bad.append("inline script is %d bytes (budget 3072)" % s.inline)
    if len(home_js.encode()) > 8 * 1024:
        bad.append("home.js is %d bytes (budget 8192)" % len(home_js.encode()))
    for r in s.refs:
        if not (DOCS / r.split("#")[0].split("?")[0]).exists():
            bad.append("local reference does not exist: %s" % r)
    for i in ("agent-full", "replay", "build-cmds", "main", "agent-view"):
        if i not in s.ids:
            bad.append("id %s is missing (assets/home.js or the skip link needs it)" % i)
    if len(s.tabs) != 3 or len(s.panels) != 3:
        bad.append("want 3 replay tabs and 3 panels, found %d and %d" % (len(s.tabs), len(s.panels)))
    for tid, pid in s.tabs:
        if (pid, tid) not in s.panels:
            bad.append("tab %s has no panel %s that points back" % (tid, pid))
    for pid, text in s.pre_text.items():
        if re.search(r"\b[0-9a-f]{64}\b", text):
            bad.append("panel %s shows a whole 64-digit hash" % pid)
        if re.search(r'"milliseconds":\d', text):
            bad.append("panel %s shows a timing" % pid)
        if "$ " not in text:
            bad.append("panel %s has no command" % pid)
    want = dict(figures_from_sources(), **figures_from_binaries())
    seen = set()
    for name, text in s.figs:
        seen.add(name)
        if name not in want:
            if name in ("rules", "labels_flow", "labels_records"):
                continue  # needs the binaries: checked when $FLOW_BIN and $RECORDS_BIN are set
            bad.append("figure %s has no independent source" % name)
        elif text.strip() != want[name]:
            bad.append("figure %s says %s, the sources say %s" % (name, text.strip(), want[name]))
    for name in ("damaged", "fixtures", "mutants"):
        if name not in seen:
            bad.append("figure %s is not on the page" % name)
    m = re.search(r'data-n="rules">(\d+)<', page)
    a = re.search(r"## Refusal rules\n\n((?:- .*\n)+)", agents)
    if not m or not a or len(a.group(1).splitlines()) != int(m.group(1)):
        bad.append("agents.md lists a different number of rules than the page says")
    rows = [l for l in contrast.splitlines() if l and not l.startswith("#") and not l.startswith("scheme")]
    if len(rows) < 20 or any(not l.rstrip().endswith(" ok") for l in rows):
        bad.append("docs/bench/contrast.txt is missing or has a failing pair")
    return bad


def load():
    return ((DOCS / "index.html").read_text(), (DOCS / "agents.md").read_text(), (DOCS / "assets" / "home.js").read_text(),
            (DOCS / "bench" / "contrast.txt").read_text() if (DOCS / "bench" / "contrast.txt").exists() else "")


BREAKS = {
    "second h1": lambda p: p.replace("<h2 class=\"sr\">What it does</h2>", "<h1>x</h1>", 1),
    "short title": lambda p: re.sub(r"<title>.*?</title>", "<title>flow</title>", p, count=1),
    "external script": lambda p: p.replace('<script src="assets/home.js">', '<script src="https://cdn.example.com/x.js">', 1),
    "no skip link": lambda p: p.replace('class="skip"', 'class="nope"', 1),
    "wrong figure": lambda p: re.sub(r'(data-n="fixtures">)\d+', r"\g<1>99", p, count=1),
    "missing local file": lambda p: p.replace('href="assets/site.css"', 'href="assets/gone.css"', 1),
    "tab without panel": lambda p: p.replace('aria-controls="screen-stale"', 'aria-controls="screen-none"', 1),
    "whole hash in a panel": lambda p: p.replace("62994be4a983…", "0" * 64, 1),
    "a timing shown": lambda p: p.replace("# exit status 5", '"milliseconds":12', 1),
    "oversize page": lambda p: p + "<!--" + "x" * 40000 + "-->",
}


def main():
    page, agents, js, contrast = load()
    if "--selftest" in sys.argv:
        if check(page, agents, js, contrast):
            print("selftest: the unbroken page already fails"); return 1
        miss = 0
        for name, f in BREAKS.items():
            broken = f(page)
            if broken == page:
                print("selftest: break %r changed nothing (stale break)" % name); miss += 1
            elif not check(broken, agents, js, contrast):
                print("selftest: break %r was NOT caught" % name); miss += 1
        print("selftest: %d of %d breaks caught" % (len(BREAKS) - miss, len(BREAKS)))
        return 1 if miss else 0
    bad = check(page, agents, js, contrast)
    for b in bad:
        print("FAIL " + b)
    if not bad:
        print("landing: ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
