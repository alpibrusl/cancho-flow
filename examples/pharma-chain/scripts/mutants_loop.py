#!/usr/bin/env python3
"""Mutants of the loop (docs/use-cases.md section 7a, U7b/U7c): each is a one-line change to a copy of the example, run as a short arm (decisions at the ends of weeks 90 and 91, outcomes through week 93, seed 20261112) and judged
by the gates of experiment.py (G21 to G23, without the claims, which need the whole horizon). A mutant is killed when its run stops (the twin or the loop refuses) or the judge reports a problem. The unmutated arm is run first
as the CONTROL: it must give no problem, or no kill below means anything.

    CANCHO=<compiler> SCIPY_PYTHON=<python with scipy> python3 scripts/mutants_loop.py --d DIR_WITH_D_DATA [--out DIR] [name ...]

DIR_WITH_D_DATA holds the batch twin's tables for the seed (data/ of arm D of the experiment). Without names: the controls, then every mutant.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
SEED, FIRST, LAST, END = 20261112, 90, 91, 93

# name: (arm, file, old text (once), new text, what the gates are expected to say)
MUTANTS = {
    "wrong-week": ("C", "scripts/closed_loop.py", '"merge", str(w), "decisions/week-%d.json" % w]', '"merge", str(w + 1), "decisions/week-%d.json" % w]', "the decisions of a week written under the next week's number"),
    "pharmacy-swapped": ("C", "plan_decisions.py", '"pharmacy": d["pharmacy"], "item": item', '"pharmacy": {"P001": "P002", "P002": "P001"}.get(d["pharmacy"], d["pharmacy"]), "item": item', "the orders of P001 under P002 and the reverse"),
    "refit-after-89": ("C", "scripts/closed_loop.py", "twin_step(fl, seed, FIT_THROUGH, [])", "twin_step(fl, seed, FIT_THROUGH + 1, [])", "the model fitted with week 90 in it (also the where clause below)"),
    "actions-swapped": ("B", "plan_decisions.py", 'KINDS = (("call", "xc"), ("reminder", "xr")', 'KINDS = (("reminder", "xc"), ("call", "xr")', "the names of two outreach actions swapped"),
    "no-pack": ("C", "plan_decisions.py", '"units": d["pack"][i] * int(round(plan["x"]["q[%d]" % i]))', '"units": int(round(plan["x"]["q[%d]" % i]))', "orders not multiplied by the pack size"),
    "no-outreach-in-merge": ("B", "scripts/closed_loop.py", '            parts.append("b_dec.json")', "            pass", "arm B would equal D"),
    "lapse-flag-dropped": ("CL", "scripts/closed_loop.py", '(["--lapse", "lapse.json"] if lapse else [])', "[]", "arm CL would be arm C (G24: no lapse member)"),
    "clock-in-decisions": ("B", "plan_decisions.py", 'doc = {"week": week}', 'doc = {"week": week, "clock": __import__("time").time()}', "a time in a decisions file (G22)"),
}
# the second edit of a mutant that needs two
EXTRA = {"refit-after-89": ("scripts/closed_loop.py", '<= %d" % (C_FIT_FROM, FIT_THROUGH)', '<= %d" % (C_FIT_FROM, FIT_THROUGH + 1)')}


def copy_tree(dst):
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns("__pycache__"))


def apply(root, name):
    arm, rel, old, new, _ = MUTANTS[name]
    edits = [(rel, old, new)] + ([EXTRA[name]] if name in EXTRA else [])
    for rel, old, new in edits:
        p = pathlib.Path(root) / rel
        t = p.read_text()
        if t.count(old) != 1:
            sys.exit("mutants_loop: the text of mutant %s occurs %d times in %s" % (name, t.count(old), rel))
        p.write_text(t.replace(old, new))


def run(name, arm, work, dpath, py):
    """Run one arm from a (mutated) copy; return (stopped_text or None, judge_output, judge_rc)."""
    root = pathlib.Path(work) / "tree"
    copy_tree(root)
    if name:
        apply(root, name)
    out = pathlib.Path(work) / "out"
    (out / ("D_%d" % SEED)).mkdir(parents=True)
    os.symlink(os.path.abspath(dpath), out / ("D_%d" % SEED) / "data")
    env = dict(os.environ, FLOW_REPO=str(REPO), FLOW_TIMEOUT_MS="600000")
    r = subprocess.run([sys.executable, str(root / "scripts" / "closed_loop.py"), "--arm", arm, "--seed", str(SEED), "--out", str(out / ("%s_%d" % (arm, SEED))), "--first", str(FIRST), "--last", str(LAST), "--end", str(END)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        import re
        rules = re.findall(r'"rule":"([A-Za-z0-9_.-]+)"', r.stdout + r.stderr)
        return ("rule " + ", ".join(sorted(set(rules))) if rules else (r.stdout + r.stderr).strip()[-300:]), "", None
    code = "import sys,pathlib; sys.path.insert(0,%r); import experiment; sys.exit(experiment.judge([%d], pathlib.Path(%r), %d, %d, %d, arms=(%r,), with_claims=False))" % (str(HERE / "scripts"), SEED, str(out), FIRST, LAST, END, arm)
    j = subprocess.run([py, "-c", code], capture_output=True, text=True, env=env)
    return None, j.stdout, j.returncode


def main(argv):
    def arg(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    dpath = arg("--d")
    if not dpath:
        sys.stderr.write("mutants_loop.py --d DIR_WITH_D_DATA [--out DIR] [name ...]\n")
        return 2
    skip = {arg("--d"), arg("--out")}
    names = [a for a in argv if not a.startswith("--") and a not in skip]
    for n in names:
        if n not in MUTANTS:
            sys.stderr.write("mutants_loop: no mutant called %s\n" % n)
            return 2
    py = os.environ.get("SCIPY_PYTHON", sys.executable)
    base = pathlib.Path(arg("--out") or tempfile.mkdtemp(prefix="mutants_loop_"))
    base.mkdir(parents=True, exist_ok=True)
    todo = [("control-" + a, None, a) for a in ("C", "B", "CL")] + [(n, n, MUTANTS[n][0]) for n in (names or MUTANTS)]
    if not names:
        pass
    results = {}

    def job(item):
        label, mut, arm = item
        w = base / label
        if w.exists():
            shutil.rmtree(w)
        w.mkdir()
        return label, run(mut, arm, w, dpath, py)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for label, res in ex.map(job, todo):
            results[label] = res
    bad = 0
    for label, mut, arm in todo:
        stopped, out, rc = results[label]
        if mut is None:
            ok = stopped is None and rc == 0
            print("%s: %s" % (label, "clean (no problem reported), as a control must be" if ok else "NOT CLEAN: %s" % (stopped or out[-300:])))
            bad += 0 if ok else 1
        else:
            probs = [ln for ln in out.splitlines() if ln.startswith("G2") or ": G2" in ln]
            if stopped is not None:
                print("%s: KILLED, the run stopped: %s" % (label, stopped.replace("\n", " ")[-200:]))
            elif rc != 0:
                print("%s: KILLED by %s" % (label, "; ".join(p[:140] for p in probs[:2])))
            else:
                print("%s: SURVIVED (%s)" % (label, MUTANTS[label][4]))
                bad += 1
    print("mutants_loop: %d of %d mutants killed, controls %s" % (sum(1 for l, m, a in todo if m and (results[l][0] is not None or results[l][2] != 0)), sum(1 for l, m, a in todo if m),
                                                              "clean" if all(results["control-" + a][0] is None and results["control-" + a][2] == 0 for a in ("C", "B", "CL")) else "NOT CLEAN"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
