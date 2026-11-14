#!/usr/bin/env python3
"""U7c: the experiment (docs/use-cases.md section 7a, G21 to G23 and the four claims, committed before this was written).

    CANCHO=<compiler> SCIPY_PYTHON=<python with scipy> python3 scripts/experiment.py [--seeds 20261112,1] [--out DIR] [--first 90 --last 101 --end 103] [--judge-only]

For each seed: arm D (the batch twin, the twin's own policies) and the arms C, B and T of closed_loop.py run side by side; arm T of the first seed runs twice for G22. Then G21 to G23, the outcomes of each arm,
and the claims, each on every seed.
"""
import csv
import hashlib
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
import closed_loop as cl  # noqa: E402
import pipeline_c as pc  # noqa: E402

CLAIM1, CLAIM2, CLAIM3, CLAIM4 = 0.95, 1.5, 1.05, 0.90   # the margins of docs/use-cases.md section 7a (U7c), fixed before this was written
EPS = 1e-6


def table(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def outcomes(data, first, last, end):
    disp = table(os.path.join(data, "dispensing.csv"))
    dem = table(os.path.join(data, "truth", "demand.csv"))
    refills = table(os.path.join(data, "refills.csv"))
    o = {"orders_units": 0, "stockout_cells": 0, "units_short": 0, "written_off": 0, "events": 0, "lapses": 0}
    for r, d in zip(disp, dem):
        w = int(r["week"])
        if first <= w <= last:
            o["orders_units"] += int(r["ordered"])
        if first + 1 <= w <= end:
            o["stockout_cells"] += int(r["stockout"])
            o["units_short"] += int(d["demand"]) - int(r["units"])
            o["written_off"] += int(r["written_off"])
    for r in refills:
        if first + 1 <= int(r["due_week"]) <= end:
            o["events"] += 1
            o["lapses"] += int(r["filled"] == "0")
    return o


def tree_digest(root):
    h = hashlib.sha256()
    for f in sorted(pathlib.Path(root).rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(root)).encode() + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def main(argv):
    def arg(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    seeds = [int(x) for x in arg("--seeds", "20261112,1").split(",")]
    first, last, end = int(arg("--first", 90)), int(arg("--last", 101)), int(arg("--end", 103))
    base = pathlib.Path(arg("--out", "experiment_out")).resolve()
    if "--judge-only" not in argv:
        # the twin refuses an absolute --out: the batch arms run from their own directory
        base.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, FLOW_TIMEOUT_MS=os.environ.get("FLOW_TIMEOUT_MS", "600000"))
        procs = []
        for s in seeds:
            for a in ("C", "B", "T"):
                procs.append(("%s_%d" % (a, s), subprocess.Popen([sys.executable, str(HERE / "scripts" / "closed_loop.py"), "--arm", a, "--seed", str(s), "--out", str(base / ("%s_%d" % (a, s))), "--first", str(first), "--last", str(last), "--end", str(end)],
                                                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)))
        procs.append(("T2_%d" % seeds[0], subprocess.Popen([sys.executable, str(HERE / "scripts" / "closed_loop.py"), "--arm", "T", "--seed", str(seeds[0]), "--out", str(base / ("T2_%d" % seeds[0])), "--first", str(first), "--last", str(last), "--end", str(end)],
                                                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)))
        for s in seeds:
            dd = base / ("D_%d" % s)
            dd.mkdir(exist_ok=True)
            shutil.copy(HERE / "world.json", dd / "world.json")
            r = subprocess.run([sys.executable, str(HERE / "twin.py"), "generate", "--world", "world.json", "--seed", str(s), "--size", "large", "--tables", cl.FULL, "--out", "data", "--overwrite"], cwd=str(dd), capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit("experiment: the batch arm D failed: " + r.stderr[-300:])
        failed = []
        for name, p in procs:
            out = p.communicate()[0]
            if p.returncode != 0:
                failed.append("%s: %s" % (name, out.strip()[-300:]))
        if failed:
            for f in failed:
                print("experiment: an arm stopped: " + f)
            return 1
    return judge(seeds, base, first, last, end)


def judge(seeds, base, first, last, end):
    problems, report = [], []
    py = os.environ.get("SCIPY_PYTHON", sys.executable)
    res = {}
    for s in seeds:
        dd = base / ("D_%d" % s) / "data"
        res[(s, "D")] = outcomes(dd, first, last, end)
        for a in ("C", "B", "T"):
            res[(s, a)] = outcomes(base / ("%s_%d" % (a, s)) / "root" / "data", first, last, end)
    # ---- G21 ----
    for name in sorted(p.name for p in base.iterdir() if p.is_dir() and p.name[0] in "CBT"):  # C_*, B_*, T_*, T2_*
        root = base / name / "root"
        arm = name[0]
        nplans = nbad = nstopped = 0
        for kind in ("c", "b"):
            if not (root / kind / "models").exists():
                continue
            for pj in sorted((root / kind / "models").glob("W*_P*.plan.json")):
                b = str(pj)[:-len(".plan.json")]
                plan, ver = json.loads(pj.read_text()), json.loads(pathlib.Path(b + ".verify.json").read_text())
                nplans += 1
                nstopped += int(plan.get("status") != "optimal")
                if plan.get("status") not in ("optimal", "feasible") or ver.get("status") != "verified" or not ver.get("objective_checked"):
                    nbad += 1
            if os.environ.get("SKIP_ORACLE") != "1":
                o = subprocess.run([py, str(HERE / "scripts" / ("oracle_highs.py" if kind == "c" else "oracle_highs_b.py")), str(root / kind)], capture_output=True, text=True)
                try:
                    oj = json.loads(o.stdout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    oj = {"ok": False, "rule": "oracle.no-output"}
                if oj.get("rule") == "oracle.no-scipy":
                    problems.append("G21: the HiGHS oracle was not run (no scipy); set SCIPY_PYTHON, or SKIP_ORACLE=1 to leave it out knowingly")
                elif not oj.get("ok"):
                    problems.append("G21: %s: HiGHS disagrees with solve for the %s plans: %s" % (name, kind, json.dumps(oj)[:200]))
        # the decisions against the plans, recomputed from the plan files and the data files
        mism = 0
        for w in range(first, last + 1):
            doc = json.loads((root / "decisions" / ("week-%d.json" % w)).read_text())
            want_orders, want_out = {}, {}
            if arm in ("C", "T"):
                for pj in sorted((root / "c" / "models").glob("W%d_P*.json" % (w + 1))):
                    if pj.name.endswith(".plan.json") or pj.name.endswith(".verify.json"):
                        continue
                    d, plan = json.loads(pj.read_text()), json.loads(pathlib.Path(str(pj)[:-5] + ".plan.json").read_text())
                    for i, it in enumerate(d["items"]):
                        want_orders[(d["pharmacy"], it)] = d["pack"][i] * int(round(plan["x"]["q[%d]" % i]))
            if arm in ("B", "T"):
                for pj in sorted((root / "b" / "models").glob("W%d_P*.json" % (w + 1))):
                    if pj.name.endswith(".plan.json") or pj.name.endswith(".verify.json"):
                        continue
                    d, plan = json.loads(pj.read_text()), json.loads(pathlib.Path(str(pj)[:-5] + ".plan.json").read_text())
                    for e, ev in enumerate(d["events"]):
                        pa_, it = ev.split("/")
                        for act, key in (("call", "xc"), ("reminder", "xr"), ("switch90", "xs"), ("delivery", "xd")):
                            if plan["x"]["%s[%d]" % (key, e)] > 0.5:
                                want_out[(pa_, it)] = act
            got_orders = {(e["pharmacy"], e["item"]): e["units"] for e in doc.get("orders", [])}
            got_out = {(e["patient"], e["item"]): e["action"] for e in doc.get("outreach", [])}
            if got_orders != want_orders or got_out != want_out:
                mism += 1
        # the models: fitted once, on weeks up to 89, and the model on disk is the one fitted on that file
        leak = []
        for rel, col, lim in (("c_train.csv", "week", cl.FIT_THROUGH), ("b_fit.csv", "due_week", cl.FIT_THROUGH), ("b_cal.csv", "due_week", cl.FIT_THROUGH)):
            fp = root / rel
            if fp.exists() and max(int(r[col]) for r in table(str(fp))) > lim:
                leak.append("%s holds a %s after %d" % (rel, col, lim))
        for mfile, fitj in (("c_model.ml", "c_fit.json"), ("b_model.ml", "b_fit.json")):
            if (root / mfile).exists():
                fj = json.loads((root / fitj).read_text())["data"]
                if hashlib.sha256((root / mfile).read_bytes()).hexdigest() != fj["sha256"]:
                    leak.append("%s is not the model its fit printed" % mfile)
        report.append("G21 %s: %d plans, %d not verified, %d stopped at the node limit; decisions against plans: %d weeks differ; models: %s" % (name, nplans, nbad, nstopped, mism, "; ".join(leak) or "fitted once on weeks up to %d" % cl.FIT_THROUGH))
        if nbad:
            problems.append("G21: %s: %d plans are not verified" % (name, nbad))
        if mism:
            problems.append("G21: %s: %d weeks of decisions differ from what their plans say" % (name, mism))
        if leak:
            problems.append("G21: %s: %s" % (name, "; ".join(leak)))
        # G22 (records) per arm
        fr = base / name / "flow-records"
        r = subprocess.run([str(fr), "check", "--recursive", "--root", ".", "rec"], cwd=str(root), capture_output=True, text=True)
        victim = root / "data" / "dispensing.csv"
        orig = victim.read_bytes()
        victim.write_bytes(orig[:-2] + (b"9\n" if orig[-2:-1] != b"9" else b"8\n"))
        r2 = subprocess.run([str(fr), "check", "--recursive", "--root", ".", "rec"], cwd=str(root), capture_output=True, text=True)
        victim.write_bytes(orig)
        report.append("G22 %s: flow-records check %s on the recorded steps; a changed byte of dispensing.csv: exit %d" % (name, "clean" if r.returncode == 0 else "NOT CLEAN", r2.returncode))
        if r.returncode != 0:
            problems.append("G22: %s: flow-records check is not clean: %s" % (name, r.stdout[:200]))
        if r2.returncode == 0:
            problems.append("G22: %s: a changed byte of a recorded output was not detected" % name)
    t, t2 = base / ("T_%d" % seeds[0]) / "root", base / ("T2_%d" % seeds[0]) / "root"
    if t.exists() and t2.exists():
        same_data = all((t / "data" / f).read_bytes() == (t2 / "data" / f).read_bytes() for f in cl.OUTS)
        same_dec = tree_digest(t / "decisions") == tree_digest(t2 / "decisions")
        same_rec = tree_digest(t / "rec") == tree_digest(t2 / "rec")
        report.append("G22 two independent runs of arm T, seed %d: the final tables %s, the decisions %s, the records %s" % (seeds[0], "equal" if same_data else "DIFFER", "equal" if same_dec else "DIFFER", "equal" if same_rec else "DIFFER"))
        if not (same_data and same_dec and same_rec):
            problems.append("G22: two runs of arm T differ (tables %s, decisions %s, records %s)" % (same_data, same_dec, same_rec))
    # ---- G23 ----
    for s in seeds:
        dd = base / ("D_%d" % s) / "data"
        def same(arm, f):
            return (base / ("%s_%d" % (arm, s)) / "root" / "data" / f).read_bytes() == (dd / f).read_bytes()
        bad = []
        if not same("B", "dispensing.csv") or not same("B", "truth/demand.csv"):
            bad.append("arm B's stock differs from D's")
        if not same("C", "truth/demand.csv") or not same("T", "truth/demand.csv"):
            bad.append("the demand differs between arms")
        for arm in ("C", "B", "T"):
            a_ = table(str(base / ("%s_%d" % (arm, s)) / "root" / "data" / "dispensing.csv"))
            d_ = table(str(dd / "dispensing.csv"))
            if any(x != y for x, y in zip(a_, d_) if int(x["week"]) < first):
                bad.append("arm %s differs from D before week %d" % (arm, first))
            ra, rd_ = table(str(base / ("%s_%d" % (arm, s)) / "root" / "data" / "refills.csv")), table(str(dd / "refills.csv"))
            if [r for r in ra if int(r["due_week"]) <= first] != [r for r in rd_ if int(r["due_week"]) <= first]:
                bad.append("arm %s differs from D in the refills due up to week %d" % (arm, first))
        for arm, want_orders in (("C", True), ("B", False), ("T", True)):
            for w in range(first, last + 1):
                doc = json.loads((base / ("%s_%d" % (arm, s)) / "root" / "decisions" / ("week-%d.json" % w)).read_text())
                if bool(doc.get("orders")) != want_orders or (arm != "C" and not doc.get("outreach")):
                    bad.append("arm %s week %d: the decisions file has the wrong parts" % (arm, w))
                    break
        report.append("G23 seed %d: %s" % (s, "arms are what they claim (B's stock and all demand equal D's; no difference before week %d; the decisions files have the right parts)" % first if not bad else "; ".join(bad)))
        if bad:
            problems.append("G23: seed %d: %s" % (s, "; ".join(bad)))
    # ---- outcomes and claims ----
    for s in seeds:
        for a in ("D", "C", "B", "T"):
            o = res[(s, a)]
            report.append("seed %d arm %s: orders %d units (weeks %d-%d), stockout cells %d, units short %d, written off %d, events %d, lapses %d (weeks %d-%d)" % (
                s, a, o["orders_units"], first, last, o["stockout_cells"], o["units_short"], o["written_off"], o["events"], o["lapses"], first + 1, end))
    claims = (("1", "C orders at most %.2f of D's units" % CLAIM1, lambda c, d, b, t: c["orders_units"] <= CLAIM1 * d["orders_units"], lambda c, d, b, t: c["orders_units"] / d["orders_units"]),
              ("2", "C has at least %.1f times D's stockout cells" % CLAIM2, lambda c, d, b, t: c["stockout_cells"] >= CLAIM2 * d["stockout_cells"], lambda c, d, b, t: c["stockout_cells"] / d["stockout_cells"]),
              ("3", "C has at least %.2f times D's lapses" % CLAIM3, lambda c, d, b, t: c["lapses"] >= CLAIM3 * d["lapses"], lambda c, d, b, t: c["lapses"] / d["lapses"]),
              ("4", "B has at most %.2f of D's lapses" % CLAIM4, lambda c, d, b, t: b["lapses"] <= CLAIM4 * d["lapses"], lambda c, d, b, t: b["lapses"] / d["lapses"]))
    for cid, text, test, ratio in claims:
        parts, ok = [], True
        for s in seeds:
            c, d, b, t = res[(s, "C")], res[(s, "D")], res[(s, "B")], res[(s, "T")]
            r_ = ratio(c, d, b, t)
            parts.append("seed %d: %.3f" % (s, r_))
            ok = ok and test(c, d, b, t)
        report.append("CLAIM %s (%s): %s -> %s" % (cid, text, "; ".join(parts), "holds on every seed" if ok else "FAILS"))
        if not ok:
            problems.append("CLAIM %s: %s does not hold on every seed (%s)" % (cid, text, "; ".join(parts)))
    for s in seeds:
        d, t = res[(s, "D")], res[(s, "T")]
        report.append("T (reported, not claimed), seed %d: lapses %d against D's %d (%+.1f%%), stockout cells %d against %d, orders %d against %d" % (
            s, t["lapses"], d["lapses"], 100.0 * (t["lapses"] - d["lapses"]) / d["lapses"], t["stockout_cells"], d["stockout_cells"], t["orders_units"], d["orders_units"]))
    for ln in report:
        print(ln)
    for p in problems:
        print(p)
    if problems:
        return 1
    print("experiment: ok (G21 to G23 and the four claims hold)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
