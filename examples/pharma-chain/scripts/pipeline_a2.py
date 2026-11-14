#!/usr/bin/env python3
"""U4b: A's models, as recorded `flow` steps, and G4, G8 for A and G7 (docs/use-cases.md, margins of 7a for U4b, committed before the models were built).

    CANCHO=<compiler> python3 scripts/pipeline_a2.py [--mutants] [--mutant NAME] [--keep DIR]

The large size, the twin as it is. Route energy: a boost against a linear fit on the distance alone, fit on days before 546, tested from 546. Excursion of a stop: a boost, calibrated by `ml isotonic`,
fit before day 364, calibrated on 364 to 545, tested from 546. Every step is a recorded `flow` step.
"""
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
import pipeline_a as pa  # noqa: E402
import pipeline_c as pc  # noqa: E402

# --- the margins of docs/use-cases.md section 7a (G4 and G8 for A), fixed before the models were built ---
E_IMPROVE = 0.80        # boost MAE at most this times the distance-only baseline's, on the same test routes
E_FLOOR = 0.95          # and at least this times the noise floor (a model that knew the parts of every stop)
X_IMPROVE = 0.985       # calibrated log loss at most this times the constant model's
X_FLOOR = 0.97          # and at least this times the log loss of the true probabilities
G8_ABS, G8_SD, G8_GROUPS = 0.05, 5.0, 5
FIT_E, TEST_FROM = 546, 546
FIT_X, CAL_X = 364, 546
KEYS = "route,seq"
LABEL = "excursion"
X_DROP = "route,day,pharmacy,temp_band,door_band,energy_wh,wh_per_min"
E_DROP = "route,day"
E_BASE_DROP = "route,day,stops,temp_c,span_min"


def run_steps(fl):
    tb = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]
    pa.world(fl, "main", None)
    d = "data_main"
    fl.step(pa.TWIN + ["world_main.json"], ["%s/%s" % (d, f) for f in pa.DEL_FILES],
            ["python3", "twin.py", "generate", "--world", "world_main.json", "--seed", str(pa.SEED), "--size", "large", "--tables", "core,delivery", "--out", d])
    fl.step(["features_a.py", d + "/routes.csv", d + "/telemetry.csv", d + "/days.csv"], ["stops.csv"], ["python3", "features_a.py", d, "stops.csv"])
    fl.step(["features_a2.py", d + "/routes.csv", d + "/telemetry.csv"], ["routes_e.csv"], ["python3", "features_a2.py", d, "routes_e.csv"])
    # ---- route energy ----
    fl.step(["routes_e.csv"], ["fit_e.csv"], tb + ["fit_e.csv", "--where", "day:int < %d" % FIT_E, "routes_e.csv"])
    fl.step(["routes_e.csv"], ["test_e.csv"], tb + ["test_e.csv", "--where", "day:int >= %d" % TEST_FROM, "routes_e.csv"])
    fl.step(["fit_e.csv"], ["m_base.ml"], ["ml", "--root", ".", "--model", "linear", "--target", "energy_wh", "--drop", E_BASE_DROP, "--output", "m_base.ml", "fit", "fit_e.csv"], stdout_file="fit_base.json")
    fl.step(["fit_e.csv"], ["m_eboost.ml"], ["ml", "--root", ".", "--model", "boost", "--target", "energy_wh", "--drop", E_DROP, "--output", "m_eboost.ml", "fit", "fit_e.csv"], stdout_file="fit_eboost.json")
    fl.step(["m_base.ml", "test_e.csv"], [], ["ml", "--root", ".", "--model-file", "m_base.ml", "--drop", E_BASE_DROP, "eval", "test_e.csv"], stdout_file="eval_base.json")
    fl.step(["m_eboost.ml", "test_e.csv"], [], ["ml", "--root", ".", "--model-file", "m_eboost.ml", "--drop", E_DROP, "eval", "test_e.csv"], stdout_file="eval_eboost.json")
    # ---- excursion ----
    fl.step(["stops.csv"], ["fit_x.csv"], tb + ["fit_x.csv", "--where", "day:int < %d" % FIT_X, "stops.csv"])
    fl.step(["stops.csv"], ["cal_x.csv"], tb + ["cal_x.csv", "--where", "day:int >= %d and day:int < %d" % (FIT_X, CAL_X), "stops.csv"])
    fl.step(["stops.csv"], ["test_x.csv"], tb + ["test_x.csv", "--where", "day:int >= %d" % TEST_FROM, "stops.csv"])
    fl.step(["fit_x.csv"], ["m_const.ml"], ["ml", "--root", ".", "--model", "constant", "--target", LABEL, "--drop", X_DROP, "--output", "m_const.ml", "fit", "fit_x.csv"], stdout_file="fit_const.json")
    fl.step(["fit_x.csv"], ["m_xboost.ml"], ["ml", "--root", ".", "--model", "boost", "--task", "classification", "--positive", "1", "--target", LABEL, "--drop", X_DROP, "--output", "m_xboost.ml", "fit", "fit_x.csv"],
            stdout_file="fit_xboost.json")
    for part in ("cal", "test"):
        fl.step(["m_xboost.ml", part + "_x.csv"], [], ["ml", "--root", ".", "--model-file", "m_xboost.ml", "--drop", X_DROP, "--proba", "--limit", "1000000", "predict", part + "_x.csv"],
                stdout_file="pred_%s.json" % part, max_output=33554432)
        fl.step(["pred_join_g.py", part + "_x.csv", "pred_%s.json" % part], ["pred_%s.csv" % part], ["python3", "pred_join_g.py", part + "_x.csv", "pred_%s.json" % part, "pred_%s.csv" % part, LABEL, KEYS])
    fl.step(["pred_cal.csv"], [], ["ml", "--root", ".", "--x-col", "p", "--y-col", LABEL, "isotonic", "pred_cal.csv"], stdout_file="iso.json")
    fl.step(["apply_isotonic_g.py", "iso.json", "pred_test.csv"], ["test_cal.csv"], ["python3", "apply_isotonic_g.py", "iso.json", "pred_test.csv", "test_cal.csv", LABEL, KEYS])
    fl.step(["pred_test.csv"], [], ["ml", "--root", ".", "--prob-col", "p", "--target", LABEL, "calibrate", "pred_test.csv"], stdout_file="calibrate_raw.json")
    fl.step(["test_cal.csv"], [], ["ml", "--root", ".", "--prob-col", "p", "--target", LABEL, "calibrate", "test_cal.csv"], stdout_file="calibrate_cal.json")


def groups(rows):
    """rows: (p, y); G8_GROUPS groups of equal size by rank of p. Returns (mean p, observed, n, bound)."""
    rows = sorted(rows, key=lambda t: t[0])
    n, out = len(rows), []
    for k in range(G8_GROUPS):
        part = rows[k * n // G8_GROUPS:(k + 1) * n // G8_GROUPS]
        mp, ob = sum(p for p, _ in part) / len(part), sum(y for _, y in part) / len(part)
        out.append((mp, ob, len(part), max(G8_ABS, G8_SD * math.sqrt(mp * (1 - mp) / len(part)))))
    return out


def logloss(pairs):
    eps = 1e-12
    return -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)) for y, p in pairs) / len(pairs)


def judge(fl):
    problems, report = [], []
    J = lambda rel: json.loads(fl.read(rel))
    T = pc.table
    # ---- split hygiene ----
    def days(rel):
        ds = [int(r["day"]) for r in T(fl.read(rel))]
        return min(ds), max(ds)
    def keys_of(rel, cols):
        return {tuple(r[c] for c in cols) for r in T(fl.read(rel))}
    (a0, a1), (b0, b1), (c0, c1), (e0, e1) = days("fit_x.csv"), days("cal_x.csv"), days("test_x.csv"), days("fit_e.csv")
    sh = len(keys_of("fit_x.csv", ("route", "seq")) & keys_of("cal_x.csv", ("route", "seq"))) + len(keys_of("fit_x.csv", ("route", "seq")) & keys_of("test_x.csv", ("route", "seq"))) + len(keys_of("cal_x.csv", ("route", "seq")) & keys_of("test_x.csv", ("route", "seq")))
    she = len(keys_of("fit_e.csv", ("route",)) & keys_of("test_e.csv", ("route",)))
    t0 = days("test_e.csv")[0]
    report.append("G4 split hygiene: excursion fit days %d to %d, calibration %d to %d, test %d to %d, %d rows in two files; energy fit days %d to %d, test from %d, %d routes in both" % (a0, a1, b0, b1, c0, c1, sh, e0, e1, t0, she))
    if not (a1 < b0 and b1 < c0) or sh or not (e1 < t0) or she:
        problems.append("G4: the fit, calibration and test days overlap or share rows (excursion %d-%d, %d-%d, %d-%d, %d shared; energy fit to %d, test from %d, %d shared): later days leaked into earlier files" % (a0, a1, b0, b1, c0, c1, sh, e1, t0, she))
    # ---- G4 energy ----
    mae_base = float(J("eval_base.json")["data"]["metrics"]["mae"])
    mae_boost = float(J("eval_eboost.json")["data"]["metrics"]["mae"])
    tele = {(r["route"], r["seq"]): r for r in T(fl.read("data_main/telemetry.csv"))}
    parts = {}
    for t, p in zip(T(fl.read("data_main/telemetry.csv")), T(fl.read("data_main/truth/energy_parts.csv"))):
        a, b = parts.get(t["route"], (0, 0))
        parts[t["route"]] = (a + int(t["energy_wh"]), b + int(p["drive_wh"]) + int(p["fridge_wh"]) + int(p["door_wh"]))
    test_routes = [r["route"] for r in T(fl.read("test_e.csv"))]
    floor = sum(abs(parts[r][0] - parts[r][1]) for r in test_routes) / len(test_routes)
    report.append("G4 route energy, %d test routes (Wh): linear on the distance %.0f, boost %.0f (%.3f of the baseline, limit %.2f), noise floor %.0f (boost %.3f of it, lower limit %.2f)" % (
        len(test_routes), mae_base, mae_boost, mae_boost / mae_base, E_IMPROVE, floor, mae_boost / floor, E_FLOOR))
    if mae_boost > E_IMPROVE * mae_base:
        problems.append("G4: the energy boost's MAE %.0f is not at most %.2f times the distance-only baseline's %.0f" % (mae_boost, E_IMPROVE, mae_base))
    if mae_boost < E_FLOOR * floor:
        problems.append("G4: the energy boost's MAE %.0f is below %.2f times the noise floor %.0f: it has seen something it should not" % (mae_boost, E_FLOOR, floor))
    # ---- G4 excursion ----
    test = [(float(r["p"]), int(r[LABEL]), r["route"], r["seq"]) for r in T(fl.read("test_cal.csv"))]
    truth = {(r["route"], r["seq"]): int(r["true_ppm"]) / 1e6 for r in T(fl.read("data_main/truth/excursion.csv"))}
    base_rate = float(J("fit_const.json")["data"]["summary"]["mean"])
    ll_cal = logloss([(y, p) for p, y, *_ in test])
    ll_raw = logloss([(int(r[LABEL]), float(r["p_raw"])) for r in T(fl.read("test_cal.csv"))])
    ll_const = logloss([(y, base_rate) for _, y, *_ in test])
    ll_true = logloss([(y, truth[(ro, se)]) for _, y, ro, se in test])
    report.append("G4 excursion, %d test stops: log loss: constant %.5f, boost uncalibrated %.5f, boost calibrated %.5f, the true probabilities %.5f" % (len(test), ll_const, ll_raw, ll_cal, ll_true))
    report.append("G4 calibrated boost: %.4f of the constant model's log loss (limit %.3f), %.4f of the true probabilities' (lower limit %.2f)" % (ll_cal / ll_const, X_IMPROVE, ll_cal / ll_true, X_FLOOR))
    if ll_cal > X_IMPROVE * ll_const:
        problems.append("G4: the calibrated boost's log loss %.5f is not at most %.3f times the constant model's %.5f" % (ll_cal, X_IMPROVE, ll_const))
    if ll_cal < X_FLOOR * ll_true:
        problems.append("G4: the calibrated boost's log loss %.5f is below %.2f times the true probabilities' %.5f: it has seen something it should not" % (ll_cal, X_FLOOR, ll_true))
    # ---- G8 ----
    cal, raw = groups([(p, y) for p, y, *_ in test]), groups([(float(r["p_raw"]), int(r[LABEL])) for r in T(fl.read("test_cal.csv"))])
    report.append("G8 %d groups of the calibrated probability (predicted/observed, rows): " % G8_GROUPS + ", ".join("%.3f/%.3f (%d)" % (m, o, n) for m, o, n, _ in cal))
    report.append("G8 largest deviation as a share of its bound: %.2f calibrated, %.2f uncalibrated (not judged)" % (max(abs(m - o) / b for m, o, _, b in cal), max(abs(m - o) / b for m, o, _, b in raw)))
    for k, (m, o, n, b) in enumerate(cal):
        if abs(m - o) > b:
            problems.append("G8: group %d: predicted %.4f, observed %.4f over %d rows, outside %.4f" % (k, m, o, n, b))
    p7, r7 = pc.judge_records(fl, "stops.csv")
    return problems + p7, report + r7


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        for f in ("features_a.py", "features_a2.py", "pred_join_g.py", "apply_isotonic_g.py"):
            shutil.copy(HERE / f, fl.root / f)
        shutil.copy(HERE / "twinlib" / "delivery.py", fl.root / "twinlib" / "delivery.py")
        run_steps(fl)
        out = judge(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return out


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("holdout-in-the-energy-fit", "scripts/pipeline_a2.py", _x('"day:int < %d" % FIT', '_E, "routes_e.csv"'), '"day:int < %d" % (FIT_E + 400), "routes_e.csv"', "G4"),
    ("holdout-in-the-excursion-fit", "scripts/pipeline_a2.py", _x('"day:int < %d" % FIT', '_X, "stops.csv"'), '"day:int < %d" % (FIT_X + 300), "stops.csv"', "G4"),
    ("door-minutes-dropped-from-the-excursion-model", "scripts/pipeline_a2.py", _x('X_DROP = "route,day,pharmacy,temp_band,door_band,energy_wh', ',wh_per_min"'), 'X_DROP = "route,day,pharmacy,temp_band,door_band,energy_wh,wh_per_min,door_min"', "G4"),
    ("distance-dropped-from-the-energy-model", "scripts/pipeline_a2.py", _x('E_DROP = "route', ',day"'), 'E_DROP = "route,day,distance_km"', "G4"),
    ("calibration-inverted", "scripts/pipeline_a2.py", _x('"--x-col", "p", "--y-col", LABEL, "iso', 'tonic"'), '"--x-col", "p", "--y-col", LABEL, "--decreasing", "isotonic"', "G4"),
    ("label-as-a-feature", "features_a.py", _x('w.writerow([r["route"], r["seq"], d, r["pharmacy"], t, temp_band(t), door, door_band(door), mins, wh, "%d.%02d" % (per // 100, per % 100), ', 'int(int(r["cabin_temp_dc"]) > 80)])'), 'w.writerow([r["route"], r["seq"], d, r["pharmacy"], t, temp_band(t), door, door_band(door), mins, wh, "%d.%02d" % (per // 100, per % 100), int(int(r["cabin_temp_dc"]) > 80)])', "G4"),
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
                print("mutant %-48s CANNOT BE APPLIED (%d occurrences in %s)" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            env = dict(os.environ, FLOW_REPO=str(pc.REPO), TABLE=pc.exe("table", "TABLE"), STATS=pc.exe("stats", "STATS"), ML=pc.exe("ml", "ML"), SOLVE=pc.exe("solve", "SOLVE"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "pipeline_a2.py")], capture_output=True, text=True, env=env, cwd=td, timeout=3600)
            out = r.stdout + r.stderr
            if only:
                print(out[-2500:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-48s by %s" % (name, hit[0][:130]))
            else:
                survived += 1
                print("SURVIVED %-48s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
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
    print("pipeline_a2: ok (G4, G8 and G7 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
