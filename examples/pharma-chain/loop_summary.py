#!/usr/bin/env python3
"""The summary of the loop's week, one stage at a time and then merged (docs/use-cases.md section 4, U5).

    python3 loop_summary.py c WEEK ROOT OUT                  # replenishment: per pharmacy, units ordered and the plan's objective
    python3 loop_summary.py b WEEK ROOT OUT                  # outreach: per pharmacy, events, outreaches by kind and the plan's expected value
    python3 loop_summary.py a DAY0 DAY1 ROOT OUT             # charging: per night, trucks, planned kWh and the plan's cost
    python3 loop_summary.py d WEEK DATA OUT                  # coupling: the late and warm pharmacies of the week and the stockout items of this and the next week
    python3 loop_summary.py merge OUT c.json b.json a.json d.json

ROOT holds c/models, b/models and a/models as the loop's steps left them. A step declares at most 64 files, so each stage is summarised on its own. Every number is an integer or a decimal with a fixed number of places;
the output is JSON with sorted keys, so the same plans give the same bytes (no clock, no path).
"""
import csv
import glob
import json
import os
import sys

sys.dont_write_bytecode = True


def dump(path, doc):
    with open(path, "w", newline="\n") as f:
        f.write(json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n")


def plans(root, kind, pattern):
    for jf in sorted(glob.glob(os.path.join(root, kind, "models", pattern))):
        if jf.endswith(".plan.json") or jf.endswith(".verify.json"):
            continue
        yield jf, json.load(open(jf)), json.load(open(jf[:-5] + ".plan.json"))


def stage_c(week, root, out):
    res = {}
    for jf, d, plan in plans(root, "c", "W%s_P*.json" % week):
        ordered = 0
        for i in range(d["n"]):
            ordered += d["pack"][i] * int(round(plan["x"]["q[%d]" % i]))
        res[d["pharmacy"]] = {"ordered_units": ordered, "objective": "%.6f" % plan["objective"]}
    dump(out, {"week": int(week), "pharmacies": res})


def stage_b(week, root, out):
    res = {}
    for jf, d, plan in plans(root, "b", "W%s_P*.json" % week):
        n = d["n"]
        counts = {}
        for name, key in (("call", "xc"), ("reminder", "xr"), ("switch90", "xs"), ("delivery", "xd")):
            counts[name] = sum(int(round(plan["x"]["%s[%d]" % (key, e)])) for e in range(n))
        counts["events"] = n
        counts["expected_value"] = "%.6f" % plan["objective"]
        res[d["pharmacy"]] = counts
    dump(out, {"week": int(week), "pharmacies": res})


def stage_a(day0, day1, root, out):
    res = {}
    for jf, d, plan in plans(root, "a", "D*.json"):
        res[str(d["day"])] = {"trucks": d["V"], "planned_kwh": "%.3f" % sum(d["need"]), "cost": "%.6f" % plan["objective"]}
    dump(out, {"days": [int(day0), int(day1)], "nights": res})


def stage_d(week, data, out):
    week = int(week)
    day_of = {r["route"]: int(r["day"]) for r in csv.DictReader(open(os.path.join(data, "routes.csv"), newline=""))}
    late, warm = set(), set()
    for r in csv.DictReader(open(os.path.join(data, "telemetry.csv"), newline="")):
        if r["pharmacy"] == "DEPOT" or day_of[r["route"]] // 7 != week:
            continue
        if int(r["arrive_min"]) > int(r["window_end_min"]):
            late.add(r["pharmacy"])
        if int(r["cabin_temp_dc"]) > 80:
            warm.add(r["pharmacy"])
    flagged = late | warm
    so = {str(week): [0, 0], str(week + 1): [0, 0]}
    for r in csv.DictReader(open(os.path.join(data, "dispensing.csv"), newline="")):
        w = r["week"]
        if w in so and r["stockout"] == "1":
            so[w][0 if r["pharmacy"] in flagged else 1] += 1
    dump(out, {"week": week, "late": sorted(late), "warm": sorted(warm), "stockout_items": {w: {"flagged_pharmacies": v[0], "others": v[1]} for w, v in so.items()}})


def merge(out, cj, bj, aj, dj):
    dump(out, {"c": json.load(open(cj)), "b": json.load(open(bj)), "a": json.load(open(aj)), "coupling": json.load(open(dj))})


def main(argv):
    try:
        k = argv[0]
        if k == "c" and len(argv) == 4:
            stage_c(argv[1], argv[2], argv[3])
        elif k == "b" and len(argv) == 4:
            stage_b(argv[1], argv[2], argv[3])
        elif k == "a" and len(argv) == 5:
            stage_a(argv[1], argv[2], argv[3], argv[4])
        elif k == "d" and len(argv) == 4:
            stage_d(argv[1], argv[2], argv[3])
        elif k == "merge" and len(argv) == 6:
            merge(*argv[1:])
        else:
            raise IndexError
    except (IndexError, ValueError, OSError, KeyError):
        sys.stderr.write('{"ok":false,"error":{"rule":"summary.usage","message":"see the docstring of loop_summary.py","repair":"give a stage and its operands"}}\n')
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
