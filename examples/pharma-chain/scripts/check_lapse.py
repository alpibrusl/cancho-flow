#!/usr/bin/env python3
"""G24 and G25 of U8 (docs/use-cases.md section 7a), and the mutants of the builder's lapse term.

    python3 scripts/check_lapse.py DATA_DIR [--mutants [name ...]]

DATA_DIR is the large twin's tables (the data/ of arm D of the experiment, with refills.csv through the last week). The fixture is week 95: the forecast of each cell is the units of the week before (any forecast will do: the gates
are about the target), the stock is the week before's. G25: with a lapse cost of 0 the builder with `--lapse` writes the same `.sol` byte for byte and the same `.json` less its `lapse` member as without the flag. G24: for every plan
the judge's own code (`recompute`, with the inverse of the normal distribution found by bisection on erf) gives the events a week, the lapse cost per unit, the quantile and the target; and the cap is exercised with a huge cost.
Standard library only.
"""
import csv
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEK = 95

MUTANTS = {
    "sign-flipped": ("z0 + (inv(r1) - inv(r0)), cap)", "z0 - (inv(r1) - inv(r0)), cap)"),
    "window-1": ("li = ev * window * (ppm", "li = ev * 1 * (ppm"),
    "events-include-the-week": ("<= week - 1:", "<= week:"),
    "events-over-4": ("return {k: v / history for", "return {k: v / 4 for"),
    "not-per-unit": ("* cost / max(fi, 1.0)", "* cost"),
    "absolute-not-increment": ("z0 + (inv(r1) - inv(r0)), cap)", "inv(r1), cap)"),
    "cap-removed": ("min(z0 + (inv(r1) - inv(r0)), cap)", "z0 + (inv(r1) - inv(r0))"),
}


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fixture(data, tmp):
    disp = read(os.path.join(data, "dispensing.csv"))
    prev = {(r["pharmacy"], r["item"]): r for r in disp if int(r["week"]) == WEEK - 1}
    keys = sorted(prev)
    with open(os.path.join(tmp, "test.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["pharmacy", "item", "week"])
        for p, i in keys:
            w.writerow([p, i, WEEK])
    rows = [[float(prev[k]["units"])] for k in keys]
    with open(os.path.join(tmp, "pred.json"), "w") as f:
        json.dump({"data": {"rows": rows}}, f)
    shutil.copy(os.path.join(HERE, "costs.json"), os.path.join(tmp, "costs.json"))
    return keys


def build(builder, data, tmp, name, lapse_path, only="P001"):
    out = os.path.join(tmp, name)
    if os.path.exists(out):
        shutil.rmtree(out)
    cmd = [sys.executable, builder, "--only", "%d:%s" % (WEEK, only)] + (["--lapse", lapse_path] if lapse_path else []) + [data, os.path.join(tmp, "test.csv"), os.path.join(tmp, "pred.json"), os.path.join(tmp, "costs.json"), out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-200:]
    base = os.path.join(out, "models", "W%d_%s" % (WEEK, only))
    return (open(base + ".sol", "rb").read(), json.load(open(base + ".json"))), ""


def cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def inv(p):
    lo, hi = -12.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def refill_counts(data):
    """The events of refills.csv by (pharmacy, item, due week)."""
    c = {}
    for r in read(os.path.join(data, "refills.csv")):
        k = (r["pharmacy"], r["item"], int(r["due_week"]))
        c[k] = c.get(k, 0) + 1
    return c


def recompute(d, data, costs, lapse, counts=None):
    """The judge's own computation of ev, l, z and target for one model's data d (its week, pharmacy and items), from the tables."""
    week, ph = d["week"], d["pharmacy"]
    hist = lapse["history_weeks"]["value"]
    counts = counts if counts is not None else refill_counts(data)
    cnt = {}
    for item in d["items"]:
        n = sum(counts.get((ph, item, w), 0) for w in range(week - hist, week))
        if n:
            cnt[item] = n
    over = costs["waste_per_unit"]["value"] + costs["holding_per_unit"]["value"]
    z0 = costs["z_milli"]["value"] / 1000.0
    out = []
    for k, item in enumerate(d["items"]):
        f, pen = d["f"][k], d["pen"][k]
        ev = cnt.get(item, 0) / float(hist)
        l = ev * lapse["window_weeks"]["value"] * (lapse["ppm"]["value"] / 1e6) * lapse["cost"]["value"] / max(f, 1.0)
        z = min(z0 + (inv((pen + l) / (pen + l + over)) - inv(pen / (pen + over))), lapse["z_cap"]["value"])
        out.append((ev, l, z, f + z * math.sqrt(max(f, 1.0))))
    return out


def close(a, b, tol):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def check_plans(models_dir, data, costs, lapse):
    """G24 on every plan of an arm: `models_dir` holds W*_P*.json, `data` the arm's final tables. Returns (number of plans, problems)."""
    counts = refill_counts(data)
    n, problems = 0, []
    for jf in sorted(glob.glob(os.path.join(models_dir, "W*_P*.json"))):
        if jf.endswith(".plan.json") or jf.endswith(".verify.json"):
            continue
        d = json.load(open(jf))
        n += 1
        m = d.get("lapse")
        if m is None:
            problems.append("G24/G26: %s has no lapse member" % os.path.basename(jf))
            continue
        for k, (ev, l, z, tg) in enumerate(recompute(d, data, costs, lapse, counts)):
            if not (close(m["ev"][k], ev, 1e-9) and close(m["l"][k], l, 1e-9) and close(m["z"][k], z, 1e-9) and close(d["target"][k], tg, 1e-9)):
                problems.append("G24: %s item %s: the builder has target %.6g, the judge %.6g" % (os.path.basename(jf), d["items"][k], d["target"][k], tg))
                break
    return n, problems


def gates(builder, data, tmp, quiet=False):
    """Returns the list of problems (empty: G24 and G25 hold) of the builder at `builder`."""
    problems = []
    costs = json.load(open(os.path.join(tmp, "costs.json")))
    lapse = json.load(open(os.path.join(HERE, "lapse.json")))
    zero = json.loads(json.dumps(lapse))
    zero["cost"]["value"] = 0
    huge = json.loads(json.dumps(lapse))
    huge["cost"]["value"] = 10 ** 9
    for name, doc in (("lapse", lapse), ("zero", zero), ("huge", huge)):
        json.dump(doc, open(os.path.join(tmp, name + ".json"), "w"))
    base, e0 = build(os.path.join(HERE, "build_models.py"), data, tmp, "plain", None)   # the flag-free output is always the committed builder's
    z, e1 = build(builder, data, tmp, "zero", os.path.join(tmp, "zero.json"))
    if base[0] is None or z[0] is None:
        return ["G25: a builder did not run: %s %s" % (e0, e1)]
    sol0, d0 = base
    sol1, d1 = z
    lap = d1.pop("lapse", None)
    if sol0 != sol1 or d0 != d1 or lap is None:
        problems.append("G25: with a lapse cost of 0 the plan is not the plan without the lapse term")
    for name in ("lapse", "huge"):
        res, e = build(builder, data, tmp, name, os.path.join(tmp, name + ".json"))
        if res[0] is None:
            problems.append("G24: the builder did not run for %s: %s" % (name, e))
            continue
        sol, d = res
        lp = {"lapse": lapse, "huge": huge}[name]
        rc = recompute(d, data, costs, lp)
        for k, (ev, l, z, tg) in enumerate(rc):
            m = d["lapse"]
            if not (close(m["ev"][k], ev, 1e-9) and close(m["l"][k], l, 1e-9) and close(m["z"][k], z, 1e-9) and close(d["target"][k], tg, 1e-9)):
                problems.append("G24: %s: item %s: the builder has ev %.6g l %.6g z %.6g target %.6g, the judge %.6g %.6g %.6g %.6g" % (name, d["items"][k], m["ev"][k], m["l"][k], m["z"][k], d["target"][k], ev, l, z, tg))
                break
        if name == "lapse":
            idle = [k for k, (ev, _, _, _) in enumerate(rc) if ev == 0]
            z0 = costs["z_milli"]["value"] / 1000.0
            if not idle or any(d["target"][k] != d["f"][k] + z0 * max(d["f"][k], 1.0) ** 0.5 for k in idle):
                problems.append("G24: an item with no event does not keep the old target (%d such items)" % len(idle))
            if not any(ev > 0 for ev, _, _, _ in rc):
                problems.append("G24: the fixture has no item with an event: the term is not exercised")
        else:
            if not any(z >= lp["z_cap"]["value"] - 1e-12 for _, _, z, _ in rc):
                problems.append("G24: the fixture does not bind the cap")
    return problems


def main(argv):
    if not argv or argv[0].startswith("--"):
        sys.stderr.write("check_lapse.py DATA_DIR [--mutants [name ...]]\n")
        return 2
    data = argv[0]
    tmp = tempfile.mkdtemp(prefix="check_lapse_")
    fixture(data, tmp)
    builder = os.path.join(HERE, "build_models.py")
    problems = gates(builder, data, tmp)
    print("G24, G25 on the committed builder: %s" % ("hold" if not problems else "FAIL: " + "; ".join(problems)))
    if problems:
        return 1
    if "--mutants" in argv:
        names = [a for a in argv[argv.index("--mutants") + 1:]] or list(MUTANTS)
        survived = 0
        text = open(builder).read()
        for n in names:
            old, new = MUTANTS[n]
            if text.count(old) != 1:
                print("%s: its text occurs %d times in build_models.py" % (n, text.count(old)))
                return 2
            mdir = os.path.join(tmp, "mut_" + n)
            os.makedirs(mdir)
            mb = os.path.join(mdir, "build_models.py")
            open(mb, "w").write(text.replace(old, new))
            mp = gates(mb, data, tmp)
            print("%s: %s" % (n, "killed by " + mp[0][:110] if mp else "SURVIVED"))
            survived += 0 if mp else 1
        print("check_lapse: %d of %d mutants killed" % (len(names) - survived, len(names)))
        return 1 if survived else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
