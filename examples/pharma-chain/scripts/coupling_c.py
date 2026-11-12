#!/usr/bin/env python3
"""U2c: the coupling from a stockout to a lapse (G3 of docs/use-cases.md; margins in section 7a, committed before the coupling was built), as recorded `flow` steps.

    CANCHO=<compiler> python3 scripts/coupling_c.py [--mutants] [--mutant NAME]

Two worlds of the `large` size (20,000 patients): the twin as it is, and the same with the coupling parameter set to zero. For each: the twin as a step, then
`stats test prop` of the lapse against "saw a stockout". G3 holds when the difference is within 0.02 of the parameter, with p < 1e-6, at its value; and within 0.02 of
zero, with p >= 1e-3, when it is zero. G7 as in pipeline_c.py.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import pipeline_c as pc  # noqa: E402

# --- the margins of docs/use-cases.md section 7a (G3), fixed before the coupling was built ---
TOL = 0.02
P_FOUND = 1e-6
P_ABSENT = 1e-3
SEED = 20261112
TABLES = "core,dispensing,refills"
OUT_FILES = ["items.csv", "pharmacies.csv", "patients.csv", "truth.json", "dispensing.csv", "truth/demand.csv", "refills.csv"]


def world(fl, tag, zero):
    w = json.loads((HERE / "world.json").read_text())
    if zero:
        w["params"]["lapse_stockout_ppm"]["value"] = 0
    (fl.root / ("world_%s.json" % tag)).write_text(json.dumps(w))
    return w


def run_steps(fl, group="stockout_seen", success="0"):
    for tag, zero in (("main", False), ("zero", True)):
        world(fl, tag, zero)
        d = "data_" + tag
        fl.step(pc.TWIN_FILES + ["world_%s.json" % tag], ["%s/%s" % (d, f) for f in OUT_FILES],
                ["python3", "twin.py", "generate", "--world", "world_%s.json" % tag, "--seed", str(SEED), "--size", "large", "--tables", TABLES, "--out", d])
        fl.step([d + "/refills.csv"], [], ["stats", "--root", ".", "test", "prop", "--cols", "filled", "--success", success, "--group", group, d + "/refills.csv"], stdout_file="prop_%s.json" % tag)


def judge(fl):
    problems, report = [], []
    J = lambda rel: json.loads(fl.read(rel))
    value = json.loads((HERE / "world.json").read_text())["params"]["lapse_stockout_ppm"]["value"] / 1e6

    def seen_minus_unseen(rel):
        t = J(rel)["data"]["tests"][0]
        lv = t["levels"]
        # the interval is of a minus b, a being the first level (stockout_seen 0, bytewise) and the success the lapse
        sign = -1.0 if (lv.get("a") == "0" and J(rel)["data"]["success"] == "0") else 1.0
        return sign * t["interval"]["estimate"], t["p_value"], t["n"]
    d1, p1, n1 = seen_minus_unseen("prop_main.json")
    d0, p0, n0 = seen_minus_unseen("prop_zero.json")
    report.append("G3 at its value (%.2f): lapse proportion, saw a stockout minus did not, is %+.4f, p = %.2e, from %d and %d refills" % (value, d1, p1, n1["b"]["n"], n1["a"]["n"]))
    report.append("G3 with the coupling set to zero: %+.4f, p = %.3f, from %d and %d refills" % (d0, p0, n0["b"]["n"], n0["a"]["n"]))
    if not (abs(d1 - value) <= TOL and p1 < P_FOUND):
        problems.append("G3: at its value the difference is %+.4f (p = %.2e): wanted within %.2f of %.2f and p < %g" % (d1, p1, TOL, value, P_FOUND))
    if not (abs(d0) <= TOL and p0 >= P_ABSENT):
        problems.append("G3: with the coupling at zero the difference is %+.4f (p = %.3g): wanted within %.2f of zero and p >= %g" % (d0, p0, TOL, P_ABSENT))
    p2, r2 = pc.judge_records(fl, "data_main/refills.csv")
    return problems + p2, report + r2


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        run_steps(fl)
        out = judge(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return out


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("coupling-ignored-by-the-twin", "twinlib/core.py", 'p["lapse_stockout_ppm"] * seen', "0 * seen", "G3"),
    ("grouped-by-the-wrong-column", "scripts/coupling_c.py", _x('def run_steps(fl, group="stock', 'out_seen"'), 'def run_steps(fl, group="interval_weeks"', "G3"),
]


def mutants(only=None):
    if only is None:
        problems, report = run()
        for ln in report:
            print(ln)
        if problems:
            print("control FAILED:")
            for p in problems:
                print("  " + p)
            return 1
        print("control passes")
    survived = 0
    for name, rel, old, new, gate in MUTANTS:
        if only and name != only:
            continue
        with tempfile.TemporaryDirectory() as td:
            tree = pathlib.Path(td) / "pharma-chain"
            shutil.copytree(HERE, tree, ignore=shutil.ignore_patterns("__pycache__"))
            f = tree / rel
            text = f.read_text()
            if text.count(old) != 1:
                print("mutant %-30s CANNOT BE APPLIED (%d occurrences in %s)" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            env = dict(os.environ, FLOW_REPO=str(pc.REPO), TABLE=pc.exe("table", "TABLE"), STATS=pc.exe("stats", "STATS"), ML=pc.exe("ml", "ML"), SOLVE=pc.exe("solve", "SOLVE"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "coupling_c.py")], capture_output=True, text=True, env=env, cwd=td, timeout=3600)
            out = r.stdout + r.stderr
            if only:
                print(out[-1800:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-30s by %s" % (name, hit[0][:130]))
            else:
                survived += 1
                print("SURVIVED %-30s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
    print("%d mutants, %d survived" % (len(MUTANTS), survived))
    return 1 if survived else 0


def main():
    if "--mutant" in sys.argv:
        return mutants(sys.argv[sys.argv.index("--mutant") + 1])
    if "--mutants" in sys.argv:
        return mutants()
    problems, report = run(sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None)
    for ln in report:
        print(ln)
    for p in problems:
        print(p)
    if problems:
        return 1
    print("coupling_c: ok (G3 and G7 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
