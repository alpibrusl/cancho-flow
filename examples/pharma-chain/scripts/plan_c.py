#!/usr/bin/env python3
"""U2b: pharmacy replenishment as a decision for `solve`, run as recorded `flow` steps after the forecast of pipeline_c.py, and the gates G5, G6 and G7.

    CANCHO=<compiler> [SCIPY_PYTHON=<a python with scipy>] python3 scripts/plan_c.py [--mutants] [--mutant NAME]

Per pharmacy and held-out week (96 of them): build the model from the forecast and the stock (build_models.py), `solve run`, join, `solve verify`: four recorded steps
each. Then:
  G5  every plan is `verified` by `solve verify`; HiGHS (scipy) solves each decision from the data and gets the same optimum; and on a toy instance the optimum equals a
      brute-force enumeration of the cost written out here, apart from the builder's code.
  G6  recomputed from the raw stock and the capacities, no plan orders more than the room that is left, or a fractional pack, or more packs than allowed; and a plan with an
      order past its bound or past the room is refused by `solve verify` with a rule tag.
  G7  as in pipeline_c.py.
There is also an exploratory comparison with the pharmacy's own ordering (printed, with no margin: none was fixed before it, so it is not a claim).
SCIPY_PYTHON missing or without scipy: G5's oracle is reported NOT RUN and that fails the gate, unless SKIP_ORACLE=1 says it was left out on purpose.
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
import pipeline_c as pc  # noqa: E402
from build_models import instance, model_text  # noqa: E402

DROP = "pharmacy,item,week"


def run_plan(fl):
    pc.run_main(fl)
    fl.step(["m_boost.ml", "test.csv"], [], ["ml", "--root", ".", "--model-file", "m_boost.ml", "--drop", DROP, "--limit", "6000", "predict", "test.csv"], stdout_file="pred.json")
    cells = sorted({(int(r["week"]), r["pharmacy"]) for r in pc.table(fl.read("test.csv"))})
    ins = ["build_models.py", "data_main/dispensing.csv", "data_main/items.csv", "data_main/pharmacies.csv", "test.csv", "pred.json", "costs.json"]
    for w, p in cells:
        b = "models/W%d_%s" % (w, p)
        fl.step(ins, [b + ".sol", b + ".json"], ["python3", "build_models.py", "--only", "%d:%s" % (w, p), "data_main", "test.csv", "pred.json", "costs.json", "."])
        fl.step([b + ".sol"], [], ["solve", "run"], stdin_file=b + ".sol", stdout_file=b + ".plan.json")
        fl.step(["verify_input.py", b + ".sol", b + ".plan.json"], [b + ".verify.in"], ["python3", "verify_input.py", b + ".sol", b + ".plan.json", b + ".verify.in"])
        fl.step([], [], ["solve", "verify"], stdin_file=b + ".verify.in", stdout_file=b + ".verify.json")
    return cells


def toy():
    """A small decision whose optimum is found by trying every order, with the cost written out here and the target computed here."""
    costs = json.loads((HERE / "costs.json").read_text())
    items = [
        {"pack": 10, "cold": 0, "critical": 1, "controlled": 0, "shelf_weeks": 4},
        {"pack": 5, "cold": 1, "critical": 0, "controlled": 0, "shelf_weeks": 26},
        {"pack": 20, "cold": 0, "critical": 0, "controlled": 1, "shelf_weeks": 52},
        {"pack": 12, "cold": 1, "critical": 0, "controlled": 0, "shelf_weeks": 52},
    ]
    f, stock = [8.0, 6.0, 45.0, 3.0], [3, 0, 0, 30]
    d = instance(items, f, stock, 40, 200, costs)
    z = costs["z_milli"]["value"] / 1000.0
    best = None
    for q in itertools.product(*[range(0, (2 if it["controlled"] else 6) + 1) for it in items]):
        cold_units = sum(it["pack"] * qi for it, qi in zip(items, q) if it["cold"])
        warm_units = sum(it["pack"] * qi for it, qi in zip(items, q) if not it["cold"])
        if cold_units > max(0, 40 - sum(s for it, s in zip(items, stock) if it["cold"])) or warm_units > max(0, 200 - sum(s for it, s in zip(items, stock) if not it["cold"])):
            continue
        cost = 0.0
        for it, fi, si, qi in zip(items, f, stock, q):
            have = si + it["pack"] * qi
            target = fi + z * math.sqrt(max(fi, 1.0))
            cover = min(52, it["shelf_weeks"]) * fi
            pen = costs["penalty_per_unit_short_critical"]["value"] if it["critical"] else costs["penalty_per_unit_short"]["value"]
            cost += pen * max(0.0, target - have) + costs["waste_per_unit"]["value"] * max(0.0, have - cover) + costs["holding_per_unit"]["value"] * it["pack"] * qi
        if best is None or cost < best:
            best = cost
    return model_text(d), best


def judge_plan(fl, cells):
    problems, report = [], []
    solve = str(fl.tmp / "programs" / "solve")
    status_bad, tag_cells, over_room, frac, over_q, obj_bad = [], 0, [], [], [], []
    short_p = short_t = left_p = left_t = ord_p = ord_t = crit_short_p = crit_short_t = 0.0
    truth = {(r["pharmacy"], r["item"], int(r["week"])): int(r["demand"]) for r in pc.table(fl.read("data_main/truth/demand.csv"))}
    disp = {(r["pharmacy"], r["item"], int(r["week"])): r for r in pc.table(fl.read("data_main/dispensing.csv"))}
    first_zero_room = None
    for w, p in cells:
        b = "models/W%d_%s" % (w, p)
        d, plan, ver = json.loads(fl.read(b + ".json")), json.loads(fl.read(b + ".plan.json")), json.loads(fl.read(b + ".verify.json"))
        if plan.get("status") != "optimal":
            status_bad.append("%s %s" % (b, plan.get("status")))
            continue
        if ver.get("status") != "verified" or not ver.get("objective_checked"):
            status_bad.append("%s verify %s" % (b, ver.get("status")))
        m = d["n"]
        q = [plan["x"]["q[%d]" % i] for i in range(m)]
        for i, qi in enumerate(q):
            if abs(qi - round(qi)) > 1e-6:
                frac.append("%s q[%d]=%s" % (b, i, qi))
            if qi < -1e-6 or qi > d["qmax"][i] + 1e-6:
                over_q.append("%s q[%d]=%s > %d" % (b, i, qi, d["qmax"][i]))
        # the room, from the raw stock and the capacities (not from the room the model was given)
        room_c = max(0, d["cap_cold"] - sum(s for s, c in zip(d["stock"], d["cold"]) if c))
        room_s = max(0, d["cap_shelf"] - sum(s for s, c in zip(d["stock"], d["cold"]) if not c))
        oc = sum(d["pack"][i] * q[i] for i in range(m) if d["cold"][i])
        os_ = sum(d["pack"][i] * q[i] for i in range(m) if not d["cold"][i])
        if oc > room_c + 1e-6 or os_ > room_s + 1e-6:
            over_room.append("%s ordered %.0f cold into room %d, %.0f other into room %d" % (b, oc, room_c, os_, room_s))
        if first_zero_room is None and room_c == 0 and any(d["cold"]):
            first_zero_room = (b, d)
        # the objective, from the formula
        obj = 0.0
        for i in range(m):
            have = d["stock"][i] + d["pack"][i] * q[i]
            obj += d["pen"][i] * max(0.0, d["target"][i] - have) + d["waste"] * max(0.0, have - d["cover"][i]) + d["holding"] * d["pack"][i] * q[i]
        if abs(obj - plan["objective"]) > 1e-6 * max(1.0, abs(obj)):
            obj_bad.append("%s formula %.6f, solve %.6f" % (b, obj, plan["objective"]))
        # exploratory: the plan against the pharmacy's own order, under the true demand of that week
        for i, it in enumerate(d["items"]):
            D = truth[(p, it, w)]
            S = d["stock"][i]
            av_p = S + d["pack"][i] * q[i]
            av_t = S + int(disp[(p, it, w - 1)]["ordered"])
            sp, st = max(0, D - av_p), max(0, D - av_t)
            short_p += sp; short_t += st
            left_p += max(0, av_p - D); left_t += max(0, av_t - D)
            ord_p += d["pack"][i] * q[i]; ord_t += int(disp[(p, it, w - 1)]["ordered"])
            if d["pen"][i] > 10:
                crit_short_p += sp; crit_short_t += st
    n = len(cells)
    report.append("G5 %d decisions: %d with status other than optimal or not verified%s" % (n, len(status_bad), (" (e.g. %s)" % status_bad[0]) if status_bad else ""))
    if status_bad:
        problems.append("G5: %d plans are not optimal and verified, e.g. %s" % (len(status_bad), status_bad[0]))
    # HiGHS
    py = os.environ.get("SCIPY_PYTHON", sys.executable)
    if os.environ.get("SKIP_ORACLE") == "1":
        report.append("G5 oracle: SKIPPED on purpose (SKIP_ORACLE=1)")
    else:
        r = subprocess.run([py, str(HERE / "scripts" / "oracle_highs.py"), str(fl.root)], capture_output=True, text=True)
        try:
            o = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            o = {"ok": False, "rule": "oracle.no-output"}
        if o.get("rule") == "oracle.no-scipy":
            report.append("G5 oracle: NOT RUN (no scipy for %s)" % py)
            problems.append("G5: the HiGHS oracle was not run (no scipy); set SCIPY_PYTHON, or SKIP_ORACLE=1 to leave it out knowingly")
        else:
            report.append("G5 HiGHS: %d instances, worst relative gap %.2e%s" % (o.get("instances", 0), o.get("worst_relative_gap", float("nan")), "" if o.get("ok") else " (BAD: %s)" % o.get("bad")))
            if not o.get("ok") or o.get("instances") != n:
                problems.append("G5: HiGHS and solve disagree, or did not cover every decision: %s" % json.dumps(o)[:300])
    # toy enumeration
    text, best = toy()
    r = subprocess.run([solve, "run"], input=text, capture_output=True, text=True)
    try:
        got = json.loads(r.stdout)["objective"]
    except (ValueError, KeyError):
        got = None
    report.append("G5 toy (4 items, %s orders tried): enumeration %.6f, solve %s" % ("1,029" if True else "", best, ("%.6f" % got) if got is not None else "none"))
    if got is None or abs(got - best) > 1e-6 * max(1.0, abs(best)):
        problems.append("G5: on the toy decision solve's optimum is %s, an enumeration of every order gives %.6f" % (got, best))
    # G6
    report.append("G6 %d plans: %d beyond the room, %d fractional packs, %d beyond the packs allowed, %d whose objective is not the formula's" % (n, len(over_room), len(frac), len(over_q), len(obj_bad)))
    for k, lst in (("room", over_room), ("fractional pack", frac), ("packs allowed", over_q), ("objective", obj_bad)):
        if lst:
            problems.append("G6: %d plans break the %s rule, e.g. %s" % (len(lst), k, lst[0]))
    # tamper: a plan with a bound broken must be refused by solve verify with a rule tag
    base = "models/W%d_%s" % cells[0]
    model, plan = fl.read(base + ".sol"), json.loads(fl.read(base + ".plan.json"))
    d0 = json.loads(fl.read(base + ".json"))
    tampers = [("an order past its bound", "q[0]", d0["qmax"][0] + 1, "solve.bound-violated")]
    if first_zero_room:
        b0, d1 = first_zero_room
        ci = next(i for i in range(d1["n"]) if d1["cold"][i])
        model, plan = fl.read(b0 + ".sol"), json.loads(fl.read(b0 + ".plan.json"))
        tampers.append(("an order into a full refrigerated space", "q[%d]" % ci, 1, "solve.row-violated"))
    for label, var, val, tag in tampers:
        pl = json.loads(json.dumps(plan))
        pl["x"][var] = val
        r = subprocess.run([solve, "verify"], input=model.rstrip("\n") + "\n---\n" + json.dumps(pl) + "\n", capture_output=True, text=True)
        got_tag = None
        try:
            doc = json.loads((r.stderr or r.stdout).strip().splitlines()[0])
            e = doc.get("error")
            got_tag = e if isinstance(e, str) else (e or {}).get("rule")
        except (ValueError, IndexError, AttributeError):
            pass
        report.append("G6 tamper, %s: solve verify exit %d, rule %s" % (label, r.returncode, got_tag))
        if r.returncode == 0:
            problems.append("G6: solve verify accepted %s" % label)
        elif got_tag != tag:
            problems.append("G6: solve verify refused %s with rule %s, not %s" % (label, got_tag, tag))
    # exploratory
    report.append("exploratory (no margin was fixed for it: not a claim), %d decisions against the pharmacy's own order, the true demand of the week: units short %.0f (plan) against %.0f (own), of which "
                  "critical items %.0f against %.0f; units left over %.0f against %.0f; units ordered %.0f against %.0f" % (n, short_p, short_t, crit_short_p, crit_short_t, left_p, left_t, ord_p, ord_t))
    return problems, report


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        shutil.copy(HERE / "build_models.py", fl.root / "build_models.py")
        shutil.copy(HERE / "verify_input.py", fl.root / "verify_input.py")
        shutil.copy(HERE / "costs.json", fl.root / "costs.json")
        cells = run_plan(fl)
        problems, report = pc.judge_forecast(fl)
        p2, r2 = judge_plan(fl, cells)
        p3, r3 = pc.judge_records(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return problems + p2 + p3, report + r2 + r3


MUTANTS = [
    ("cold-room-dropped", "build_models.py", '    if cold:\n        t += "    coldroom: "', '    if False:\n        t += "    coldroom: "', "G6"),
    ("room-ignores-stock", "build_models.py", 'room_cold = max(0, cap_cold - sum(s for it, s in zip(items, stock) if it["cold"]))', "room_cold = cap_cold", "G6"),
    ("target-sign-flipped", "build_models.py", "target = [fi + z * (max(fi, 1.0) ** 0.5) for fi in f]", "target = [fi - z * (max(fi, 1.0) ** 0.5) for fi in f]", "G5"),
    ("wrong-stock-in-the-model-text", "build_models.py", 'arr(d["stock"]), arr(d["pack"]), arr(d["pen"])', 'arr([x + 1 for x in d["stock"]]), arr(d["pack"]), arr(d["pen"])', "G5"),
    ("waste-cost-zero-in-the-model-text", "build_models.py", 'num(float(d["waste"]))', '"0"', "G5"),
    ("controlled-cap-dropped", "build_models.py", 'if d["qmax"][i] < max(d["qmax"]):', "if False:", "G5"),
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
            r = subprocess.run([sys.executable, str(tree / "scripts" / "plan_c.py")], capture_output=True, text=True, env=env, cwd=td, timeout=3600)
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
    print("plan_c: ok (G2, G4, G5, G6 and G7 hold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
