#!/usr/bin/env python3
"""U3b: the outreach decision for `solve`, run as recorded `flow` steps after the calibrated lapse model of pipeline_b.py, and the gates G5, G6, G9 and G7 (docs/use-cases.md, margins of 7a
for U3b, committed before this was built).

    CANCHO=<compiler> [SCIPY_PYTHON=<a python with scipy>] python3 scripts/plan_b.py [--mutants] [--mutant NAME] [--keep DIR]

Per pharmacy and test week (the 208 cells): build the model from the calibrated probabilities (build_outreach.py), `solve run`, join, `solve verify`. Per cell also the *oracle plan*, built
from the twin's true probabilities (build_outreach.py --true-p, which is the only place the analysis side reads truth/, to make the yardstick of G9), and solved. Then the judges.
SCIPY_PYTHON missing or without scipy: G5's oracle is NOT RUN and that fails the gate, unless SKIP_ORACLE=1 says it was left out on purpose.
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
import pipeline_b as pb  # noqa: E402
import pipeline_c as pc  # noqa: E402
from build_outreach import ACTIONS, instance, model_text  # noqa: E402

# --- the margins of docs/use-cases.md section 7a (G9), fixed before the decision was built ---
G9_VS_ORACLE_MIN = 0.90
G9_VS_ORACLE_MAX = 1.0
G9_VS_BASELINE_MIN = 1.25
G9_EXPECTED_VS_TRUE = 0.10
G9_BINDING_SHARE = 0.5
EPS = 1e-6
NODE_LIMIT = 20000  # `flow` ends a step at its deadline and a few decisions take longer than that to prove (measured: 2 of 1,040 past 20 s): a node limit is how the search ends instead


def run_plan(fl):
    pb.run_steps(fl)
    # G7 is judged inside pb.judge over every step recorded so far, the outreach steps included. The cells: the home pharmacy of each event due in the test weeks (patients.csv is what the pharmacy knows)
    home = {r["patient"]: r["home_pharmacy"] for r in pc.table(fl.read("data_main/patients.csv"))}
    cells = sorted({(int(r["due_week"]), home[r["patient"]]) for r in pc.table(fl.read("test_cal.csv"))})
    ins = ["build_outreach.py", "test_cal.csv", "data_main/patients.csv", "outreach.json"]
    for w, p in cells:
        b = "models/W%d_%s" % (w, p)
        fl.step(ins, [b + ".sol", b + ".json"], ["python3", "build_outreach.py", "--only", "%d:%s" % (w, p), "test_cal.csv", "data_main", "outreach.json", "."])
        fl.step([b + ".sol"], [], ["solve", "run", "--node-limit", str(NODE_LIMIT)], stdin_file=b + ".sol", stdout_file=b + ".plan.json")
        fl.step(["verify_input.py", b + ".sol", b + ".plan.json"], [b + ".verify.in"], ["python3", "verify_input.py", b + ".sol", b + ".plan.json", b + ".verify.in"])
        fl.step([], [], ["solve", "verify"], stdin_file=b + ".verify.in", stdout_file=b + ".verify.json")
        o = "oracle/models/W%d_%s" % (w, p)
        fl.step(ins + ["data_main/truth/refill_hazard.csv"], [o + ".sol", o + ".json"], ["python3", "build_outreach.py", "--true-p", "--only", "%d:%s" % (w, p), "test_cal.csv", "data_main", "outreach.json", "oracle"])
        fl.step([o + ".sol"], [], ["solve", "run", "--node-limit", str(NODE_LIMIT)], stdin_file=o + ".sol", stdout_file=o + ".plan.json")
    return cells


def chosen(plan, n):
    """The outreach index (0..3) or -1 for each of n events, from the plan's variables."""
    out = []
    for e in range(n):
        ks = [k for k, a in enumerate(("xc", "xr", "xs", "xd")) if plan["x"]["%s[%d]" % (a, e)] > 0.5]
        out.append(ks)
    return out


def toy():
    """Five events, four outreaches, small capacities: every assignment tried, the value written out here and not taken from the builder."""
    cfg = json.loads((HERE / "outreach.json").read_text())
    cfg["capacity_per_pharmacy_week"] = {"minutes": 8.0, "money": 9.0, "delivery_slots": 1}
    ev = [(30, 0.40), (30, 0.10), (90, 0.25), (30, 0.55), (60, 0.05)]
    d = instance(ev, cfg)
    u = [cfg["uplift"][a] for a in ACTIONS]
    m = [cfg["minutes"][a] for a in ACTIONS]
    c = [cfg["money"][a] for a in ACTIONS]
    best = None
    for asg in itertools.product(range(5), repeat=5):  # 4 = no outreach
        mi = sum(m[k] for k in asg if k < 4)
        mo = sum(c[k] for k in asg if k < 4)
        sl = sum(1 for k in asg if k == 3)
        if mi > 8.0 + 1e-9 or mo > 9.0 + 1e-9 or sl > 1:
            continue
        v = sum(days * p * u[k] for (days, p), k in zip(ev, asg) if k < 4)
        if best is None or v > best:
            best = v
    return model_text(d), best


def judge_plan(fl, cells):
    problems, report = [], []
    cfg = json.loads(fl.read("outreach.json"))
    U = [cfg["uplift"][a] for a in ACTIONS]
    M = [cfg["minutes"][a] for a in ACTIONS]
    C = [cfg["money"][a] for a in ACTIONS]
    cap = cfg["capacity_per_pharmacy_week"]
    solve = str(fl.tmp / "programs" / "solve")
    truth = {(r["patient"], r["item"], int(r["due_week"])): int(r["true_lapse_ppm"]) / 1e6 for r in pc.table(fl.read("data_main/truth/refill_hazard.csv"))}
    days = {r["patient"]: int(r["refill_interval_days"]) for r in pc.table(fl.read("data_main/patients.csv"))}
    home = {r["patient"]: r["home_pharmacy"] for r in pc.table(fl.read("data_main/patients.csv"))}
    pcal = {}
    order = {}
    for r in pc.table(fl.read("test_cal.csv")):
        k = (int(r["due_week"]), home[r["patient"]])
        pcal[(r["patient"], r["item"], int(r["due_week"]))] = float(r["p"])
        order.setdefault(k, []).append((r["patient"], r["item"]))
    status_bad, over, twice, obj_bad, binding = [], [], [], [], 0
    tot = {"plan": 0.0, "oracle": 0.0, "base": 0.0, "expected": 0.0}
    n_events = 0
    differ = 0
    gaps = []
    for w, p in cells:
        b = "models/W%d_%s" % (w, p)
        plan, ver = json.loads(fl.read(b + ".plan.json")), json.loads(fl.read(b + ".verify.json"))
        orc = json.loads(fl.read("oracle/models/W%d_%s.plan.json" % (w, p)))
        if plan.get("status") != "optimal":
            status_bad.append("%s %s (objective %.6f, bound %.6f)" % (b, plan.get("status"), plan["objective"], plan["bound"]))
            gaps.append(abs(plan["bound"] - plan["objective"]) / max(1.0, abs(plan["objective"])))
        if orc.get("status") not in ("optimal", "feasible"):
            status_bad.append("oracle plan %s %s" % (b, orc.get("status")))
            continue
        if ver.get("status") != "verified" or not ver.get("objective_checked"):
            status_bad.append("%s verify %s" % (b, ver.get("status")))
        evs = order[(w, p)]
        n = len(evs)
        n_events += n
        ch, och = chosen(plan, n), chosen(orc, n)
        differ += 1 if ch != och else 0
        # G6 from the raw files: one outreach per event, the three limits, the objective
        mi = mo = sl = 0.0
        obj = 0.0
        for e, (pa, it) in enumerate(evs):
            if len(ch[e]) > 1:
                twice.append("%s event %d has %d outreaches" % (b, e, len(ch[e])))
            for k in ch[e]:
                mi += M[k]; mo += C[k]; sl += 1 if k == 3 else 0
                obj += days[pa] * pcal[(pa, it, w)] * U[k]
        if mi > cap["minutes"] + EPS or mo > cap["money"] + EPS or sl > cap["delivery_slots"] + EPS:
            over.append("%s minutes %.2f/%s money %.2f/%s slots %d/%s" % (b, mi, cap["minutes"], mo, cap["money"], sl, cap["delivery_slots"]))
        if abs(obj - plan["objective"]) > 1e-6 * max(1.0, abs(obj)):
            obj_bad.append("%s formula %.6f, solve %.6f" % (b, obj, plan["objective"]))
        if mi >= cap["minutes"] - 1e-6 or mo >= cap["money"] - 1e-6 or sl >= cap["delivery_slots"] - 1e-6:
            binding += 1
        # G9: the true value of the plan, of the oracle plan and of the baseline; and the value the plan expects
        def true_value(chs):
            return sum(days[pa] * truth[(pa, it, w)] * U[k] for (pa, it), ks in zip(evs, chs) for k in ks)
        tot["plan"] += true_value(ch)
        tot["oracle"] += true_value(och)
        tot["expected"] += obj
        bm = bmo = 0.0
        bch = []
        for pa, it in evs:  # the baseline: in the order listed, the cheapest outreach (a reminder) while the minutes and the money last
            k = min(range(4), key=lambda j: (M[j], C[j]))
            if bm + M[k] <= cap["minutes"] + EPS and bmo + C[k] <= cap["money"] + EPS:
                bm += M[k]; bmo += C[k]
                bch.append([k])
            else:
                bch.append([])
        tot["base"] += true_value(bch)
    nc = len(cells)
    if gaps:
        report.append("G5 (added after the run, not a margin fixed before it): the %d plans that stopped at the node limit are feasible and verified, with a proven gap of at most %.2e of the objective" % (len(gaps), max(gaps)))
    report.append("G5 %d decisions (%d events): %d not optimal or not verified%s" % (nc, n_events, len(status_bad), (" (e.g. %s)" % status_bad[0]) if status_bad else ""))
    if status_bad:
        problems.append("G5: %d plans are not optimal and verified, e.g. %s" % (len(status_bad), status_bad[0]))
    py = os.environ.get("SCIPY_PYTHON", sys.executable)
    if os.environ.get("SKIP_ORACLE") == "1":
        report.append("G5 oracle: SKIPPED on purpose (SKIP_ORACLE=1)")
    else:
        r = subprocess.run([py, str(HERE / "scripts" / "oracle_highs_b.py"), str(fl.root)], capture_output=True, text=True)
        try:
            o = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            o = {"ok": False, "rule": "oracle.no-output"}
        if o.get("rule") == "oracle.no-scipy":
            report.append("G5 oracle: NOT RUN (no scipy for %s)" % py)
            problems.append("G5: the HiGHS oracle was not run (no scipy); set SCIPY_PYTHON, or SKIP_ORACLE=1 to leave it out knowingly")
        else:
            report.append("G5 HiGHS: %d instances, worst relative gap %.2e%s" % (o.get("instances", 0), o.get("worst_relative_gap", float("nan")), "" if o.get("ok") else " (BAD: %s)" % o.get("bad")))
            if not o.get("ok") or o.get("instances") != nc:
                problems.append("G5: HiGHS and solve disagree, or did not cover every decision: %s" % json.dumps(o)[:300])
    text, best = toy()
    r = subprocess.run([solve, "run"], input=text, capture_output=True, text=True)
    try:
        got = json.loads(r.stdout)["objective"]
    except (ValueError, KeyError):
        got = None
    report.append("G5 toy (5 events, 5^5 = 3,125 assignments tried): enumeration %.6f, solve %s" % (best, ("%.6f" % got) if got is not None else "none"))
    if got is None or abs(got - best) > 1e-6 * max(1.0, abs(best)):
        problems.append("G5: on the toy decision solve's optimum is %s, an enumeration gives %.6f" % (got, best))
    report.append("G6 %d plans: %d over the minutes, the money or the slots, %d events given two outreaches, %d whose objective is not the formula's" % (nc, len(over), len(twice), len(obj_bad)))
    for k, lst in (("limits", over), ("one-outreach", twice), ("objective", obj_bad)):
        if lst:
            problems.append("G6: %d plans break the %s rule, e.g. %s" % (len(lst), k, lst[0]))
    # tamper: a plan with two outreaches on an event, and one over the minutes, must be refused with a rule tag
    base = "models/W%d_%s" % cells[0]
    model, plan = fl.read(base + ".sol"), json.loads(fl.read(base + ".plan.json"))
    n0 = len(order[cells[0]])
    ch0 = chosen(plan, n0)
    e_on = next((e for e in range(n0) if ch0[e]), 0)
    t1 = json.loads(json.dumps(plan))
    t1["x"]["xr[%d]" % e_on] = 1.0
    t1["x"]["xc[%d]" % e_on] = 1.0
    t2 = json.loads(json.dumps(plan))
    for e in range(n0):
        t2["x"]["xc[%d]" % e] = 1.0  # a call for everyone: far past the minutes (and the money)
        for a in ("xr", "xs", "xd"):
            t2["x"]["%s[%d]" % (a, e)] = 0.0
    for label, pl in (("an event given a call and a reminder", t1), ("a call for every event", t2)):
        r = subprocess.run([solve, "verify"], input=model.rstrip("\n") + "\n---\n" + json.dumps(pl) + "\n", capture_output=True, text=True)
        tag = msg = None
        try:
            doc = json.loads((r.stderr or r.stdout).strip().splitlines()[0])
            e = doc.get("error")
            tag = e if isinstance(e, str) else (e or {}).get("rule")
            msg = json.dumps(doc)[:200]
        except (ValueError, IndexError, AttributeError):
            pass
        report.append("G6 tamper, %s: solve verify exit %d, rule %s" % (label, r.returncode, tag))
        if r.returncode == 0:
            problems.append("G6: solve verify accepted %s" % label)
        elif not (tag or "").startswith("solve."):
            problems.append("G6: solve verify refused %s without a solve.* rule tag (%s)" % (label, msg))
    # G9
    pl, orc, base_v, exp = tot["plan"], tot["oracle"], tot["base"], tot["expected"]
    report.append("G9 true value over %d decisions (expected adherent days gained): plan %.1f, oracle plan %.1f, baseline %.1f; the value the plan expects %.1f" % (nc, pl, orc, base_v, exp))
    report.append("G9 plan/oracle %.4f (limits %.2f to %.2f), plan/baseline %.2f (at least %.2f), expected against true %+.4f (limit %.2f), %d of %d decisions bind a limit (at least %.0f%%)" % (
        pl / orc, G9_VS_ORACLE_MIN, G9_VS_ORACLE_MAX, pl / base_v, G9_VS_BASELINE_MIN, (exp - pl) / pl, G9_EXPECTED_VS_TRUE, binding, nc, 100 * G9_BINDING_SHARE))
    if pl < G9_VS_ORACLE_MIN * orc:
        problems.append("G9: the plan's true value %.1f is below %.2f of the oracle plan's %.1f" % (pl, G9_VS_ORACLE_MIN, orc))
    if pl > G9_VS_ORACLE_MAX * orc * (1 + 1e-9):
        problems.append("G9: the plan's true value %.1f beats the oracle plan's %.1f: the planner or the evaluation has seen the truth" % (pl, orc))
    if pl < G9_VS_BASELINE_MIN * base_v:
        problems.append("G9: the plan's true value %.1f is below %.2f times the baseline's %.1f" % (pl, G9_VS_BASELINE_MIN, base_v))
    if abs(exp - pl) > G9_EXPECTED_VS_TRUE * pl:
        problems.append("G9: the value the plan expects (%.1f) is not within %.2f of its true value (%.1f)" % (exp, G9_EXPECTED_VS_TRUE, pl))
    if differ == 0:
        problems.append("G9: the plan equals the oracle plan in every decision: a planner that sees only calibrated probabilities does not do that, so it has seen the truth")
    if binding < G9_BINDING_SHARE * nc:
        problems.append("G9: only %d of %d decisions bind a limit: the decision is trivial" % (binding, nc))
    return problems, report


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        for f in ("features_b.py", "pred_join.py", "apply_isotonic.py", "build_outreach.py", "verify_input.py", "outreach.json"):
            shutil.copy(HERE / f, fl.root / f)
        cells = run_plan(fl)
        problems, report = pb.judge(fl)
        p2, r2 = judge_plan(fl, cells)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return problems + p2, report + r2


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("one-outreach-row-dropped", "build_outreach.py", _x('t += "    forall e in 0..n: one: xc[e] + xr[e] + xs[e] + xd[e] <= 1', ';\\n"'), 't += ""', "G6"),
    ("minutes-row-dropped", "build_outreach.py", _x('t += "    minutes: sum e in 0..n: (%s * xc[e]', ' + %s * xr[e]'), 't += "" and "    minutes: sum e in 0..n: (%s * xc[e] + %s * xr[e]', "G6"),
    ("slots-row-dropped", "build_outreach.py", _x('t += "    slots: sum e in 0..n: xd[e] <= %d', ';\\n" % d["cap_slots"]'), 't += ""', "G6"),
    ("uplift-wrong-in-the-model-text", "build_outreach.py", _x('g = [[d["days"][e] * d["p"][e] * d["upl', 'ift"][k] for e'), 'g = [[d["days"][e] * d["p"][e] * 0.2 for e', "G6"),
    ("planner-reads-the-truth", "build_outreach.py", _x("only, true_p = None, ", "False"), "only, true_p = None, True", "G9"),
    ("planner-uses-the-uncalibrated-p", "build_outreach.py", _x('float(r["', 'p"])'), 'float(r["p_raw"])', "G9"),
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
                print("mutant %-34s CANNOT BE APPLIED (%d occurrences in %s)" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            env = dict(os.environ, FLOW_REPO=str(pc.REPO), TABLE=pc.exe("table", "TABLE"), STATS=pc.exe("stats", "STATS"), ML=pc.exe("ml", "ML"), SOLVE=pc.exe("solve", "SOLVE"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "plan_b.py")], capture_output=True, text=True, env=env, cwd=td, timeout=7200)
            out = r.stdout + r.stderr
            if only:
                print(out[-2500:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-34s by %s" % (name, hit[0][:120]))
            else:
                survived += 1
                print("SURVIVED %-34s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
    print("%d mutants, %d survived" % (len(MUTANTS), survived))
    return 1 if survived else 0


def main():
    if "--mutant" in sys.argv:
        return mutants(sys.argv[sys.argv.index("--mutant") + 1])
    if "--mutants" in sys.argv:
        return mutants()
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    problems, report = run(keep)
    for ln in report:
        print(ln)
    for p in problems:
        print(p)
    if problems:
        return 1
    print("plan_b: ok (G2, G4, G8 of U3a and G5, G6, G9, G7 of U3b hold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
