#!/usr/bin/env python3
"""U4d: the coupling from a late or a warm delivery to the pharmacy's stockouts and write-offs, as recorded `flow` steps, and G3d and G7 (docs/use-cases.md, margins of 7a for U4d, committed before this was built).

    CANCHO=<compiler> python3 scripts/pipeline_ad.py [--mutants] [--mutant NAME] [--keep DIR]

Two worlds of the large size, the same seed: the twin with the table `coupled` (a late week holds the delivery to the next week, a warm week throws away the cold-chain arrival) and without it (the control: the same delivery data, no effect).
`stats test prop`: the stockout against *late week*; the write-off, among cold-chain items that received stock, against *warm week*.
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
import pipeline_a as pa  # noqa: E402
import pipeline_c as pc  # noqa: E402

# --- the margins of docs/use-cases.md section 7a (G3d), fixed before this pipeline was built ---
LATE_MIN = 0.05          # stockout proportion, late weeks minus others, at least this in the twin
WARM_MIN = 0.5           # write-off proportion among cold-chain arrivals, warm weeks minus others, at least this in the twin
CONTROL_TOL = 0.01       # within this of zero (stockout), and each write-off share at most this, in the control
P_FOUND = 1e-6
P_ABSENT = 1e-3
SEED = 20261112
FILES = pa.DEL_FILES + ["dispensing.csv", "truth/demand.csv"]
WORLDS = (("main", "core,dispensing,delivery,coupled", FILES + ["truth/coupling.csv"]), ("control", "core,dispensing,delivery", FILES))


def run_steps(fl):
    tb = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]
    pa.world(fl, "main", None)
    for tag, tables, outs in WORLDS:
        d = "data_" + tag
        fl.step(pa.TWIN + ["world_main.json"], ["%s/%s" % (d, f) for f in outs],
                ["python3", "twin.py", "generate", "--world", "world_main.json", "--seed", str(SEED), "--size", "large", "--tables", tables, "--out", d])
        fl.step(["features_ad.py", d + "/dispensing.csv", d + "/items.csv", d + "/routes.csv", d + "/telemetry.csv"], ["pw_%s.csv" % tag], ["python3", "features_ad.py", d, "pw_%s.csv" % tag])
        fl.step(["pw_%s.csv" % tag], ["cold_%s.csv" % tag], tb + ["cold_%s.csv" % tag, "--where", "cold = '1' and received:int > 0", "pw_%s.csv" % tag])
        fl.step(["pw_%s.csv" % tag], [], ["stats", "--root", ".", "test", "prop", "--cols", "stockout", "--success", "1", "--group", "late", "pw_%s.csv" % tag], stdout_file="prop_late_%s.json" % tag)
        fl.step(["cold_%s.csv" % tag], [], ["stats", "--root", ".", "test", "prop", "--cols", "wo", "--success", "1", "--group", "warm", "cold_%s.csv" % tag], stdout_file="prop_warm_%s.json" % tag)


def diff(doc):
    """(flagged minus others, p, n flagged, n others, share flagged, share others), from the counts the test printed."""
    t = doc["data"]["tests"][0]
    lv = t["levels"]
    assert lv == {"a": "0", "b": "1"}, lv
    a, b = t["n"]["a"], t["n"]["b"]
    pa_, pb_ = a["successes"] / a["n"], b["successes"] / b["n"]
    return pb_ - pa_, t["p_value"], b["n"], a["n"], pb_, pa_, t.get("reason")


def judge(fl):
    problems, report = [], []
    J = lambda rel: json.loads(fl.read(rel))
    d1, p1, nb1, na1, sb1, sa1, _ = diff(J("prop_late_main.json"))
    d0, p0, nb0, na0, sb0, sa0, _ = diff(J("prop_late_control.json"))
    report.append("G3d stockout, late weeks (%d rows) minus others (%d): %+.4f, p = %.2e (%.4f against %.4f); control (no coupling): %+.4f, p = %s (%.4f against %.4f)" % (
        nb1, na1, d1, p1, sb1, sa1, d0, ("%.3f" % p0) if p0 is not None else "none", sb0, sa0))
    if not (d1 >= LATE_MIN and p1 is not None and p1 < P_FOUND):
        problems.append("G3d: the effect of a late week on the stockout was not found (difference %+.4f, p = %s, wanted at least %.2f and p < %g)" % (d1, p1, LATE_MIN, P_FOUND))
    if not (abs(d0) <= CONTROL_TOL and (p0 is None or p0 >= P_ABSENT)):
        problems.append("G3d: in the control the stockout differs between late weeks and the others by %+.4f (p = %s): wanted within %.2f of zero and p >= %g" % (d0, p0, CONTROL_TOL, P_ABSENT))
    w1, q1, wb1, wa1, ws1, wsa1, _ = diff(J("prop_warm_main.json"))
    w0, q0, wb0, wa0, ws0, wsa0, reason0 = diff(J("prop_warm_control.json"))
    report.append("G3d write-off of cold-chain arrivals, warm weeks (%d) minus others (%d): %+.4f, p = %.2e (%.4f against %.4f); control: shares %.4f and %.4f, stats says %s" % (
        wb1, wa1, w1, q1, ws1, wsa1, ws0, wsa0, reason0 or ("p = %.3f" % q0 if q0 is not None else "no p")))
    if not (w1 >= WARM_MIN and q1 is not None and q1 < P_FOUND):
        problems.append("G3d: the effect of a warm week on the write-off was not found (difference %+.4f, p = %s, wanted at least %.2f and p < %g)" % (w1, q1, WARM_MIN, P_FOUND))
    if not (ws0 <= CONTROL_TOL and wsa0 <= CONTROL_TOL):
        problems.append("G3d: in the control the write-off shares of the arrivals are %.4f (warm weeks) and %.4f (others), wanted at most %.2f" % (ws0, wsa0, CONTROL_TOL))
    tj = json.loads(fl.read("data_main/truth.json")).get("delivery_realised", {})
    report.append("twin (large): %d routes, %d late stops, %d excursions in the delivery files" % (tj.get("routes", 0), tj.get("late_stops", 0), tj.get("excursions", 0)))
    p7, r7 = pc.judge_records(fl, "pw_main.csv")
    return problems + p7, report + r7


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        shutil.copy(HERE / "features_ad.py", fl.root / "features_ad.py")
        shutil.copy(HERE / "twinlib" / "delivery.py", fl.root / "twinlib" / "delivery.py")
        run_steps(fl)
        out = judge(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return out


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("twin-ignores-late-weeks", "twinlib/core.py", 'if flags and (phid, week) in flags["late"]:', "if False:", "G3d"),
    ("twin-ignores-warm-weeks", "twinlib/core.py", 'discarded = received if (flags and cold and (phid, week) in flags["warm"]) else 0', "discarded = 0", "G3d"),
    ("control-is-coupled", "scripts/pipeline_ad.py", _x('("control", "core,dispensing,delivery"', ', FILES))'), '("control", "core,dispensing,delivery,coupled", FILES + ["truth/coupling.csv"]))', "G3d"),
    ("late-flag-from-the-wrong-column", "features_ad.py", _x('int(k in late), int(k in ', 'warm)'), 'int(k in warm), int(k in warm)', "G3d"),
    ("warm-test-grouped-by-late", "scripts/pipeline_ad.py", _x('"--success", "1", "--group", "', 'warm", "cold_%s.csv"'), '"--success", "1", "--group", "late", "cold_%s.csv"', "G3d"),
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
                print("mutant %-36s CANNOT BE APPLIED (%d occurrences in %s)" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            env = dict(os.environ, FLOW_REPO=str(pc.REPO), TABLE=pc.exe("table", "TABLE"), STATS=pc.exe("stats", "STATS"), ML=pc.exe("ml", "ML"), SOLVE=pc.exe("solve", "SOLVE"), OPT=pc.exe("opt", "OPT"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "pipeline_ad.py")], capture_output=True, text=True, env=env, cwd=td, timeout=3600)
            out = r.stdout + r.stderr
            if only:
                print(out[-2500:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-36s by %s" % (name, hit[0][:130]))
            else:
                survived += 1
                print("SURVIVED %-36s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
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
    print("pipeline_ad: ok (G3d and G7 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
