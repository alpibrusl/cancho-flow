#!/usr/bin/env python3
"""U3a: the model of the refill lapse, calibrated, and the effects recovered; G2, G4 and G8 for B and G7 (docs/use-cases.md section 7 and the margins of 7a, committed before this ran).

    CANCHO=<compiler> python3 scripts/pipeline_b.py [--mutants] [--mutant NAME]

The large size (20,000 patients). The twin as it is, and a control whose four lapse effects are zero; the events; a time split (fit before week 60, calibrate 60 to 77, test from 78);
`ml` fits and predicts; `ml isotonic` calibrates; `ml calibrate` and `stats test chisq` look; every step is a recorded `flow` step.
"""
import csv
import json
import math
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

# --- the margins of docs/use-cases.md section 7a (G2, G4, G8 for B), fixed before the model was built ---
G2_P_FOUND = 1e-6
G2_P_ABSENT = 1e-3
G4_IMPROVE = 0.98          # calibrated log loss at most this times the constant model's
G4_FLOOR = 0.99            # and at least this times the log loss of the true probabilities
G8_ABS = 0.05              # each decile within this of the predicted rate, or within 5 binomial sd if larger
G8_SD = 5.0
G8_MIN_ROWS = 1000
FIT_BEFORE, CALIB_BEFORE = 60, 78
SEED = 20261112
TABLES = "core,dispensing,refills"
OUT_FILES = ["items.csv", "pharmacies.csv", "patients.csv", "truth.json", "dispensing.csv", "truth/demand.csv", "refills.csv", "truth/refill_hazard.csv"]
# what the model sees: the label is the target; the keys, the time and the text labels are dropped, and so is `fills_before`, which `ml` itself reports out of the training range
# on three quarters of the test rows (it grows with time), a reason given before the test metrics were looked at as a judgement, not after.
DROP = "patient,item,due_week,copay_band,age_band,fills_before"
FACTORS = ("n_items", "copay_band", "age_band", "stockout_seen")


def world(fl, tag, zero):
    w = json.loads((HERE / "world.json").read_text())
    if zero:
        P = w["params"]
        P["lapse_per_extra_item_ppm"]["value"] = 0
        P["lapse_copay_ppm"]["value"] = [0, 0, 0]
        P["lapse_age_ppm"]["value"] = [0, 0, 0, 0, 0]
        P["lapse_stockout_ppm"]["value"] = 0
    (fl.root / ("world_%s.json" % tag)).write_text(json.dumps(w))


def run_steps(fl, factors=FACTORS):
    tb = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]
    for tag, zero in (("main", False), ("zero", True)):
        world(fl, tag, zero)
        d = "data_" + tag
        fl.step(pc.TWIN_FILES + ["world_%s.json" % tag], ["%s/%s" % (d, f) for f in OUT_FILES],
                ["python3", "twin.py", "generate", "--world", "world_%s.json" % tag, "--seed", str(SEED), "--size", "large", "--tables", TABLES, "--out", d])
        fl.step(["features_b.py", d + "/refills.csv", d + "/patients.csv"], ["events_%s.csv" % tag], ["python3", "features_b.py", d, "events_%s.csv" % tag])
        for f in factors:
            fl.step(["events_%s.csv" % tag], [], ["stats", "--root", ".", "test", "chisq", "--cols", "lapsed", "--vs", f, "events_%s.csv" % tag], stdout_file="chisq_%s_%s.json" % (tag, f))
    fl.step(["events_main.csv"], ["fit.csv"], tb + ["fit.csv", "--where", "due_week:int < %d" % FIT_BEFORE, "events_main.csv"])
    fl.step(["events_main.csv"], ["calib.csv"], tb + ["calib.csv", "--where", "due_week:int >= %d and due_week:int < %d" % (FIT_BEFORE, CALIB_BEFORE), "events_main.csv"])
    fl.step(["events_main.csv"], ["test.csv"], tb + ["test.csv", "--where", "due_week:int >= %d" % CALIB_BEFORE, "events_main.csv"])
    fl.step(["fit.csv"], ["m_const.ml"], ["ml", "--root", ".", "--model", "constant", "--target", "lapsed", "--drop", DROP, "--output", "m_const.ml", "fit", "fit.csv"], stdout_file="fit_const.json")
    fl.step(["fit.csv"], ["m_boost.ml"], ["ml", "--root", ".", "--model", "boost", "--task", "classification", "--positive", "1", "--target", "lapsed", "--drop", DROP, "--output", "m_boost.ml", "fit", "fit.csv"],
            stdout_file="fit_boost.json")
    for part in ("calib", "test"):
        fl.step(["m_boost.ml", part + ".csv"], [], ["ml", "--root", ".", "--model-file", "m_boost.ml", "--drop", DROP, "--proba", "--limit", "1000000", "predict", part + ".csv"], stdout_file="pred_%s.json" % part, max_output=33554432)
        fl.step(["pred_join.py", part + ".csv", "pred_%s.json" % part], ["pred_%s.csv" % part], ["python3", "pred_join.py", part + ".csv", "pred_%s.json" % part, "pred_%s.csv" % part])
    fl.step(["pred_calib.csv"], [], ["ml", "--root", ".", "--x-col", "p", "--y-col", "lapsed", "isotonic", "pred_calib.csv"], stdout_file="iso.json")
    fl.step(["apply_isotonic.py", "iso.json", "pred_test.csv"], ["test_cal.csv"], ["python3", "apply_isotonic.py", "iso.json", "pred_test.csv", "test_cal.csv"])
    fl.step(["pred_test.csv"], [], ["ml", "--root", ".", "--prob-col", "p", "--target", "lapsed", "calibrate", "pred_test.csv"], stdout_file="calibrate_raw.json")
    fl.step(["test_cal.csv"], [], ["ml", "--root", ".", "--prob-col", "p", "--target", "lapsed", "calibrate", "test_cal.csv"], stdout_file="calibrate_cal.json")


def logloss(pairs):
    eps = 1e-12
    return -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)) for y, p in pairs) / len(pairs)


def deciles(rows):
    """rows: (p, y) pairs; ten groups of equal size by rank of p. Returns (mean p, observed, n, bound) for each."""
    rows = sorted(rows, key=lambda t: t[0])
    n, out = len(rows), []
    for k in range(10):
        part = rows[k * n // 10:(k + 1) * n // 10]
        mp, ob = sum(p for p, _ in part) / len(part), sum(y for _, y in part) / len(part)
        out.append((mp, ob, len(part), max(G8_ABS, G8_SD * math.sqrt(mp * (1 - mp) / len(part)))))
    return out


def judge(fl, factors=FACTORS):
    problems, report = [], []
    J = lambda rel: json.loads(fl.read(rel))
    # ---- G2 ----
    for f in factors:
        pm = J("chisq_main_%s.json" % f)["data"]["tests"][0]["p_value"]
        pz = J("chisq_zero_%s.json" % f)["data"]["tests"][0]["p_value"]
        report.append("G2 %-14s p = %.2e in the twin, %.3f in the control with the effect at zero" % (f, pm, pz))
        if not pm < G2_P_FOUND:
            problems.append("G2: the effect of %s was not found (p = %.2e, wanted < %g)" % (f, pm, G2_P_FOUND))
        if not pz >= G2_P_ABSENT:
            problems.append("G2: an effect of %s was found in the control where there is none (p = %.2e, wanted >= %g)" % (f, pz, G2_P_ABSENT))
    # ---- split hygiene ----
    def keys(rel):
        return {(r["patient"], r["item"], r["due_week"]) for r in pc.table(fl.read(rel))}
    def weeks(rel):
        ws = [int(r["due_week"]) for r in pc.table(fl.read(rel))]
        return min(ws), max(ws)
    (f0, f1), (c0, c1), (t0, t1) = weeks("fit.csv"), weeks("calib.csv"), weeks("test.csv")
    shared = len(keys("fit.csv") & keys("calib.csv")) + len(keys("fit.csv") & keys("test.csv")) + len(keys("calib.csv") & keys("test.csv"))
    report.append("G4 split hygiene: fit weeks %d to %d, calibration %d to %d, test %d to %d, %d rows in two files" % (f0, f1, c0, c1, t0, t1, shared))
    if not (f1 < c0 and c1 < t0) or shared:
        problems.append("G4: the fit, calibration and test weeks overlap (%d-%d, %d-%d, %d-%d, %d shared rows): the later weeks leaked into the earlier files" % (f0, f1, c0, c1, t0, t1, shared))
    # ---- G4 ----
    test = [(float(r["p"]), int(r["lapsed"]), r["patient"], r["item"], r["due_week"]) for r in pc.table(fl.read("test_cal.csv"))]
    truth = {(r["patient"], r["item"], r["due_week"]): int(r["true_lapse_ppm"]) / 1e6 for r in pc.table(fl.read("data_main/truth/refill_hazard.csv"))}
    base_rate = float(J("fit_const.json")["data"]["summary"]["mean"])
    ll_cal = logloss([(y, p) for p, y, *_ in test])
    ll_raw = logloss([(int(r["lapsed"]), float(r["p_raw"])) for r in pc.table(fl.read("test_cal.csv"))])
    ll_const = logloss([(y, base_rate) for _, y, *_ in test])
    ll_true = logloss([(y, truth[(pa, it, w)]) for _, y, pa, it, w in test])
    report.append("G4 test rows %d: log loss: constant %.5f, boost uncalibrated %.5f, boost calibrated %.5f, the true probabilities %.5f" % (len(test), ll_const, ll_raw, ll_cal, ll_true))
    report.append("G4 calibrated boost: %.4f of the constant model's log loss (limit %.2f), %.4f of the true probabilities' (lower limit %.2f)" % (ll_cal / ll_const, G4_IMPROVE, ll_cal / ll_true, G4_FLOOR))
    if ll_cal > G4_IMPROVE * ll_const:
        problems.append("G4: the calibrated boost's log loss %.5f is not at most %.2f times the constant model's %.5f" % (ll_cal, G4_IMPROVE, ll_const))
    if ll_cal < G4_FLOOR * ll_true:
        problems.append("G4: the calibrated boost's log loss %.5f is below %.2f times the true probabilities' %.5f: it has seen something it should not" % (ll_cal, G4_FLOOR, ll_true))
    # ---- G8 ----
    cal, raw = deciles([(p, y) for p, y, *_ in test]), deciles([(float(r["p_raw"]), int(r["lapsed"])) for r in pc.table(fl.read("test_cal.csv"))])
    worst = max(abs(m - o) / b for m, o, _, b in cal)
    worst_raw = max(abs(m - o) / b for m, o, _, b in raw)
    report.append("G8 deciles of the calibrated probability (predicted, observed): " + ", ".join("%.3f/%.3f" % (m, o) for m, o, _, _ in cal))
    report.append("G8 largest deviation as a share of its bound: %.2f calibrated, %.2f uncalibrated (not judged); the smallest decile has %d rows" % (worst, worst_raw, min(n for _, _, n, _ in cal)))
    if min(n for _, _, n, _ in cal) < G8_MIN_ROWS:
        problems.append("G8: a decile has fewer than %d rows" % G8_MIN_ROWS)
    for k, (m, o, n, b) in enumerate(cal):
        if abs(m - o) > b:
            problems.append("G8: decile %d: predicted %.4f, observed %.4f over %d rows, outside %.4f" % (k, m, o, n, b))
    cj = J("calibrate_cal.json")["data"]
    report.append("ml calibrate (its own gate, defaults) on the calibrated probabilities: ok=%s, overall ratio %.3f; on the uncalibrated: ok=%s, overall ratio %.3f" % (
        cj.get("ok"), float(cj["overall_ratio"]), J("calibrate_raw.json")["data"].get("ok"), float(J("calibrate_raw.json")["data"]["overall_ratio"])))
    p7, r7 = pc.judge_records(fl, "events_main.csv")
    return problems + p7, report + r7


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        for f in ("features_b.py", "pred_join.py", "apply_isotonic.py"):
            shutil.copy(HERE / f, fl.root / f)
        run_steps(fl)
        out = judge(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return out


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("label-in-a-feature", "features_b.py", 'p["copay_band"]), p["copay_band"],', _x('1 - int(r["fil', 'led"]), p["copay_band"],'), "G4"),
    ("calibration-inverted", "scripts/pipeline_b.py", _x('"--x-col", "p", "--y-col", "lapsed", "iso', 'tonic"'), '"--x-col", "p", "--y-col", "lapsed", "--decreasing", "isotonic"', "G8"),
    ("later-weeks-in-the-fit", "scripts/pipeline_b.py", _x('"due_week:int < %d" % FIT_', 'BEFORE'), _x('"due_week:int < %d" % (FIT_', 'BEFORE + 30)'), "G4"),
    ("stockout-tested-against-the-wrong-column", "scripts/pipeline_b.py", _x('FACTORS = ("n_items", "copay_band", "age_band", "stock', 'out_seen")'), 'FACTORS = ("n_items", "copay_band", "age_band", "interval_weeks")', "G2"),
    ("coupling-ignored-by-the-twin", "twinlib/core.py", 'p["lapse_stockout_ppm"] * seen', "0 * seen", "G2"),
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
                print("mutant %-42s CANNOT BE APPLIED (%d occurrences in %s)" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            env = dict(os.environ, FLOW_REPO=str(pc.REPO), TABLE=pc.exe("table", "TABLE"), STATS=pc.exe("stats", "STATS"), ML=pc.exe("ml", "ML"), SOLVE=pc.exe("solve", "SOLVE"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "pipeline_b.py")], capture_output=True, text=True, env=env, cwd=td, timeout=3600)
            out = r.stdout + r.stderr
            if only:
                print(out[-2500:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-42s by %s" % (name, hit[0][:130]))
            else:
                survived += 1
                print("SURVIVED %-42s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
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
    print("pipeline_b: ok (G2, G4, G8 and G7 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
