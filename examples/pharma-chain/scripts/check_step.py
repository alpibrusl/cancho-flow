#!/usr/bin/env python3
"""Gates G18 to G20 of docs/use-cases.md (section 7a, U7a, committed before the stepping twin was written): the twin as a stepping environment.

    python3 scripts/check_step.py              # the checks, on the committed twin
    python3 scripts/check_step.py --mutants    # each deliberate fault in a copy of the twin must be caught

G18  the stepped twin writes every file of the batch twin byte for byte, with no decisions: two seeds, two sizes, and every table group
G19  a bad decisions file is refused with a rule tag and nothing is written; a fuzz of 300 never reaches a traceback; the decisions have only the effects they name (nothing before their week)
G20  the same decisions give the same bytes, and the order of the entries of a file does not matter
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
sys.path.insert(0, str(HERE))
from twinlib.prng import SplitMix64  # noqa: E402  (the gate's own random numbers: the fuzz)

FULL = "core,dispensing,refills,delivery,coupled"
SUBSETS = ("core", "core,dispensing", "core,dispensing,refills", "core,delivery", "core,dispensing,delivery,coupled")


def run(tree, args, cwd, timeout=900):
    return subprocess.run([sys.executable, str(tree / "twin.py")] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def gen(tree, work, seed, size, tables, out, extra=()):
    r = run(tree, ["generate", "--world", "world.json", "--seed", str(seed), "--size", size, "--tables", tables, "--out", out] + list(extra), work)
    if r.returncode != 0:
        return None, r
    root = pathlib.Path(work) / out
    return {str(f.relative_to(root)): f.read_bytes() for f in sorted(root.rglob("*")) if f.is_file()}, r


def table(b):
    lines = b.decode().splitlines()
    head = lines[0].split(",")
    return [dict(zip(head, ln.split(","))) for ln in lines[1:]]


def tag_of(r):
    err = r.stderr.strip().splitlines()
    if len(err) == 1:
        try:
            return json.loads(err[0])["error"]["rule"]
        except (ValueError, KeyError, TypeError):
            return None
    return None


def check(tree, quick=False):
    """Returns the problems; `quick` (the mutants) runs the equality on the small size and seed 20261112 only."""
    problems = []
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td) / "w"
        work.mkdir()
        shutil.copy(tree / "world.json", work / "world.json")
        # ---- G18 ----
        cfgs = [(20261112, "small", FULL)] if quick else [(s, z, FULL) for s in (20261112, 1) for z in ("small", "large")] + [(20261112, "small", t) for t in SUBSETS]
        for seed, size, tables in cfgs:
            a, ra = gen(tree, work, seed, size, tables, "b_%d_%s_%s" % (seed, size, tables.replace(",", "_")))
            b, rb = gen(tree, work, seed, size, tables, "s_%d_%s_%s" % (seed, size, tables.replace(",", "_")), ["--engine", "step"])
            if a is None or b is None:
                problems.append("G18: the twin did not run for seed %d, %s, %s: %s" % (seed, size, tables, (ra.stderr if a is None else rb.stderr).strip()[-120:]))
                continue
            if set(a) != set(b):
                problems.append("G18: seed %d, %s, %s: the stepped twin writes other files than the batch twin: %s" % (seed, size, tables, sorted(set(a) ^ set(b))))
            for f in sorted(set(a) & set(b)):
                if a[f] != b[f]:
                    problems.append("G18: seed %d, %s, %s: %s differs between the stepped and the batch twin" % (seed, size, tables, f))
        if quick:
            # the mutants are also judged by the effects of the decisions, on the small size
            pass
        # ---- the decisions of the checks: built from the small world ----
        base, rb0 = gen(tree, work, 20261112, "small", FULL, "dec_base")
        if base is None:
            return problems + ["G19: the small world did not run: %s" % rb0.stderr.strip()[-120:]]
        items = {r["item"]: r for r in table(base["items.csv"])}
        pharm = {r["pharmacy"]: r for r in table(base["pharmacies.csv"])}
        trucks = [r["truck"] for r in table(base["trucks.csv"])]
        refills = table(base["refills.csv"])
        by_week = {}
        for r in refills:
            by_week.setdefault(int(r["due_week"]), []).append(r)
        disp = table(base["dispensing.csv"])

        def write_dir(name, files):
            d = work / name
            d.mkdir()
            for fname, doc in files.items():
                (d / fname).write_bytes(doc if isinstance(doc, bytes) else json.dumps(doc).encode())
            return name

        def stepped(dname, out, tables=FULL):
            return gen(tree, work, 20261112, "small", tables, out, ["--decisions", dname])

        # ---- G19: the effects ----
        W0 = 50
        zero_orders = [{"pharmacy": r["pharmacy"], "item": r["item"], "units": 0} for r in disp if int(r["week"]) == W0]
        d1 = write_dir("d_zero", {"week-%d.json" % W0: {"week": W0, "orders": zero_orders}})
        z, rz = stepped(d1, "o_zero")
        if z is None:
            problems.append("G19: a decisions file of zero orders was refused: %s" % rz.stderr.strip()[-120:])
        else:
            rb_, rz_ = table(base["dispensing.csv"]), table(z["dispensing.csv"])
            before = [i for i, (x, y) in enumerate(zip(rb_, rz_)) if int(x["week"]) < W0 and x != y]
            at = [x for x, y in zip(rb_, rz_) if int(x["week"]) == W0 and (y["ordered"] != "0" or any(x[k] != y[k] for k in x if k != "ordered"))]
            after = [1 for x, y in zip(rb_, rz_) if int(x["week"]) > W0 and x != y]
            if before:
                problems.append("G19: zero orders at week %d change %d rows of dispensing.csv before it (the first is row %d)" % (W0, len(before), before[0]))
            if at:
                problems.append("G19: zero orders at week %d: the row of week %d changes more than its `ordered` column or does not order zero" % (W0, W0))
            if not after:
                problems.append("G19: zero orders at week %d change no row after it: the decision has no effect" % W0)
            if base["truth/demand.csv"] != z["truth/demand.csv"]:
                problems.append("G19: zero orders change truth/demand.csv: the demand does not depend on the stock in this twin")
        W1 = 20
        acts = []
        for w in range(W1, W1 + 31):
            acts.append((w, [{"patient": r["patient"], "item": r["item"], "action": "call"} for r in by_week.get(w + 1, [])]))
        d2 = write_dir("d_call", {"week-%d.json" % w: {"week": w, "outreach": a_} for w, a_ in acts})
        c, rc = stepped(d2, "o_call")
        if c is None:
            problems.append("G19: a decisions file with outreach was refused: %s" % rc.stderr.strip()[-120:])
        else:
            r0, r1 = table(base["refills.csv"]), table(c["refills.csv"])
            first = {(r["patient"], r["item"], r["due_week"]): r for r in r0}
            pre = [k for k, r in first.items() if int(k[2]) <= W1 and any(x for x in [r] if r not in r1)]
            if pre:
                problems.append("G19: calls from week %d change %d refill rows due before week %d" % (W1, len(pre), W1 + 1))
            l0 = sum(1 for r in r0 if r["filled"] == "0")
            l1 = sum(1 for r in r1 if r["filled"] == "0")
            if not l1 < l0:
                problems.append("G19: a call for every event of weeks %d to %d does not lower the lapses (%d against %d)" % (W1 + 1, W1 + 31, l1, l0))
            if base["truth/demand.csv"] != c["truth/demand.csv"]:
                problems.append("G19: outreach changes truth/demand.csv")
        W2 = 20
        d3 = write_dir("d_charge", {"week-%d.json" % W2: {"week": W2, "charge": [{"truck": t, "day": d, "kwh": 0} for t in trucks for d in range(7 * (W2 + 1), 7 * (W2 + 1) + 7)]}})
        ch, rch = stepped(d3, "o_charge")
        if ch is None:
            problems.append("G19: a decisions file with charges was refused: %s" % rch.stderr.strip()[-120:])
        else:
            short = table(ch.get("truth/short.csv", b"route,seq\n"))
            if not short:
                problems.append("G19: a charge of zero for every truck makes no route end short")
            days = {r["route"]: int(r["day"]) for r in table(ch["routes.csv"])}
            if any(not 7 * (W2 + 1) <= days[s["route"]] <= 7 * (W2 + 1) + 6 for s in short):
                problems.append("G19: a route ends short outside the days of the charge")
            if base["routes.csv"] != ch["routes.csv"] or base["truth/demand.csv"] != ch["truth/demand.csv"]:
                problems.append("G19: charges change routes.csv or the demand")
        # ---- G19: the refusals ----
        some_item = next(iter(items))
        some_ph = next(iter(pharmacy for pharmacy in pharm))
        pack = int(items[some_item]["pack_size"])
        cap = int(pharm[some_ph]["cold_capacity_units"] if items[some_item]["cold_chain"] == "1" else pharm[some_ph]["shelf_capacity_units"])
        ev = by_week[5][0]
        wk = 5
        cases = [
            ("unknown-pharmacy", "twin.decision-unknown-pharmacy", {"week-3.json": {"week": 3, "orders": [{"pharmacy": "P999", "item": some_item, "units": 0}]}}),
            ("unknown-item", "twin.decision-unknown-item", {"week-3.json": {"week": 3, "orders": [{"pharmacy": some_ph, "item": "I9999", "units": 0}]}}),
            ("negative", "twin.decision-number", {"week-3.json": {"week": 3, "orders": [{"pharmacy": some_ph, "item": some_item, "units": -pack}]}}),
            ("fractional", "twin.decision-number", {"week-3.json": {"week": 3, "orders": [{"pharmacy": some_ph, "item": some_item, "units": 1.5}]}}),
            ("not-a-pack", "twin.decision-pack", {"week-3.json": {"week": 3, "orders": [{"pharmacy": some_ph, "item": some_item, "units": pack + 1}]}}),
            ("over-capacity", "twin.decision-over-capacity", {"week-3.json": {"week": 3, "orders": [{"pharmacy": some_ph, "item": some_item, "units": (cap // pack + 1) * pack}]}}),
            ("duplicate", "twin.decision-duplicate", {"week-3.json": {"week": 3, "orders": [{"pharmacy": some_ph, "item": some_item, "units": 0}, {"pharmacy": some_ph, "item": some_item, "units": 0}]}}),
            ("week-mismatch", "twin.decision-week", {"week-3.json": {"week": 4}}),
            ("week-out-of-range", "twin.decision-week", {"week-9999.json": {"week": 9999}}),
            ("unknown-patient", "twin.decision-unknown-patient", {"week-3.json": {"week": 3, "outreach": [{"patient": "N999999", "item": some_item, "action": "call"}]}}),
            ("unknown-action", "twin.decision-unknown-action", {"week-%d.json" % (wk - 1): {"week": wk - 1, "outreach": [{"patient": ev["patient"], "item": ev["item"], "action": "hug"}]}}),
            ("unknown-truck", "twin.decision-unknown-truck", {"week-3.json": {"week": 3, "charge": [{"truck": "T99", "day": 28, "kwh": 1}]}}),
            ("wrong-day", "twin.decision-day", {"week-3.json": {"week": 3, "charge": [{"truck": trucks[0], "day": 3, "kwh": 1}]}}),
            ("not-due", "twin.decision-not-due", {"week-%d.json" % (wk - 1): {"week": wk - 1, "outreach": [{"patient": r["patient"], "item": r["item"], "action": "call"} for r in by_week[wk + 1][:1]]}}),
            ("too-large", "twin.decision-too-large", {"week-3.json": b" " * 1_048_577}),
            ("not-json", "twin.decision-json", {"week-3.json": b"{not json"}),
            ("bad-file-name", "twin.decision-file", {"orders.json": {"week": 3}}),
        ]
        for name, rule, files in cases:
            dn = write_dir("r_" + name, files)
            r = run(tree, ["generate", "--world", "world.json", "--seed", "20261112", "--size", "small", "--tables", FULL, "--out", "ro_" + name, "--decisions", dn], work)
            if r.returncode != 2 or tag_of(r) != rule or r.stdout or (work / ("ro_" + name)).exists():
                problems.append("G19: refusal %s: exit %s, rule %s, wanted exit 2 and %s and nothing written" % (name, r.returncode, tag_of(r), rule))
        r = run(tree, ["generate", "--world", "world.json", "--seed", "20261112", "--size", "small", "--tables", "core", "--out", "ro_tables", "--decisions", write_dir("r_tables", {"week-3.json": {"week": 3, "orders": [{"pharmacy": some_ph, "item": some_item, "units": 0}]}})], work)
        if r.returncode != 2 or tag_of(r) != "twin.decision-tables" or (work / "ro_tables").exists():
            problems.append("G19: orders with no dispensing table: exit %s, rule %s, wanted twin.decision-tables" % (r.returncode, tag_of(r)))
        if not quick:
            rng = SplitMix64(20261112)
            valid = {"week": 3, "orders": [{"pharmacy": some_ph, "item": some_item, "units": pack}], "outreach": [], "charge": [{"truck": trucks[0], "day": 28, "kwh": 5}]}
            junk = [None, True, 7, "x", [], {}, -1, 1.5, "P001", 10 ** 30, {"a": 1}, [1], "I0001", "call", ""]


            def pick():
                return json.loads(json.dumps(junk[rng.below(len(junk))]))  # a copy: a draw never shares an object with another
            for i in range(300):
                doc = json.loads(json.dumps(valid))
                for _ in range(1 + rng.below(3)):
                    where = rng.below(6)
                    try:
                        if where == 0:
                            doc["week"] = pick()
                        elif where == 1:
                            doc["orders"][0][["pharmacy", "item", "units"][rng.below(3)]] = pick()
                        elif where == 2:
                            doc["charge"][0][["truck", "day", "kwh"][rng.below(3)]] = pick()
                        elif where == 3:
                            doc[["orders", "outreach", "charge", "extra"][rng.below(4)]] = pick()
                        elif where == 4:
                            doc["outreach"] = [{"patient": pick(), "item": pick(), "action": pick()}]
                        else:
                            doc = pick()
                    except (KeyError, TypeError, IndexError):
                        pass  # the earlier mutation of this draw left nothing to mutate here: the draw is what it is
                dn = write_dir("fz%d" % i, {"week-3.json": doc})
                r = run(tree, ["generate", "--world", "world.json", "--seed", "20261112", "--size", "small", "--tables", FULL, "--out", "fzo%d" % i, "--decisions", dn, "--through", "6"], work)
                if r.returncode not in (0, 2) or "Traceback" in r.stderr or (r.returncode == 2 and not r.stderr.strip().startswith("{")):
                    problems.append("G19: fuzz %d: %r gave exit %d and %r" % (i, doc, r.returncode, r.stderr.strip()[-100:]))
                    break
                shutil.rmtree(work / dn, ignore_errors=True)
                shutil.rmtree(work / ("fzo%d" % i), ignore_errors=True)
        # ---- G20 ----
        z2, _ = stepped(d1, "o_zero2")
        if z is not None and (z2 is None or any(z[f] != z2[f] for f in z)):
            problems.append("G20: two runs of the same decisions differ")
        rev = write_dir("d_rev", {"week-%d.json" % W0: {"week": W0, "orders": list(reversed(zero_orders))}})
        z3, _ = stepped(rev, "o_zero3")
        if z is not None and (z3 is None or any(z[f] != z3[f] for f in z)):
            problems.append("G20: the order of the entries of a decisions file changes the output")
    return problems


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("refill-uniform-index-not-advanced", "twinlib/step.py", _x('                st["j"] +', '= 1\n'), '                st["j"] += 0\n', "G18"),
    ("refill-numbers-misaligned", "twinlib/step.py", _x('            pos +', '= k\n'), '            pos += k + 1\n', "G18"),
    ("refills-in-the-wrong-order", "twinlib/step.py", _x('            rrows.sort(key=lambda r: (order_idx[r[0]], r[1], ', 'r[3]))\n'), '            rrows.sort(key=lambda r: (order_idx[r[0]], r[3], r[1]))\n', "G18"),
    ("batch-numbers-ignored", "twinlib/step.py", _x('                if st["j"] < ', 'len(st["u"]):'), '                if False:', "G18"),
    ("the-week-has-six-days", "twinlib/step.py", _x('            for d in range(7 * W, 7 * W + ', '7):\n'), '            for d in range(7 * W, 7 * W + 6):\n', "G18"),
    ("coupling-not-passed-to-the-stock", "twinlib/step.py", _x('    flags = {"late": dw.late_weeks, "warm": dw.warm_weeks} if ', 'coupled else None'), '    flags = None if True else None', "G18"),
    ("stockout-window-off-by-one", "twinlib/step.py", _x('for x in range(max(0, W - window + 1), W ', '+ 1)))'), 'for x in range(max(0, W - window + 1), W)))', "G18"),
    ("orders-applied-a-week-late", "twinlib/step.py", _x('sim.step(W, dec[W]["orders"] if W in dec and dec[W]["orders"] else None)', ''), 'sim.step(W, dec[W - 1]["orders"] if (W - 1) in dec and dec[W - 1]["orders"] else None)', "G19"),
    ("orders-ignored", "twinlib/core.py", _x('            if orders is not None and (phid, itid) in orders:\n                ordered = ', 'orders[(phid, itid)]'), '            if False:\n                ordered = orders[(phid, itid)]', "G19"),
    ("outreach-has-no-effect", "twinlib/step.py", _x('                if key in acts:\n                    chance = ', 'chance * (1_000_000 - uplift[acts[key]]) // 1_000_000'), '                if False:\n                    chance = chance', "G19"),
    ("charges-ignored", "twinlib/delivery.py", _x('            if available is not None and tr[0] in available and energy > ', 'available[tr[0]] * 1000:'), '            if False and energy > available[tr[0]] * 1000:', "G19"),
    ("decisions-of-the-same-week-for-outreach", "twinlib/step.py", _x('            acts = dec[W - 1]["outreach"] if (W - 1) in dec ', 'else {}'), '            acts = dec[W]["outreach"] if W in dec else {}', "G19"),
    ("entry-order-matters", "twinlib/decisions.py", _x('            res["orders"][(ph, it)] = ', 'u'), '            res["orders"][(ph, it)] = u + len(res["orders"]) * 0 + (1 if (ph, it) == next(iter(res["orders"]), None) else 0)', "G20"),
]


def mutants():
    base = check(HERE, quick=True)
    if base:
        print("control FAILED (the unmodified twin is refused):")
        for p in base:
            print("  " + p)
        return 1
    print("control passes (quick)")
    survived = 0
    for name, rel, old, new, want in MUTANTS:
        with tempfile.TemporaryDirectory() as td:
            tree = pathlib.Path(td) / "t"
            shutil.copytree(HERE, tree, ignore=shutil.ignore_patterns("__pycache__", "scripts", "*.pyc"))
            f = tree / rel
            text = f.read_text()
            if text.count(old) != 1:
                print("mutant %-44s CANNOT BE APPLIED: the text occurs %d times in %s" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            found = check(tree, quick=True)
            hit = [p for p in found if p.startswith(want)]
            if hit:
                print("killed   %-44s by %s" % (name, hit[0][:100]))
            else:
                survived += 1
                print("SURVIVED %-44s wanted a %s problem; found %s" % (name, want, [p[:60] for p in found] or "none"))
    print("%d mutants, %d survived" % (len(MUTANTS), survived))
    return 1 if survived else 0


def main():
    if "--mutants" in sys.argv:
        return mutants()
    problems = check(HERE)
    for p in problems:
        print("check_step: " + p)
    if problems:
        return 1
    print("check_step: ok (G18: stepped = batch in 9 configurations; G19: refusals, fuzz, effects; G20: determinism)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
