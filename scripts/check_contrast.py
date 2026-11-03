#!/usr/bin/env python3
"""WCAG 2.x contrast of the colour pairs of docs/assets/site.css, in the light and in the dark scheme (standard library only).

    python3 scripts/check_contrast.py            # fail (exit 1) if a pair is under its minimum or docs/bench/contrast.txt is not what this prints
    python3 scripts/check_contrast.py --write    # rewrite docs/bench/contrast.txt
    python3 scripts/check_contrast.py --mutants  # the check is shown able to fail

The tokens are read from the file itself (the first :root block is the light scheme; the :root block inside
`@media (prefers-color-scheme: dark)` overrides some of them). A pair is (text token, background token, minimum): 4.5 for text (AA), 3.0 for the
borders and the focus ring (non-text, AA 1.4.11). The pairs are the ones the pages use: body text, muted text, links and the accent on the
page, the soft band and the cards; the status colours; the button text on the accent; the warning notice; and the terminal colours.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "docs" / "assets" / "site.css"
OUT = ROOT / "docs" / "bench" / "contrast.txt"

TEXT = 4.5
UI = 3.0
SURFACES = ["bg", "soft", "surface"]
PAIRS = ([(t, s, TEXT) for t in ("fg", "muted", "accent", "good", "bad") for s in SURFACES]
         + [("warn", "bg", TEXT), ("warn", "surface", TEXT), ("warn", "warn-bg", TEXT), ("fg", "warn-bg", TEXT),
            ("accent-fg", "accent", TEXT),
            ("term-fg", "term-bg", TEXT), ("term-dim", "term-bg", TEXT), ("term-good", "term-bg", TEXT), ("term-bad", "term-bg", TEXT),
            ("term-acc", "term-bg", TEXT), ("term-fg", "term-btn", TEXT), ("term-dim", "term-btn", TEXT),
            ("accent", "bg", UI), ("muted", "line", 1.0)])
PAIRS = [p for p in PAIRS if p[1] != "line"]  # the line colour is decorative: no minimum


def tokens(css):
    light_block = re.search(r":root \{(.*?)\n\}", css, re.S).group(1)
    dark_block = re.search(r"prefers-color-scheme: dark\) \{\s*:root \{(.*?)\}\s*\}", css, re.S).group(1)

    def parse(b):
        return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})\b", b))
    light = parse(light_block)
    dark = dict(light)
    dark.update(parse(dark_block))
    return light, dark


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def report(css):
    light, dark = tokens(css)
    lines = ["# WCAG contrast of docs/assets/site.css (scripts/check_contrast.py); minimum 4.5 for text, 3.0 for the accent as a ring or border",
             "%-8s %-10s %-10s %-9s %-9s %6s %4s" % ("scheme", "text", "on", "text hex", "bg hex", "ratio", "min")]
    fails = []
    for name, toks in (("light", light), ("dark", dark)):
        for t, s, mn in PAIRS:
            r = ratio(toks[t], toks[s])
            ok = r >= mn
            if not ok:
                fails.append("%s: --%s on --%s is %.2f, under %.1f" % (name, t, s, r, mn))
            lines.append("%-8s %-10s %-10s %-9s %-9s %6.2f %4.1f %s" % (name, t, s, toks[t], toks[s], r, mn, "ok" if ok else "FAIL"))
    return "\n".join(lines) + "\n", fails


def main(argv):
    css = CSS.read_text()
    if "--mutants" in argv:
        bad = 0
        for what, new in [("a light muted text too pale", css.replace("--muted: #55606a", "--muted: #9aa5ad", 1)),
                          ("a dark accent too dark", css.replace("--accent: #7fb2ff", "--accent: #2a5fa8", 1)),
                          ("the terminal's dim text too dim", css.replace("--term-dim: #7d8f96", "--term-dim: #3d4c52", 1))]:
            _, fails = report(new)
            print("%-40s %s" % (what, "refused" if fails else "NOT REFUSED"))
            bad += 0 if fails else 1
        return 1 if bad else 0
    text, fails = report(css)
    if "--write" in argv:
        OUT.write_text(text)
        print("wrote", OUT.relative_to(ROOT))
    elif not OUT.exists() or OUT.read_text() != text:
        fails.append("docs/bench/contrast.txt is not what this prints: run scripts/check_contrast.py --write")
    for f in fails:
        print("check_contrast:", f)
    if not fails:
        print("check_contrast: %d pairs in two schemes, all at or above their minimum" % len(PAIRS))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
