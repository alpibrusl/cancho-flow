#!/usr/bin/env python3
"""U5: a week of the whole chain, one command (docs/use-cases.md section 7a, G13 to G17, committed before this was written).

    CANCHO=<compiler> [SCIPY_PYTHON=<a python with scipy>] python3 scripts/loop.py [--runs N] [--keep DIR] [--mutants] [--mutant NAME]

The large, coupled twin (seed 20261112), then for week 100: C (the forecast and the 20 replenishment decisions), B (the lapse model and the 20 outreach decisions), A (the route-energy model and the charging plan of each night of days 700 to 706),
then the summary; every step is a recorded `flow` step. By default the whole thing runs twice at once in fresh directories (G13: the summary and the records are byte for byte equal) and the first run is judged (G14 to G17).
The decisions are checked but do not change the twin's world: the loop is closed in the data and open in the decisions (section 7a).
"""
import csv
import glob
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scripts"))
import pipeline_a as pa  # noqa: E402
import pipeline_b as pb  # noqa: E402
import pipeline_c as pc  # noqa: E402

WEEK, DAY0, DAY1 = 100, 700, 706
C_FIT_FROM, B_FIT_BEFORE = 48, 74
SEED = 20261112
NODE_LIMIT = "20000"
OUTS = ["items.csv", "pharmacies.csv", "patients.csv", "truth.json", "dispensing.csv", "truth/demand.csv", "refills.csv", "truth/refill_hazard.csv", "trucks.csv", "locations.csv", "days.csv", "deliveries.csv",
        "routes.csv", "telemetry.csv", "depot.csv", "truth/energy_parts.csv", "truth/excursion.csv", "truth/coupling.csv"]
HELPERS = ("features_b.py", "features_a2.py", "pred_join.py", "apply_isotonic.py", "pred_routes.py", "build_models.py", "build_outreach.py", "build_charging.py", "verify_input.py", "costs.json", "outreach.json", "charging.json", "loop_summary.py")
THREADS = os.environ.get("LOOP_ML_THREADS")  # U6: every `ml fit` with --threads N (default: the tool's own, 1)


def thr():
    return ["--threads", THREADS] if THREADS else []


TB = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]


def solve_chain(fl, base):
    fl.step([base + ".sol"], [], ["solve", "run", "--node-limit", NODE_LIMIT], stdin_file=base + ".sol", stdout_file=base + ".plan.json", allow_failure=True)
    fl.step(["verify_input.py", base + ".sol", base + ".plan.json"], [base + ".verify.in"], ["python3", "verify_input.py", base + ".sol", base + ".plan.json", base + ".verify.in"])
    fl.step([], [], ["solve", "verify"], stdin_file=base + ".verify.in", stdout_file=base + ".verify.json")


def run_steps(fl):
    fl.stage = {}
    mark = [time.time()]

    def done(name):
        now = time.time()
        fl.stage[name] = now - mark[0]
        mark[0] = now
    pa.world(fl, "main", None)
    fl.step(pa.TWIN + ["world_main.json"], ["data/" + f for f in OUTS],
            ["python3", "twin.py", "generate", "--world", "world_main.json", "--seed", str(SEED), "--size", "large", "--tables", "core,dispensing,refills,delivery,coupled", "--out", "data"])
    done("twin")
    # ---- C: the forecast and the replenishment decisions of the week ----
    fl.step(["features.py", "data/dispensing.csv", "data/items.csv", "data/pharmacies.csv"], ["c_feat.csv"], ["python3", "features.py", "data", "c_feat.csv"])
    fl.step(["c_feat.csv"], ["c_train.csv"], TB + ["c_train.csv", "--where", "week:int >= %d and week:int < %d" % (C_FIT_FROM, WEEK), "c_feat.csv"])
    fl.step(["c_feat.csv"], ["c_test.csv"], TB + ["c_test.csv", "--where", "week:int = %d" % WEEK, "c_feat.csv"])
    drop = "pharmacy,item,week"
    fl.step(["c_train.csv"], ["c_model.ml"], ["ml", "--root", ".", "--model", "boost", "--cat", "group,season", "--step", "encode column=group,season kind=onehot", "--target", "units", "--drop", drop, "--output", "c_model.ml", "fit", "c_train.csv"] + thr(),
            stdout_file="c_fit.json")
    fl.step(["c_model.ml", "c_test.csv"], [], ["ml", "--root", ".", "--model-file", "c_model.ml", "--drop", drop, "--limit", "6000", "predict", "c_test.csv"], stdout_file="c_pred.json")
    phs = sorted({r["pharmacy"] for r in pc.table(fl.read("c_test.csv"))})
    for ph in phs:
        b = "c/models/W%d_%s" % (WEEK, ph)
        fl.step(["build_models.py", "data/dispensing.csv", "data/items.csv", "data/pharmacies.csv", "c_test.csv", "c_pred.json", "costs.json"], [b + ".sol", b + ".json"],
                ["python3", "build_models.py", "--only", "%d:%s" % (WEEK, ph), "data", "c_test.csv", "c_pred.json", "costs.json", "c"])
        solve_chain(fl, b)
    fl.step(["loop_summary.py"] + ["c/models/W%d_%s.%s" % (WEEK, ph, e) for ph in phs for e in ("json", "plan.json")], ["c_summary.json"], ["python3", "loop_summary.py", "c", str(WEEK), ".", "c_summary.json"])
    done("C")
    # ---- B: the lapse model and the outreach decisions of the week ----
    fl.step(["features_b.py", "data/refills.csv", "data/patients.csv"], ["b_events.csv"], ["python3", "features_b.py", "data", "b_events.csv"])
    fl.step(["b_events.csv"], ["b_fit.csv"], TB + ["b_fit.csv", "--where", "due_week:int < %d" % B_FIT_BEFORE, "b_events.csv"])
    fl.step(["b_events.csv"], ["b_cal.csv"], TB + ["b_cal.csv", "--where", "due_week:int >= %d and due_week:int < %d" % (B_FIT_BEFORE, WEEK), "b_events.csv"])
    fl.step(["b_events.csv"], ["b_test.csv"], TB + ["b_test.csv", "--where", "due_week:int = %d" % WEEK, "b_events.csv"])
    fl.step(["b_fit.csv"], ["b_model.ml"], ["ml", "--root", ".", "--model", "boost", "--task", "classification", "--positive", "1", "--target", "lapsed", "--drop", pb.DROP, "--output", "b_model.ml", "fit", "b_fit.csv"] + thr(), stdout_file="b_fit.json")
    for part in ("cal", "test"):
        fl.step(["b_model.ml", "b_%s.csv" % part], [], ["ml", "--root", ".", "--model-file", "b_model.ml", "--drop", pb.DROP, "--proba", "--limit", "1000000", "predict", "b_%s.csv" % part], stdout_file="b_pred_%s.json" % part, max_output=33554432)
        fl.step(["pred_join.py", "b_%s.csv" % part, "b_pred_%s.json" % part], ["b_pred_%s.csv" % part], ["python3", "pred_join.py", "b_%s.csv" % part, "b_pred_%s.json" % part, "b_pred_%s.csv" % part])
    fl.step(["b_pred_cal.csv"], [], ["ml", "--root", ".", "--x-col", "p", "--y-col", "lapsed", "isotonic", "b_pred_cal.csv"], stdout_file="b_iso.json")
    fl.step(["apply_isotonic.py", "b_iso.json", "b_pred_test.csv"], ["b_test_cal.csv"], ["python3", "apply_isotonic.py", "b_iso.json", "b_pred_test.csv", "b_test_cal.csv"])
    home = {r["patient"]: r["home_pharmacy"] for r in pc.table(fl.read("data/patients.csv"))}
    bphs = sorted({home[r["patient"]] for r in pc.table(fl.read("b_test_cal.csv"))})
    for ph in bphs:
        b = "b/models/W%d_%s" % (WEEK, ph)
        fl.step(["build_outreach.py", "b_test_cal.csv", "data/patients.csv", "outreach.json"], [b + ".sol", b + ".json"], ["python3", "build_outreach.py", "--only", "%d:%s" % (WEEK, ph), "b_test_cal.csv", "data", "outreach.json", "b"])
        solve_chain(fl, b)
    fl.step(["loop_summary.py"] + ["b/models/W%d_%s.%s" % (WEEK, ph, e) for ph in bphs for e in ("json", "plan.json")], ["b_summary.json"], ["python3", "loop_summary.py", "b", str(WEEK), ".", "b_summary.json"])
    done("B")
    # ---- A: the route-energy model and the charging plan of each night ----
    fl.step(["features_a2.py", "data/routes.csv", "data/telemetry.csv"], ["a_routes.csv"], ["python3", "features_a2.py", "data", "a_routes.csv"])
    fl.step(["a_routes.csv"], ["a_fit.csv"], TB + ["a_fit.csv", "--where", "day:int < %d" % DAY0, "a_routes.csv"])
    fl.step(["a_routes.csv"], ["a_test.csv"], TB + ["a_test.csv", "--where", "day:int >= %d and day:int <= %d" % (DAY0, DAY1), "a_routes.csv"])
    fl.step(["a_fit.csv"], ["a_base.ml"], ["ml", "--root", ".", "--model", "linear", "--target", "energy_wh", "--drop", "route,day,stops,temp_c,span_min", "--output", "a_base.ml", "fit", "a_fit.csv"] + thr(), stdout_file="a_fit_base.json")
    fl.step(["a_fit.csv"], ["a_boost.ml"], ["ml", "--root", ".", "--model", "boost", "--target", "energy_wh", "--drop", "route,day", "--output", "a_boost.ml", "fit", "a_fit.csv"] + thr(), stdout_file="a_fit_boost.json")
    fl.step(["a_boost.ml", "a_test.csv"], [], ["ml", "--root", ".", "--model-file", "a_boost.ml", "--drop", "route,day", "--limit", "1000000", "predict", "a_test.csv"], stdout_file="a_pred_boost.json", max_output=33554432)
    fl.step(["a_base.ml", "a_test.csv"], [], ["ml", "--root", ".", "--model-file", "a_base.ml", "--drop", "route,day,stops,temp_c,span_min", "--limit", "1000000", "predict", "a_test.csv"], stdout_file="a_pred_base.json", max_output=33554432)
    fl.step(["pred_routes.py", "a_test.csv", "a_pred_boost.json", "a_pred_base.json"], ["a_pred.csv"], ["python3", "pred_routes.py", "a_test.csv", "a_pred_boost.json", "a_pred_base.json", "a_pred.csv"])
    days = sorted({int(r["day"]) for r in pc.table(fl.read("a_test.csv"))})
    for dd in days:
        b = "a/models/D%d" % dd
        fl.step(["build_charging.py", "data/routes.csv", "data/telemetry.csv", "data/depot.csv", "a_pred.csv", "charging.json"], [b + ".sol", b + ".json"],
                ["python3", "build_charging.py", str(dd), "data", "a_pred.csv", "charging.json", "a"])
        solve_chain(fl, b)
    fl.step(["loop_summary.py"] + ["a/models/D%d.%s" % (dd, e) for dd in days for e in ("json", "plan.json")], ["a_summary.json"], ["python3", "loop_summary.py", "a", str(DAY0), str(DAY1), ".", "a_summary.json"])
    done("A")
    # ---- the coupling in the week, and the summary ----
    fl.step(["loop_summary.py", "data/routes.csv", "data/telemetry.csv", "data/dispensing.csv"], ["d_summary.json"], ["python3", "loop_summary.py", "d", str(WEEK), "data", "d_summary.json"])
    fl.step(["loop_summary.py", "c_summary.json", "b_summary.json", "a_summary.json", "d_summary.json"], ["summary.json"], ["python3", "loop_summary.py", "merge", "summary.json", "c_summary.json", "b_summary.json", "a_summary.json", "d_summary.json"])
    done("summary")
    return phs, bphs, days


def oracle(py, script, root):
    r = subprocess.run([py, str(HERE / "scripts" / script), str(root)], capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "rule": "oracle.no-output"}


def judge(fl, phs, bphs, days):
    problems, report = [], []
    T = pc.table
    py = os.environ.get("SCIPY_PYTHON", sys.executable)
    # ---- G14: every plan verified; HiGHS equal or bracketing ----
    stopped = 0
    kinds = (("c", "replenishment", ["c/models/W%d_%s" % (WEEK, p) for p in phs], "oracle_highs.py"), ("b", "outreach", ["b/models/W%d_%s" % (WEEK, p) for p in bphs], "oracle_highs_b.py"),
             ("a", "charging", ["a/models/D%d" % d for d in days], "oracle_highs_c.py"))
    for k, name, bases, script in kinds:
        bad, nopt = [], 0
        for b in bases:
            plan, ver = json.loads(fl.read(b + ".plan.json")), json.loads(fl.read(b + ".verify.json"))
            if plan.get("status") not in ("optimal", "feasible") or ver.get("status") != "verified" or not ver.get("objective_checked"):
                bad.append("%s %s / verify %s" % (b, plan.get("status"), ver.get("status")))
            nopt += int(plan.get("status") != "optimal")
        stopped += nopt
        if os.environ.get("SKIP_ORACLE") == "1":
            o_txt = "HiGHS SKIPPED on purpose"
        else:
            o = oracle(py, script, fl.root / k)
            if o.get("rule") == "oracle.no-scipy":
                o_txt = "HiGHS NOT RUN (no scipy)"
                problems.append("G14: the HiGHS oracle was not run (no scipy); set SCIPY_PYTHON, or SKIP_ORACLE=1 to leave it out knowingly")
            else:
                o_txt = "HiGHS: %d instances, worst relative gap %.2e" % (o.get("instances", 0), o.get("worst_relative_gap", float("nan")))
                if not o.get("ok") or o.get("instances") != len(bases):
                    problems.append("G14: HiGHS and solve disagree for %s, or did not cover every plan: %s" % (name, json.dumps(o)[:300]))
        report.append("G14 %s: %d plans, %d not verified or not optimal-or-feasible, %d stopped at the node limit; %s" % (name, len(bases), len(bad), nopt, o_txt))
        if bad:
            problems.append("G14: %d %s plans are not verified, e.g. %s" % (len(bad), name, bad[0]))
    # ---- G15: the summary recomputed from the raw plan and data files ----
    S = json.loads(fl.read("summary.json"))
    g15 = len(problems)
    want = {"c": {"week": WEEK, "pharmacies": {}}, "b": {"week": WEEK, "pharmacies": {}}, "a": {"days": [DAY0, DAY1], "nights": {}}}
    pack = {r["item"]: int(r["pack_size"]) for r in T(fl.read("data/items.csv"))}
    ctest = T(fl.read("c_test.csv"))
    for p in phs:
        plan = json.loads(fl.read("c/models/W%d_%s.plan.json" % (WEEK, p)))
        its = [r["item"] for r in ctest if r["pharmacy"] == p]
        want["c"]["pharmacies"][p] = {"ordered_units": sum(pack[it] * int(round(plan["x"]["q[%d]" % i])) for i, it in enumerate(its)), "objective": "%.6f" % plan["objective"]}
    home = {r["patient"]: r["home_pharmacy"] for r in T(fl.read("data/patients.csv"))}
    nev = {}
    for r in T(fl.read("b_test_cal.csv")):
        if int(r["due_week"]) == WEEK:  # the events the decision is about; a file with later weeks in it is G16's finding, not a crash here
            nev[home[r["patient"]]] = nev.get(home[r["patient"]], 0) + 1
    for p in bphs:
        plan = json.loads(fl.read("b/models/W%d_%s.plan.json" % (WEEK, p)))
        n = nev[p]
        row = {kk: sum(int(round(plan["x"].get("%s[%d]" % (key, e), 0))) for e in range(n)) for kk, key in (("call", "xc"), ("reminder", "xr"), ("switch90", "xs"), ("delivery", "xd"))}
        row.update({"events": n, "expected_value": "%.6f" % plan["objective"]})
        want["b"]["pharmacies"][p] = row
    routes = T(fl.read("data/routes.csv"))
    pred = {r["route"]: float(r["pred_boost_wh"]) for r in T(fl.read("a_pred.csv"))}
    for d in days:
        plan = json.loads(fl.read("a/models/D%d.plan.json" % d))
        rs = [r for r in routes if int(r["day"]) == d]
        want["a"]["nights"][str(d)] = {"trucks": len(rs), "planned_kwh": "%.3f" % sum(pred[r["route"]] / 1000.0 + 3.0 for r in rs), "cost": "%.6f" % plan["objective"]}
    day_of = {r["route"]: int(r["day"]) for r in routes}
    late, warm = set(), set()
    for r in T(fl.read("data/telemetry.csv")):
        if r["pharmacy"] != "DEPOT" and day_of[r["route"]] // 7 == WEEK:
            if int(r["arrive_min"]) > int(r["window_end_min"]):
                late.add(r["pharmacy"])
            if int(r["cabin_temp_dc"]) > 80:
                warm.add(r["pharmacy"])
    so = {str(WEEK): [0, 0], str(WEEK + 1): [0, 0]}
    for r in T(fl.read("data/dispensing.csv")):
        if r["week"] in so and r["stockout"] == "1":
            so[r["week"]][0 if r["pharmacy"] in (late | warm) else 1] += 1
    want["coupling"] = {"week": WEEK, "late": sorted(late), "warm": sorted(warm), "stockout_items": {w: {"flagged_pharmacies": v[0], "others": v[1]} for w, v in so.items()}}
    diff = [k for k in ("c", "b", "a", "coupling") if S.get(k) != want[k]]
    report.append("G15 the summary against a recomputation from the plans and the data: %s" % ("equal on all four parts" if not diff else "DIFFERS in %s" % ", ".join(diff)))
    if diff:
        problems.append("G15: the summary differs from the plans and data in %s (e.g. %s against %s)" % (", ".join(diff), json.dumps(S.get(diff[0]), sort_keys=True)[:120], json.dumps(want[diff[0]], sort_keys=True)[:120]))
    # ---- G16: the stages ----
    n_c, n_b, n_a = len(phs), len(bphs), len(days)
    report.append("G16 decisions: %d replenishment, %d outreach, %d nights of charging; coupling in week %d: late %s, warm %s, stockout items (flagged pharmacies, others): %s" % (
        n_c, n_b, n_a, WEEK, sorted(late), sorted(warm), {w: tuple(v) for w, v in so.items()}))
    if n_c != 20 or n_b != 20 or not (1 <= n_a <= 7):
        problems.append("G16: the loop has %d replenishment, %d outreach and %d charging decisions, wanted 20, 20 and 1 to 7" % (n_c, n_b, n_a))
    wk_c = {int(r["week"]) for r in T(fl.read("c_test.csv"))}
    wk_b = {int(r["due_week"]) for r in T(fl.read("b_test.csv"))}
    dy_a = {int(r["day"]) for r in T(fl.read("a_test.csv"))}
    leak = []
    if wk_c != {WEEK}:
        leak.append("C decides on weeks %s" % sorted(wk_c))
    if wk_b != {WEEK}:
        leak.append("B decides on due weeks %s" % sorted(wk_b))
    if not dy_a <= set(range(DAY0, DAY1 + 1)):
        leak.append("A plans nights %s" % sorted(dy_a))
    for rel, col, lim, nm in (("c_train.csv", "week", WEEK - 1, "C's fit"), ("b_fit.csv", "due_week", WEEK - 1, "B's fit"), ("b_cal.csv", "due_week", WEEK - 1, "B's calibration"), ("a_fit.csv", "day", DAY0 - 1, "A's fit")):
        mx = max(int(r[col]) for r in T(fl.read(rel)))
        if mx > lim:
            leak.append("%s reaches %s %d (limit %d)" % (nm, col, mx, lim))
    report.append("G16 weeks and days: C %s, B %s, A days %s; fits end before the week" % (sorted(wk_c), sorted(wk_b), (min(dy_a), max(dy_a)) if dy_a else None))
    if leak:
        problems.append("G16: %s" % "; ".join(leak))
    # ---- G17 ----
    p7, r7 = pc.judge_records(fl, "c_test.csv")
    return problems + p7, report + r7


def run_once(out, runs_dir=None):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fl = pc.Flow(out)
    for f in ("features_b.py", "features_a2.py", "pred_join.py", "apply_isotonic.py", "pred_routes.py", "build_models.py", "build_outreach.py", "build_charging.py", "verify_input.py", "loop_summary.py", "costs.json", "outreach.json", "charging.json"):
        shutil.copy2(HERE / f, fl.root / f)
    shutil.copy(HERE / "twinlib" / "delivery.py", fl.root / "twinlib" / "delivery.py")
    t0 = time.time()
    phs, bphs, days = run_steps(fl)
    wall = time.time() - t0  # the steps, not the judging
    problems, report = judge(fl, phs, bphs, days)
    (out / "report.json").write_text(json.dumps({"problems": problems, "report": report, "steps": fl.steps}))
    (out / "timing.json").write_text(json.dumps({"wall_s": wall, "stages_s": fl.stage, "by_program_ms": fl.ms, "steps": fl.steps, "threads": THREADS or "default"}))
    return 0


def tree_digest(root):
    h = hashlib.sha256()
    for f in sorted(glob.glob(str(root / "**" / "*"), recursive=True)):
        if os.path.isfile(f):
            h.update(os.path.relpath(f, root).encode() + b"\0" + hashlib.sha256(open(f, "rb").read()).digest())
    return h.hexdigest()


def run(runs=2, keep=None):
    with tempfile.TemporaryDirectory() as td:
        dirs = [pathlib.Path(td) / ("run%d" % i) for i in range(runs)]
        procs = [subprocess.Popen([sys.executable, str(HERE / "scripts" / "loop.py"), "--once", str(d)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for d in dirs]
        outs = [p.communicate()[0] for p in procs]
        for i, p in enumerate(procs):
            if p.returncode != 0:
                return ["loop: run %d stopped: %s" % (i, outs[i].strip()[-400:])], []
        rep = json.loads((dirs[0] / "report.json").read_text())
        problems, report = list(rep["problems"]), list(rep["report"])
        sums = [(d / "root" / "summary.json").read_bytes() for d in dirs]
        digest = hashlib.sha256(sums[0]).hexdigest()
        if runs >= 2:
            recs = [tree_digest(d / "root" / "rec") for d in dirs]
            same_sum, same_rec = all(s == sums[0] for s in sums), all(r == recs[0] for r in recs)
            report.append("G13 %d independent runs, %d recorded steps each: summary.json %s (sha256 %s), the records %s" % (runs, rep["steps"], "byte for byte equal" if same_sum else "DIFFER", digest[:16], "byte for byte equal" if same_rec else "DIFFER"))
            if not same_sum:
                problems.append("G13: summary.json differs between two runs")
            if not same_rec:
                problems.append("G13: the flow records differ between two runs")
        else:
            report.append("G13 not judged (one run); summary.json sha256 %s" % digest[:16])
        if keep:
            shutil.copytree(dirs[0], keep, dirs_exist_ok=True)
        return problems, report


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("c-fit-includes-the-test-week", "scripts/loop.py", _x('"week:int >= %d and week:int < %d" % (C_FIT_FROM, ', 'WEEK)'), '"week:int >= %d and week:int < %d" % (C_FIT_FROM, WEEK + 1)', "G16", 1),
    ("b-test-includes-later-weeks", "scripts/loop.py", _x('"due_week:int = %d" % ', 'WEEK, "b_events.csv"'), '"due_week:int >= %d" % WEEK, "b_events.csv"', "G16", 1),
    ("summary-ordered-units-off-by-one", "loop_summary.py", _x('ordered += d["pack"][i] * int(round(plan["x"]["q[%d]" % i]))', ''), 'ordered += d["pack"][i] * int(round(plan["x"]["q[%d]" % i])) + 1', "G15", 1),
    ("stage-missing-from-the-summary", "loop_summary.py", _x('"a": json.load(open(aj)), ', '"coupling"'), '"coupling"', "G15", 1),
    ("clock-in-the-summary", "loop_summary.py", _x('dump(out, {"c": json.load(open(cj)), ', '"b"'), 'dump(out, {"generated": __import__("time").time(), "c": json.load(open(cj)), "b"', "G13", 2),
]


def mutants(only=None):
    survived = 0
    for name, rel, old, new, gate, runs in MUTANTS:
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
            r = subprocess.run([sys.executable, str(tree / "scripts" / "loop.py"), "--runs", str(runs)], capture_output=True, text=True, env=env, cwd=td, timeout=7200)
            out = r.stdout + r.stderr
            if only:
                print(out[-2500:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-36s by %s" % (name, hit[0][:130]))
            else:
                survived += 1
                print("SURVIVED %-36s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
    print("%d mutants, %d survived" % (len(MUTANTS) if not only else 1, survived))
    return 1 if survived else 0


def main():
    a = sys.argv
    if "--once" in a:
        return run_once(a[a.index("--once") + 1])
    if "--mutant" in a:
        return mutants(a[a.index("--mutant") + 1])
    if "--mutants" in a:
        return mutants()
    runs = int(a[a.index("--runs") + 1]) if "--runs" in a else 2
    problems, report = run(runs, a[a.index("--keep") + 1] if "--keep" in a else None)
    for ln in report:
        print(ln)
    for p in problems:
        print(p)
    if problems:
        return 1
    print("loop: ok (G13 to G17 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
