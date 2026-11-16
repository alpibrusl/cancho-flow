#!/usr/bin/env python3
"""G30 and G31 of U10 (docs/use-cases.md section 7a, committed before the space limits were built), and the mutants of the twin's limit.

    python3 scripts/check_cap.py [--mutants [name ...]]

G30  in the enforced world (`enforce_capacity` 1) the batch twin's dispensing.csv has, for every pharmacy, class and week, orders no larger than the room (recomputed here from the stock at the end of the same week); the
     orders of the twin's own policy are recomputed here from the sales alone (the cover, the trailing weeks, whole packs, then the proportional cut) and equal the twin's, cell by cell; the stepped twin writes the same bytes
     as the batch twin in the enforced configurations (two seeds, two sizes, and the table groups), and the decisions of a week change nothing before it.
G31  a decisions file whose orders of a class exceed the room is refused (twin.decision-over-room, exit 2, nothing written), one at exactly the room is accepted; the rule is not applied when the flag is 0.
Standard library only; the independent code of the policy is `recompute_policy` and `room_violations`, which the experiment's judge also uses.
"""
import csv
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
FULL = "core,dispensing,refills,delivery,coupled"
SUBSETS = ("core,dispensing", "core,dispensing,refills", "core,dispensing,delivery,coupled")
CORE_PY = "twinlib/core.py"

MUTANTS = {  # name: (file, old text (once), new text, the mode whose gates are run)
    "flag-ignored": (CORE_PY, "        if self.enforce:\n            self._limit(week, pend)", "        if False:\n            self._limit(week, pend)", 2),
    "no-cut": (CORE_PY, "            elif total > left:", "            elif False:", 1),
    "cut-rounded-up": (CORE_PY, "ordered = (default * left // total) // pack * pack", "ordered = -(-(default * left // total) // pack) * pack", 1),
    "cut-not-proportional": (CORE_PY, "ordered = (default * left // total) // pack * pack", "ordered = min(default, left) // pack * pack", 1),
    "room-ignores-the-stock": (CORE_PY, "room = max(0, cap - sum(it[6] for it in its))", "room = max(0, cap)", 2),
    "classes-pooled": (CORE_PY, "groups.setdefault((c[8], cold), []).append(item)", "groups.setdefault((c[8], 0), []).append(item)", 2),
    "over-room-accepted": (CORE_PY, "            if given > room:", "            if False:", 2),
    "tie-to-the-later-item": (CORE_PY, "                    return (-unmet, itid, k)", "                    return (-unmet, -int(itid[1:]), k)", 2),
    "smallest-unmet-first": (CORE_PY, "                    return (-unmet, itid, k)", "                    return (unmet, itid, k)", 2),
    "a-misfit-stops-the-allocation": (CORE_PY, "                    if pack > left:\n                        continue", "                    if pack > left:\n                        break", 2),
    "a-pack-over-the-room": (CORE_PY, "                    if pack > left:\n                        continue", "                    if left <= 0:\n                        continue", 2),
    "packs-beyond-the-want": (CORE_PY, "                    if unmet > 0:\n                        heapq.heappush(heap, entry(unmet, itid, k))", "                    if True:\n                        heapq.heappush(heap, entry(unmet, itid, k))", 2),
    "mode-2-is-the-proportional-cut": (CORE_PY, "            if total > left and self.enforce == 2:", "            if False:", 2),
}


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def room_violations(data, world):
    """The (pharmacy, class, week) in which the orders exceed the room, recomputed from dispensing.csv, items.csv and pharmacies.csv. Returns (violations, binding pharmacy-class-weeks, groups)."""
    data = pathlib.Path(data)
    cold = {r["item"] for r in read(data / "items.csv") if r["cold_chain"] == "1"}
    cap = {r["pharmacy"]: (int(r["shelf_capacity_units"]), int(r["cold_capacity_units"])) for r in read(data / "pharmacies.csv")}
    stock, orders = {}, {}
    for r in read(data / "dispensing.csv"):
        k = (r["pharmacy"], 1 if r["item"] in cold else 0, int(r["week"]))
        stock[k] = stock.get(k, 0) + int(r["stock_end"])
        orders[k] = orders.get(k, 0) + int(r["ordered"])
    bad = [k for k in orders if orders[k] > max(0, cap[k[0]][k[1]] - stock[k])]
    binding = sum(1 for k in orders if orders[k] >= max(0, cap[k[0]][k[1]] - stock[k]) > 0)
    return bad, binding, len(orders)


def recompute_policy(data, world, mode=1, stats=None):
    """The orders of the twin's own policy recomputed from the sales alone (docs/use-cases.md U10): order up to `order_cover_ppm` times the mean of the last `trailing_weeks` weekly sales, rounded up to whole packs, and with
    the limit, cut by `mode` (1: in proportion, rounded down to whole packs; 2: whole packs, one at a time to the item with the largest unmet want, ties to the smaller identifier, a pack that does not fit passed over; a plain scan,
    not the twin's heap). Returns the cells whose recomputed order differs from the table's. `stats`, a dict, gets `cut_weeks` and `class_weeks` (the pharmacy-class-weeks from week 52 in which the wants exceed the room)."""
    data = pathlib.Path(data)
    p = {k: v["value"] for k, v in world["params"].items()}
    cover, trail = p["order_cover_ppm"], p["trailing_weeks"]
    items = {r["item"]: r for r in read(data / "items.csv")}
    cap = {r["pharmacy"]: (int(r["shelf_capacity_units"]), int(r["cold_capacity_units"])) for r in read(data / "pharmacies.csv")}
    rows = read(data / "dispensing.csv")
    hist, want, stock_end, ordered, order_of = {}, {}, {}, {}, []
    for r in rows:
        key = (r["pharmacy"], r["item"])
        hist.setdefault(key, []).append(int(r["units"]))
        recent = hist[key][-trail:]
        target = -(-cover * sum(recent) // (1_000_000 * len(recent)))
        pack = int(items[r["item"]]["pack_size"])
        w = max(0, target - int(r["stock_end"]))
        want[(r["pharmacy"], r["item"], int(r["week"]))] = -(-w // pack) * pack if w else 0
        stock_end[(r["pharmacy"], r["item"], int(r["week"]))] = int(r["stock_end"])
        ordered[(r["pharmacy"], r["item"], int(r["week"]))] = int(r["ordered"])
        order_of.append((r["pharmacy"], r["item"], int(r["week"]), pack, 1 if items[r["item"]]["cold_chain"] == "1" else 0))
    if stats is not None:
        stats["cut_weeks"] = stats["class_weeks"] = 0
    groups = {}
    for ph, it, wk, pack, cold in order_of:
        groups.setdefault((ph, cold, wk), []).append((ph, it, wk, pack))
    diff = []
    for (ph, cold, wk), cells in groups.items():
        room = max(0, cap[ph][cold] - sum(stock_end[(c[0], c[1], c[2])] for c in cells))
        total = sum(want[(c[0], c[1], c[2])] for c in cells)
        if stats is not None and wk >= 52:
            stats["class_weeks"] += 1
            stats["cut_weeks"] += int(total > room)
        alloc = None
        if mode == 2 and total > room:
            alloc, left = {c[1]: 0 for c in cells}, room
            pk = {c[1]: c[3] for c in cells}
            wn = {c[1]: want[(c[0], c[1], c[2])] for c in cells}
            while True:
                best = None
                for it in sorted(wn):  # ascending identifier: the first of equal unmet wants wins
                    unmet = wn[it] - alloc[it]
                    if unmet > 0 and pk[it] <= left and (best is None or unmet > best[0]):
                        best = (unmet, it)
                if best is None:
                    break
                alloc[best[1]] += pk[best[1]]
                left -= pk[best[1]]
        for c in cells:
            u = want[(c[0], c[1], c[2])]
            if mode == 1 and total > room:
                u = (u * room // total) // c[3] * c[3]
            elif mode == 2 and alloc is not None:
                u = alloc[c[1]]
            if u != ordered[(c[0], c[1], c[2])]:
                diff.append(c[:3])
    return diff


def plan_rooms(models_dir, data):
    """G32: for every plan of an arm, `room_cold` and `room_shelf` of the model equal the room recomputed from the arm's tables (the stock at the end of the week before, by class). Returns (plans, problems)."""
    import glob
    data = pathlib.Path(data)
    cold = {r["item"] for r in read(data / "items.csv") if r["cold_chain"] == "1"}
    cap = {r["pharmacy"]: (int(r["shelf_capacity_units"]), int(r["cold_capacity_units"])) for r in read(data / "pharmacies.csv")}
    stock = {}
    for r in read(data / "dispensing.csv"):
        k = (r["pharmacy"], 1 if r["item"] in cold else 0, int(r["week"]))
        stock[k] = stock.get(k, 0) + int(r["stock_end"])
    n, problems = 0, []
    for jf in sorted(glob.glob(os.path.join(models_dir, "W*_P*.json"))):
        if jf.endswith(".plan.json") or jf.endswith(".verify.json"):
            continue
        d = json.load(open(jf))
        n += 1
        for cls, key in ((1, "room_cold"), (0, "room_shelf")):
            want = max(0, cap[d["pharmacy"]][cls] - stock[(d["pharmacy"], cls, d["week"] - 1)])
            if d[key] != want:
                problems.append("G32: %s: %s is %d, the world's room is %d" % (os.path.basename(jf), key, d[key], want))
    return n, problems


def world_checks(data, world, ref_data):
    """The stop rule of U11 (N1 to N3) on the batch twin's tables of an enforced world (mode 2), weeks 52 and after; `ref_data` is the same seed without the limit. Returns (report lines, problems)."""
    data = pathlib.Path(data)
    rows = read(data / "dispensing.csv")
    late = [r for r in rows if int(r["week"]) >= 52]
    rate = sum(int(r["stockout"]) for r in late) / float(len(late))
    stats = {}
    diff = recompute_policy(data, world, 2, stats)
    share = stats["cut_weeks"] / float(stats["class_weeks"])

    def dead(rs):
        sold = {}
        for r in rs:
            if int(r["week"]) >= 78:
                k = (r["pharmacy"], r["item"])
                sold[k] = sold.get(k, 0) + int(r["units"])
        return sum(1 for v in sold.values() if v == 0) / float(len(sold))
    d_lim, d_ref = dead(rows), dead(read(pathlib.Path(ref_data) / "dispensing.csv"))
    rep = ["N1 stockout cell rate from week 52: %.3f (at most 0.15)" % rate,
           "N2 the wants exceed the room in %.3f of %d pharmacy-class-weeks from week 52 (at least 0.10)" % (share, stats["class_weeks"]),
           "N3 cells with no sale from week 78: %.3f, without the limit %.3f (at most that plus 0.02)" % (d_lim, d_ref)]
    probs = []
    if rate > 0.15:
        probs.append("N1: the stockout cell rate is %.3f" % rate)
    if share < 0.10:
        probs.append("N2: the cut applies in %.3f of the pharmacy-class-weeks" % share)
    if d_lim > d_ref + 0.02:
        probs.append("N3: %.3f of the cells have no sale from week 78 (without the limit %.3f)" % (d_lim, d_ref))
    return rep, probs, diff


def world_cap(tree, flag=1):
    w = json.loads((tree / "world.json").read_text())
    w["params"]["enforce_capacity"] = {"value": flag, "source": "choice", "note": "the space limits of the pharmacies bind their orders (U10)"}
    return w


def run(tree, args, cwd):
    return subprocess.run([sys.executable, str(tree / "twin.py")] + args, cwd=cwd, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)


def gen(tree, work, wname, seed, size, tables, out, extra=()):
    r = run(tree, ["generate", "--world", wname, "--seed", str(seed), "--size", size, "--tables", tables, "--out", out] + list(extra), work)
    return r


def snapshot(root):
    root = pathlib.Path(root)
    return {str(f.relative_to(root)): f.read_bytes() for f in sorted(root.rglob("*")) if f.is_file()}


def gates(tree, work, mode=1):
    """Returns the problems of the twin at `tree`; `work` is a scratch directory."""
    problems = []
    work = pathlib.Path(work)
    (work / "world_cap.json").write_text(json.dumps(world_cap(tree, mode)))
    (work / "world_off.json").write_text(json.dumps(world_cap(tree, 0)))
    world = json.loads((work / "world_cap.json").read_text())
    for seed, size in ((20261112, "small"), (1, "small")):
        r = gen(tree, work, "world_cap.json", seed, size, "core,dispensing", "b_%d_%s" % (seed, size))
        if r.returncode != 0:
            return ["G30: the batch twin refused the enforced world: " + r.stdout[-200:] + r.stderr[-200:]]
        d = work / ("b_%d_%s" % (seed, size))
        bad, binding, groups = room_violations(d, world)
        if bad:
            problems.append("G30: seed %d %s: %d pharmacy-class-weeks order more than their room (first %s)" % (seed, size, len(bad), bad[0]))
        diff = recompute_policy(d, world, mode)
        if diff:
            problems.append("G30: seed %d %s: %d cells differ from the recomputed policy (first %s)" % (seed, size, len(diff), diff[0]))
        if binding == 0:
            problems.append("G30: seed %d %s: the limit never binds: the gate is not exercised" % (seed, size))
    # flag 0 is the old world: a recompute without the cut equals the table
    r = gen(tree, work, "world_off.json", 20261112, "small", "core,dispensing", "off")
    if r.returncode != 0 or recompute_policy(work / "off", world, mode=0):
        problems.append("G30: with the flag at 0 the orders are not the uncut policy")
    # stepped = batch in the enforced configurations
    for seed, size, tables in ((20261112, "small", FULL), (1, "small", FULL), (20261112, "small", "core,dispensing"), (20261112, "small", "core,dispensing,refills"), (20261112, "small", "core,dispensing,delivery,coupled")):
        n = "%d_%s_%s" % (seed, size, tables.replace(",", "_"))
        a = gen(tree, work, "world_cap.json", seed, size, tables, "sb_" + n)
        b = gen(tree, work, "world_cap.json", seed, size, tables, "ss_" + n, ["--engine", "step"])
        if a.returncode != 0 or b.returncode != 0 or snapshot(work / ("sb_" + n)) != snapshot(work / ("ss_" + n)):
            problems.append("G30: stepped and batch twins differ in the enforced configuration %s" % n)
    # G31: decisions
    d = work / "b_20261112_small"
    items = {r["item"]: r for r in read(d / "items.csv")}
    cap = {r["pharmacy"]: (int(r["shelf_capacity_units"]), int(r["cold_capacity_units"])) for r in read(d / "pharmacies.csv")}
    pick = None
    stock = {}
    for r in read(d / "dispensing.csv"):
        k = (r["pharmacy"], 1 if items[r["item"]]["cold_chain"] == "1" else 0, int(r["week"]))
        stock[k] = stock.get(k, 0) + int(r["stock_end"])
    for (ph, cold, wk), s in sorted(stock.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1])):
        room = cap[ph][cold] - s
        if wk >= 5 and room > 0:
            cands = [it for it in sorted(items) if (items[it]["cold_chain"] == "1") == bool(cold) and int(items[it]["pack_size"]) <= room]
            if cands:
                pick = (ph, cold, wk, room, cands[0], int(items[cands[0]]["pack_size"]))
                break
    if pick is None:
        problems.append("G31: no pharmacy-week with a room to test")
        return problems
    ph, cold, wk, room, it, pack = pick
    fit = (room // pack) * pack
    for label, units, ok in (("at the room", fit, True), ("above the room", fit + pack, False)):
        dd = work / ("dec_" + label.replace(" ", "_"))
        dd.mkdir(exist_ok=True)
        (dd / ("week-%d.json" % wk)).write_text(json.dumps({"week": wk, "orders": [{"pharmacy": ph, "item": it, "units": units}]}))
        r = gen(tree, work, "world_cap.json", 20261112, "small", "core,dispensing", "o_" + label.replace(" ", "_"), ["--engine", "step", "--decisions", str(dd.relative_to(work))])
        if ok and r.returncode != 0:
            problems.append("G31: an order of %d units at a room of %d was refused: %s" % (units, room, r.stdout[-160:]))
        if not ok:
            if r.returncode != 2 or "twin.decision-over-room" not in r.stdout + r.stderr or (work / "o_above_the_room").exists():
                problems.append("G31: an order above the room was not refused as twin.decision-over-room with nothing written (exit %d)" % r.returncode)
    r = gen(tree, work, "world_off.json", 20261112, "small", "core,dispensing", "o_off", ["--engine", "step", "--decisions", "dec_above_the_room"])
    if r.returncode != 0:
        problems.append("G31: with the flag at 0 the room rule is applied")
    return problems


def main(argv):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="check_cap_"))
    problems = []
    for mode in (1, 2):
        (tmp / ("main%d" % mode)).mkdir()
        mp_ = gates(HERE, tmp / ("main%d" % mode), mode)
        print("G30, G31 on the committed twin, mode %d: %s" % (mode, "hold" if not mp_ else "FAIL: " + "; ".join(mp_)))
        problems += mp_
    if problems:
        return 1
    if "--mutants" in argv:
        names = argv[argv.index("--mutants") + 1:] or list(MUTANTS)
        survived = 0
        for n in names:
            rel, old, new, mmode = MUTANTS[n]
            tree = tmp / ("tree_" + n)
            shutil.copytree(HERE, tree, ignore=shutil.ignore_patterns("__pycache__"))
            text = (tree / rel).read_text()
            if text.count(old) != 1:
                print("%s: its text occurs %d times in %s" % (n, text.count(old), rel))
                return 2
            (tree / rel).write_text(text.replace(old, new))
            w = tmp / ("work_" + n)
            w.mkdir()
            mp = gates(tree, w, mmode)
            print("%s: %s" % (n, "killed by " + mp[0][:130] if mp else "SURVIVED"))
            survived += 0 if mp else 1
        print("check_cap: %d of %d mutants killed" % (len(names) - survived, len(names)))
        return 1 if survived else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
