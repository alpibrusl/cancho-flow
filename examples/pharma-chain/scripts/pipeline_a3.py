#!/usr/bin/env python3
"""U4c: A's decision, as recorded `flow` steps after the models of pipeline_a2.py, and the gates G5, G6 and G11 for the overnight charging plan, G12 for the `opt` calibration, and G7 (docs/use-cases.md, margins of 7a for U4c,
committed before the charging model or the calibration was built).

    CANCHO=<compiler> [SCIPY_PYTHON=<a python with scipy>] python3 scripts/pipeline_a3.py [--mutants] [--mutant NAME] [--keep DIR]

Per night of the test days (days 546 to 727 that have routes): build the model from the predicted energy of each route (build_charging.py), `solve run`, join, `solve verify`. Then the calibration of the four energy coefficients with
`opt minimize` on the legs of the twin and of a control whose heat fraction is zero.
"""
import csv
import itertools
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scripts"))
import pipeline_a as pa  # noqa: E402
import pipeline_a2 as pa2  # noqa: E402
import pipeline_c as pc  # noqa: E402
from build_charging import instance, model_text  # noqa: E402

# --- the margins of docs/use-cases.md section 7a (G5, G6, G11, G12 for A), fixed before the charging model and the calibration were built ---
G11_SHORTFALL_MAX = 0.05     # share of route-nights charged less than was used, plan from the boost
G11_BASE_FACTOR = 2.0        # the baseline's share is at least this times the boost plan's
G11_COST_MAX = 0.60          # the optimal plan's cost against the plug-in-and-charge-now plan's
G12_SSE_FACTOR = 1.001       # the sum of squares opt reaches, against the exact minimum
G12_REL = {"drive": 0.02, "fridge_w": 0.03, "ppm": 0.10, "door_w": 0.15}
G12_CONTROL_PPM = 25000.0
X0 = "3.5,1.2,1.5,1.5"
OPT_MAXFEV = "4000"
EPS = 1e-6


def run_steps(fl):
    pa2.run_steps(fl)
    tb = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]
    # ---- the predicted energy of each test route, from the two models of U4b ----
    fl.step(["m_eboost.ml", "test_e.csv"], [], ["ml", "--root", ".", "--model-file", "m_eboost.ml", "--drop", pa2.E_DROP, "--limit", "1000000", "predict", "test_e.csv"], stdout_file="pred_e_boost.json", max_output=33554432)
    fl.step(["m_base.ml", "test_e.csv"], [], ["ml", "--root", ".", "--model-file", "m_base.ml", "--drop", pa2.E_BASE_DROP, "--limit", "1000000", "predict", "test_e.csv"], stdout_file="pred_e_base.json", max_output=33554432)
    fl.step(["pred_routes.py", "test_e.csv", "pred_e_boost.json", "pred_e_base.json"], ["pred_routes.csv"], ["python3", "pred_routes.py", "test_e.csv", "pred_e_boost.json", "pred_e_base.json", "pred_routes.csv"])
    # ---- the nights ----
    days = sorted({int(r["day"]) for r in pc.table(fl.read("test_e.csv"))})
    ins = ["build_charging.py", "data_main/routes.csv", "data_main/telemetry.csv", "data_main/depot.csv", "pred_routes.csv", "charging.json"]
    for dd in days:
        b = "models/D%d" % dd
        fl.step(ins, [b + ".sol", b + ".json"], ["python3", "build_charging.py", str(dd), "data_main", "pred_routes.csv", "charging.json", "."])
        fl.step([b + ".sol"], [], ["solve", "run"], stdin_file=b + ".sol", stdout_file=b + ".plan.json")
        fl.step(["verify_input.py", b + ".sol", b + ".plan.json"], [b + ".verify.in"], ["python3", "verify_input.py", b + ".sol", b + ".plan.json", b + ".verify.in"])
        fl.step([], [], ["solve", "verify"], stdin_file=b + ".verify.in", stdout_file=b + ".verify.json")
    # ---- the calibration of the twin's coefficients, on the twin and on a control with the heat fraction zero ----
    pa.world(fl, "fridge0", "fridge_temp_ppm")
    fl.step(pa.TWIN + ["world_fridge0.json"], ["data_fridge0/%s" % f for f in pa.DEL_FILES],
            ["python3", "twin.py", "generate", "--world", "world_fridge0.json", "--seed", str(pa.SEED), "--size", "large", "--tables", "core,delivery", "--out", "data_fridge0"])
    for tag in ("main", "fridge0"):
        fl.step(["features_a3.py", "data_%s/routes.csv" % tag, "data_%s/telemetry.csv" % tag, "data_%s/days.csv" % tag], ["legs_%s.csv" % tag], ["python3", "features_a3.py", "data_%s" % tag, "legs_%s.csv" % tag])
        fl.step(["objective_a.py", "legs_%s.csv" % tag], [], ["opt", "minimize", "--x0", X0, "--maxfev", OPT_MAXFEV, "--", "./objective_a.py", "legs_%s.csv" % tag], stdout_file="opt_%s.json" % tag, allow_failure=True)


def chosen(plan, V, T):
    return [[plan["x"]["charge[%d,%d]" % (v, t)] for t in range(T)] for v in range(V)], [[plan["x"]["on[%d,%d]" % (v, t)] for t in range(T)] for v in range(V)]


def toy():
    """Two trucks, four slots, one charger: every pattern of plugged slots tried, the best charge for a pattern found here by filling the cheapest slots (apart from the builder)."""
    cfg = {"pmax_kw": 11, "chargers": 1}
    need, arrive_h = [15.0, 10.0], [20, 21]
    price = [0.30, 0.10, 0.20, 0.10] + [0.0] * 20
    cap = [100] * 24
    price_h = [0.0] * 24
    for h in range(20, 24):
        price_h[h] = price[h - 20]
    d = instance(need, arrive_h, price_h, cap, cfg, 24)
    best = None
    V, T = 2, d["T"]
    for pat in itertools.product((0, 1), repeat=V * T):
        if any(pat[v * T + t] and not d["avail"][v * T + t] for v in range(V) for t in range(T)):
            continue
        if any(sum(pat[v * T + t] for v in range(V)) > cfg["chargers"] for t in range(T)):
            continue
        cost, ok = 0.0, True
        for v in range(V):
            rem = need[v]
            for t in sorted((t for t in range(T) if pat[v * T + t]), key=lambda t: price_h[d["h0"] + t]):
                e = min(11.0, rem)
                cost += e * price_h[d["h0"] + t]
                rem -= e
            if rem > 1e-9:
                ok = False
                break
        if ok and (best is None or cost < best):
            best = cost
    return model_text(d), best


def judge(fl):
    problems, report = pa2.judge(fl)  # the models of U4b, and G7 over every step so far
    p2, r2 = judge_decision(fl)
    return problems + p2, report + r2


def judge_decision(fl):
    problems, report = [], []
    J = lambda rel: json.loads(fl.read(rel))
    T_ = pc.table
    cfg = json.loads(fl.read("charging.json"))
    solve = str(fl.tmp / "programs" / "solve")
    depot = T_(fl.read("data_main/depot.csv"))
    tariff = [int(r["tariff_milli"]) / 1000.0 for r in depot]
    cap = [int(r["cap_kw"]) for r in depot]
    last = {}
    for r in T_(fl.read("data_main/telemetry.csv")):
        last[r["route"]] = int(r["arrive_min"])
    routes = T_(fl.read("data_main/routes.csv"))
    by_day = {}
    for r in routes:
        by_day.setdefault(int(r["day"]), []).append(r)
    actual = {r["route"]: int(r["energy_wh"]) / 1000.0 for r in routes}
    pred = {r["route"]: (float(r["pred_boost_wh"]) / 1000.0, float(r["pred_base_wh"]) / 1000.0) for r in T_(fl.read("pred_routes.csv"))}
    days = sorted({int(r["day"]) for r in T_(fl.read("test_e.csv"))})
    status_bad, short_boost, short_base, n_rt = [], 0, 0, 0
    under, over_kw, over_ch, early, cost_bad, gap_need = [], [], [], [], [], []
    cost_plan = cost_asap = 0.0
    asap_bad = 0
    PM, CH, SAF, DEP = cfg["pmax_kw"], cfg["chargers"], cfg["safety_kwh"], cfg["departure_hour"]
    for dd in days:
        b = "models/D%d" % dd
        plan, ver = json.loads(fl.read(b + ".plan.json")), json.loads(fl.read(b + ".verify.json"))
        if plan.get("status") != "optimal" or ver.get("status") != "verified" or not ver.get("objective_checked"):
            status_bad.append("%s %s / verify %s" % (b, plan.get("status"), ver.get("status")))
            continue
        rs = by_day[dd]
        V = len(rs)
        arr_h = [-(-last[r["route"]] // 60) for r in rs]
        h0 = min(arr_h)
        Tn = DEP - h0
        ch, on = chosen(plan, V, Tn)
        need = [pred[r["route"]][0] + SAF for r in rs]
        need_base = [pred[r["route"]][1] + SAF for r in rs]
        cost = 0.0
        for v in range(V):
            total = sum(ch[v])
            if total < need[v] - EPS:
                under.append("%s truck %d charged %.3f kWh, needs %.3f" % (b, v, total, need[v]))
            if total > need[v] + 1e-4:
                gap_need.append("%s truck %d charged %.3f kWh, needs %.3f" % (b, v, total, need[v]))
            n_rt += 1
            short_boost += int(total < actual[rs[v]["route"]] - 1e-9)
            short_base += int(need_base[v] < actual[rs[v]["route"]] - 1e-9)
            for t in range(Tn):
                hr = h0 + t
                if ch[v][t] > PM + EPS or ch[v][t] < -EPS:
                    over_kw.append("%s truck %d hour %d draws %.3f kW" % (b, v, hr, ch[v][t]))
                if ch[v][t] > EPS and hr < arr_h[v]:
                    early.append("%s truck %d charges at hour %d, before its arrival at %d" % (b, v, hr, arr_h[v]))
                cost += ch[v][t] * tariff[hr % 24]
        for t in range(Tn):
            hr = h0 + t
            col = [ch[v][t] for v in range(V)]
            if sum(1 for x in col if x > EPS) > CH or sum(col) > cap[hr % 24] + EPS:
                over_ch.append("%s hour %d: %d trucks, %.2f kW, connection %d kW" % (b, hr, sum(1 for x in col if x > EPS), sum(col), cap[hr % 24]))
        if abs(cost - plan["objective"]) > 1e-6 * max(1.0, abs(cost)):
            cost_bad.append("%s formula %.6f, solve %.6f" % (b, cost, plan["objective"]))
        # the plug-in-and-charge-now plan on the same needs: in order of arrival, at the full rate, while chargers and the connection allow
        busy, load, c_asap, ok = {}, {}, 0.0, True
        for v in sorted(range(V), key=lambda v: (arr_h[v], v)):
            rem = need[v]
            for t in range(arr_h[v], DEP):
                if rem <= 1e-9:
                    break
                if busy.get(t, 0) >= CH or load.get(t, 0.0) + PM > cap[t % 24] + 1e-9:
                    continue
                e = min(PM, rem)
                busy[t] = busy.get(t, 0) + 1
                load[t] = load.get(t, 0.0) + e
                rem -= e
                c_asap += e * tariff[t % 24]
            if rem > 1e-6:
                ok = False
        if ok:
            cost_plan += cost
            cost_asap += c_asap
        else:
            asap_bad += 1
    nn = len(days)
    report.append("G5 %d nights: %d not optimal or not verified%s" % (nn, len(status_bad), (" (e.g. %s)" % status_bad[0]) if status_bad else ""))
    if status_bad:
        problems.append("G5: %d plans are not optimal and verified, e.g. %s" % (len(status_bad), status_bad[0]))
    py = os.environ.get("SCIPY_PYTHON", sys.executable)
    if os.environ.get("SKIP_ORACLE") == "1":
        report.append("G5 oracle: SKIPPED on purpose (SKIP_ORACLE=1)")
    else:
        r = subprocess.run([py, str(HERE / "scripts" / "oracle_highs_c.py"), str(fl.root)], capture_output=True, text=True)
        try:
            o = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            o = {"ok": False, "rule": "oracle.no-output"}
        if o.get("rule") == "oracle.no-scipy":
            report.append("G5 oracle: NOT RUN (no scipy for %s)" % py)
            problems.append("G5: the HiGHS oracle was not run (no scipy); set SCIPY_PYTHON, or SKIP_ORACLE=1 to leave it out knowingly")
        else:
            report.append("G5 HiGHS: %d instances, worst relative gap %.2e%s" % (o.get("instances", 0), o.get("worst_relative_gap", float("nan")), "" if o.get("ok") else " (BAD: %s)" % o.get("bad")))
            if not o.get("ok") or o.get("instances") != nn:
                problems.append("G5: HiGHS and solve disagree, or did not cover every night: %s" % json.dumps(o)[:300])
    text, best = toy()
    r = subprocess.run([solve, "run"], input=text, capture_output=True, text=True)
    try:
        got = json.loads(r.stdout)["objective"]
    except (ValueError, KeyError):
        got = None
    report.append("G5 toy (2 trucks, 4 slots, 1 charger, every pattern of plugged slots tried): enumeration %.6f, solve %s" % (best, ("%.6f" % got) if got is not None else "none"))
    if got is None or abs(got - best) > 1e-6 * max(1.0, abs(best)):
        problems.append("G5: on the toy night solve's optimum is %s, an enumeration gives %.6f" % (got, best))
    report.append("G6 %d plans: %d trucks charged less than their need, %d draws beyond %d kW, %d charging before arrival, %d hours over the chargers or the connection, %d costs that are not the formula's; %d trucks charged more than their need" % (
        nn, len(under), len(over_kw), PM, len(early), len(over_ch), len(cost_bad), len(gap_need)))
    for k, lst in (("need", under), ("power", over_kw), ("arrival", early), ("chargers or connection", over_ch), ("cost", cost_bad)):
        if lst:
            problems.append("G6: %d cases break the %s rule, e.g. %s" % (len(lst), k, lst[0]))
    # tampers
    d0 = days[0]
    base = "models/D%d" % d0
    model, plan = fl.read(base + ".sol"), json.loads(fl.read(base + ".plan.json"))
    dj = json.loads(fl.read(base + ".json"))
    V0, T0 = dj["V"], dj["T"]
    t1 = json.loads(json.dumps(plan))
    for t in range(T0):
        t1["x"]["charge[0,%d]" % t] = 0.0
        t1["x"]["on[0,%d]" % t] = 0.0
    t2 = json.loads(json.dumps(plan))
    tt = next((t for t in range(T0) if plan["x"]["charge[0,%d]" % t] > 0), 0)  # a plan that charges nothing (a mutant that dropped the need) must not crash the gate
    t2["x"]["charge[0,%d]" % tt] = float(PM + 1)
    t3 = json.loads(json.dumps(plan))
    early_slot = next(t for t in range(T0) if not dj["avail"][1 * T0 + t]) if V0 > 1 and any(not dj["avail"][1 * T0 + t] for t in range(T0)) else None
    tampers = [("a truck given no charge", t1, None), ("a draw above the charger's power", t2, "solve.bound-violated")]
    if early_slot is not None:
        t3["x"]["on[1,%d]" % early_slot] = 1.0
        t3["x"]["charge[1,%d]" % early_slot] = 1.0
        tampers.append(("a truck plugged before it arrived", t3, None))
    for label, pl, want in tampers:
        r = subprocess.run([solve, "verify"], input=model.rstrip("\n") + "\n---\n" + json.dumps(pl) + "\n", capture_output=True, text=True)
        tag = None
        try:
            doc = json.loads((r.stderr or r.stdout).strip().splitlines()[0])
            e = doc.get("error")
            tag = e if isinstance(e, str) else (e or {}).get("rule")
        except (ValueError, IndexError, AttributeError):
            pass
        report.append("G6 tamper, %s: solve verify exit %d, rule %s" % (label, r.returncode, tag))
        if r.returncode == 0:
            problems.append("G6: solve verify accepted %s" % label)
        elif not (tag or "").startswith("solve.") or (want and tag != want):
            problems.append("G6: solve verify refused %s with rule %s%s" % (label, tag, (", not %s" % want) if want else ""))
    # G11
    s_boost, s_base = short_boost / n_rt, short_base / n_rt
    ratio_cost = cost_plan / cost_asap if cost_asap else float("nan")
    report.append("G11 %d route-nights: charged less than was used: %d (%.4f) from the boost's prediction plus %.1f kWh, %d (%.4f) from the distance-only baseline's; the optimal plan costs %.4f of the plug-in-and-charge-now plan (%d nights where that plan could not deliver are left out)" % (
        n_rt, short_boost, s_boost, SAF, short_base, s_base, ratio_cost, asap_bad))
    if s_boost > G11_SHORTFALL_MAX:
        problems.append("G11: the boost plan charged less than was used on %.4f of the route-nights (limit %.2f)" % (s_boost, G11_SHORTFALL_MAX))
    if s_base < G11_BASE_FACTOR * s_boost:
        problems.append("G11: the baseline plan's shortfall share %.4f is not at least %.1f times the boost plan's %.4f" % (s_base, G11_BASE_FACTOR, s_boost))
    if not ratio_cost <= G11_COST_MAX:
        problems.append("G11: the optimal plan costs %.4f of the plug-in-and-charge-now plan (limit %.2f)" % (ratio_cost, G11_COST_MAX))
    # G12
    truth = {k: json.loads(fl.read("world_main.json"))["params"][k]["value"] for k in ("drive_wh_per_km", "fridge_w", "fridge_temp_ppm", "door_w")}
    names = (("drive", truth["drive_wh_per_km"], 100.0), ("fridge_w", truth["fridge_w"], 1000.0), ("ppm", truth["fridge_temp_ppm"], 100000.0), ("door_w", truth["door_w"], 1000.0))
    om = J("opt_main.json")
    got_p = dict(zip(("drive", "fridge_w", "ppm", "door_w"), (v * s for v, (_, _, s) in zip(om["x"], names))))
    sse_opt = float(om["fun"])
    if os.environ.get("SKIP_ORACLE") == "1":
        sse_min, report_or = None, "SKIPPED on purpose"
    else:
        r = subprocess.run([py, str(HERE / "scripts" / "oracle_lstsq_a.py"), str(fl.root / "legs_main.csv")], capture_output=True, text=True)
        try:
            ol = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            ol = {"ok": False, "rule": "oracle.no-output"}
        if ol.get("rule") == "oracle.no-scipy":
            sse_min = None
            problems.append("G12: the least-squares oracle was not run (no numpy); set SCIPY_PYTHON, or SKIP_ORACLE=1 to leave it out knowingly")
        else:
            sse_min = ol["sse"]
    report.append("G12 opt (%d evaluations, converged %s): sum of squares %.3f%s; coefficients %s (the twin's: %s)" % (
        om["nfev"], om["converged"], sse_opt, (" against the exact minimum %.3f (ratio %.5f, limit %.3f)" % (sse_min, sse_opt / sse_min, G12_SSE_FACTOR)) if sse_min else " (oracle not run)",
        ", ".join("%s %.4g" % (k, got_p[k]) for k in got_p), ", ".join("%s %g" % (k, v) for k, v, _ in names)))
    if sse_min and sse_opt > G12_SSE_FACTOR * sse_min:
        problems.append("G12: the sum of squares opt reaches, %.3f, is not within %.3f of the exact minimum %.3f" % (sse_opt, G12_SSE_FACTOR, sse_min))
    for k, tv, _ in names:
        rel = abs(got_p[k] - tv) / tv
        report.append("G12 %-8s calibrated %.5g, twin %g: relative error %.4f (limit %.2f)" % (k, got_p[k], tv, rel, G12_REL[k]))
        if rel > G12_REL[k]:
            problems.append("G12: the coefficient %s is %.5g, %.1f percent from the twin's %g (limit %.0f percent)" % (k, got_p[k], 100 * rel, tv, 100 * G12_REL[k]))
    oc = J("opt_fridge0.json")
    ppm0 = oc["x"][2] * 100000.0
    report.append("G12 control (heat fraction zero in the twin): calibrated heat fraction %.0f ppm (limit %.0f)" % (ppm0, G12_CONTROL_PPM))
    if abs(ppm0) > G12_CONTROL_PPM:
        problems.append("G12: with the heat fraction zero in the twin the calibrated value is %.0f ppm (limit %.0f)" % (ppm0, G12_CONTROL_PPM))
    return problems, report


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        for f in ("features_a.py", "features_a2.py", "features_a3.py", "pred_join_g.py", "apply_isotonic_g.py", "pred_routes.py", "build_charging.py", "verify_input.py", "charging.json", "objective_a.py"):
            shutil.copy2(HERE / f, fl.root / f)
        shutil.copy(HERE / "twinlib" / "delivery.py", fl.root / "twinlib" / "delivery.py")
        run_steps(fl)
        out = judge(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return out


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("need-row-dropped", "build_charging.py", _x('    t += "    forall v in 0..V: energy: sum t in 0..T: charge[v,t] >= need[v]', ';\\n"'), '    t += ""', "G6"),
    ("tariff-hour-off-by-one", "build_charging.py", _x('"price": [price_by_hour[(h0 + t) ', '% 24] for t in range(T)]'), '"price": [price_by_hour[(h0 + t + 1) % 24] for t in range(T)]', "G6"),
    ("safety-zero", "charging.json", _x('"safety_kwh": ', '3.0'), '"safety_kwh": 0.0', "G11"),
    ("need-from-the-baseline-prediction", "build_charging.py", _x('col = "pred_', 'boost_wh"'), 'col = "pred_base_wh"', "G11"),
    ("need-wrong-in-the-model-text-only", "build_charging.py", _x('arr(d["cap"]), arr(d["ne', 'ed"]), arr(d["avail"]))'), 'arr(d["cap"]), arr([x + 1.0 for x in d["need"]]), arr(d["avail"]))', "G5"),
    ("chargers-row-dropped", "build_charging.py", _x('    t += "    forall t in 0..T: chargers_free: sum v in 0..V: on[v,t] <= %d', ';\\n" % d["chargers"]'), '    t += ""', "G6"),
    ("objective-ignores-the-doors", "objective_a.py", _x('+ int(r["door_min"]) * door_w', ' / 60.0'), '+ 0 * door_w', "G12"),
    ("opt-stops-early", "scripts/pipeline_a3.py", _x('OPT_MAXFEV = "', '4000"'), 'OPT_MAXFEV = "40"', "G12"),
    ("control-not-zeroed", "scripts/pipeline_a3.py", _x('pa.world(fl, "fridge0", "fridge_temp', '_ppm")'), 'pa.world(fl, "fridge0", "noise_ppm")', "G12"),
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
            pairs = list(zip(old, new)) if isinstance(old, list) else [(old, new)]
            if any(text.count(o) != 1 for o, _ in pairs):
                print("mutant %-40s CANNOT BE APPLIED (%s occurrences in %s)" % (name, [text.count(o) for o, _ in pairs], rel))
                survived += 1
                continue
            for o, n_ in pairs:
                text = text.replace(o, n_)
            f.write_text(text)
            env = dict(os.environ, FLOW_REPO=str(pc.REPO), TABLE=pc.exe("table", "TABLE"), STATS=pc.exe("stats", "STATS"), ML=pc.exe("ml", "ML"), SOLVE=pc.exe("solve", "SOLVE"), OPT=pc.exe("opt", "OPT"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "pipeline_a3.py")], capture_output=True, text=True, env=env, cwd=td, timeout=7200)
            out = r.stdout + r.stderr
            if only:
                print(out[-2500:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-40s by %s" % (name, hit[0][:130]))
            else:
                survived += 1
                print("SURVIVED %-40s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
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
    print("pipeline_a3: ok (G5, G6, G11, G12 and G7 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
