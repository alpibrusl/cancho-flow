#!/usr/bin/env python3
"""The replenishment decision as a model for `solve` (docs/use-cases.md section 4.1, step 4).

    python3 build_models.py [--only WEEK:PHARMACY] DATA_DIR TEST.csv PRED.json COSTS.json OUT_DIR

For every pharmacy and every held-out week it writes OUT_DIR/models/W<week>_<pharmacy>.sol (the model, in the language of `solve`) and .json (the same
numbers as data, which the oracles read: they never parse the model text), and OUT_DIR/models/index.csv. It reads the forecast of `ml predict` and what the
pharmacy knows at the end of the previous week (its stock, from dispensing.csv); it never reads truth/.

The decision for one pharmacy and one week: how many packs q[i] of each item to order, so that
    minimise   sum_i  pen_i * s_i + waste * over_i + holding * pack_i * q_i
    s_i    >= target_i - (stock_i + pack_i * q_i)          the shortfall against the target, target_i = forecast_i + z * sqrt(forecast_i)
    over_i >= stock_i + pack_i * q_i - cover_i             the units held beyond cover_i = min(shelf weeks, 52) * forecast_i
    sum over cold items of pack_i * q_i     <= room_cold   the room left in the refrigerated space (never below zero: the pharmacy may hold more than its cap)
    sum over other items of pack_i * q_i    <= room_shelf
    q_i integer in 0..max_packs, and 0..controlled_max_packs for a controlled item.
"""
import csv
import json
import os
import sys

sys.dont_write_bytecode = True


def num(x):
    return ("%.6f" % x).rstrip("0").rstrip(".") or "0"


def arr(xs):
    return "[" + ", ".join(num(x) if isinstance(x, float) else str(x) for x in xs) + "]"


def instance(items, forecast, stock, cap_cold, cap_shelf, costs):
    """The data of one decision. items: list of dicts (pack, cold, critical, controlled, shelf_weeks); forecast and stock: lists aligned with items."""
    z = costs["z_milli"]["value"] / 1000.0
    f = [max(0.0, x) for x in forecast]
    target = [fi + z * (max(fi, 1.0) ** 0.5) for fi in f]
    cover = [min(52, it["shelf_weeks"]) * fi for it, fi in zip(items, f)]
    room_cold = max(0, cap_cold - sum(s for it, s in zip(items, stock) if it["cold"]))
    room_shelf = max(0, cap_shelf - sum(s for it, s in zip(items, stock) if not it["cold"]))
    return {
        "n": len(items), "f": f, "target": target, "cover": cover, "stock": list(stock),
        "pack": [it["pack"] for it in items], "cold": [it["cold"] for it in items], "controlled": [it["controlled"] for it in items],
        "pen": [costs["penalty_per_unit_short_critical"]["value"] if it["critical"] else costs["penalty_per_unit_short"]["value"] for it in items],
        "waste": costs["waste_per_unit"]["value"], "holding": costs["holding_per_unit"]["value"],
        "qmax": [costs["controlled_max_packs"]["value"] if it["controlled"] else costs["max_packs"]["value"] for it in items],
        "room_cold": room_cold, "room_shelf": room_shelf, "cap_cold": cap_cold, "cap_shelf": cap_shelf,
    }


def model_text(d):
    n = d["n"]
    cold = [i for i in range(n) if d["cold"][i]]
    warm = [i for i in range(n) if not d["cold"][i]]
    t = "param n = %d;\n" % n
    t += "param target = %s;\nparam stock = %s;\nparam pack = %s;\nparam pen = %s;\nparam cover = %s;\n" % (arr(d["target"]), arr(d["stock"]), arr(d["pack"]), arr(d["pen"]), arr(d["cover"]))
    t += "var q[0..n] : int 0..%d;\nvar s[0..n] : real 0..1000000;\nvar over[0..n] : real 0..1000000;\n" % max(d["qmax"])
    t += "minimize cost: sum i in 0..n: (pen[i] * s[i] + %s * over[i] + %s * pack[i] * q[i]);\nsubject to\n" % (num(float(d["waste"])), num(float(d["holding"])))
    t += "    forall i in 0..n: short: s[i] + stock[i] + pack[i] * q[i] >= target[i];\n"
    t += "    forall i in 0..n: waste: over[i] >= stock[i] + pack[i] * q[i] - cover[i];\n"
    for i in range(n):
        if d["qmax"][i] < max(d["qmax"]):
            t += "    qcap%d: q[%d] <= %d;\n" % (i, i, d["qmax"][i])
    if cold:
        t += "    coldroom: " + " + ".join("pack[%d] * q[%d]" % (i, i) for i in cold) + " <= %d;\n" % d["room_cold"]
    if warm:
        t += "    shelfroom: " + " + ".join("pack[%d] * q[%d]" % (i, i) for i in warm) + " <= %d;\n" % d["room_shelf"]
    return t


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main(argv):
    only = None
    if len(argv) >= 2 and argv[0] == "--only":
        only, argv = argv[1], argv[2:]
    if len(argv) != 5:
        sys.stderr.write('{"ok":false,"error":{"rule":"plan.usage","message":"build_models.py DATA_DIR TEST.csv PRED.json COSTS.json OUT_DIR","repair":"give the five operands"}}\n')
        return 2
    data, test_csv, pred_json, costs_json, out = argv
    costs = json.load(open(costs_json))
    pred = [float(r[0]) for r in json.load(open(pred_json))["data"]["rows"]]
    test = read(test_csv)
    if len(pred) != len(test):
        sys.stderr.write('{"ok":false,"error":{"rule":"plan.forecast-rows","message":"the forecast has %d rows, the test file %d","repair":"predict with --limit at least the number of rows"}}\n' % (len(pred), len(test)))
        return 2
    items = {r["item"]: r for r in read(os.path.join(data, "items.csv"))}
    phs = {r["pharmacy"]: r for r in read(os.path.join(data, "pharmacies.csv"))}
    stock_end = {(r["pharmacy"], r["item"], int(r["week"])): int(r["stock_end"]) for r in read(os.path.join(data, "dispensing.csv"))}
    cells = {}
    for r, p in zip(test, pred):
        cells.setdefault((int(r["week"]), r["pharmacy"]), []).append((r["item"], p))
    os.makedirs(os.path.join(out, "models"), exist_ok=True)
    index = ["week,pharmacy,items"]
    if only is not None and not any(only == "%d:%s" % k for k in cells):
        sys.stderr.write('{"ok":false,"error":{"rule":"plan.no-such-cell","message":"no cell %s in the test file","repair":"use --only WEEK:PHARMACY of a held-out week"}}\n' % only)
        return 2
    for (week, ph), cs in sorted(cells.items()):
        if only is not None and only != "%d:%s" % (week, ph):
            continue
        its = [{"pack": int(items[i]["pack_size"]), "cold": int(items[i]["cold_chain"]), "critical": int(items[i]["critical"]), "controlled": int(items[i]["controlled"]),
                "shelf_weeks": int(items[i]["shelf_life_days"]) // 7} for i, _ in cs]
        stock = [stock_end[(ph, i, week - 1)] for i, _ in cs]
        d = instance(its, [p for _, p in cs], stock, int(phs[ph]["cold_capacity_units"]), int(phs[ph]["shelf_capacity_units"]), costs)
        d["week"], d["pharmacy"], d["items"] = week, ph, [i for i, _ in cs]
        base = os.path.join(out, "models", "W%d_%s" % (week, ph))
        with open(base + ".sol", "w", newline="\n") as f:
            f.write(model_text(d))
        with open(base + ".json", "w", newline="\n") as f:
            f.write(json.dumps(d, sort_keys=True, separators=(",", ":")) + "\n")
        index.append("%d,%s,%d" % (week, ph, len(cs)))
    if only is None:
        with open(os.path.join(out, "models", "index.csv"), "w", newline="\n") as f:
            f.write("\n".join(index) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
