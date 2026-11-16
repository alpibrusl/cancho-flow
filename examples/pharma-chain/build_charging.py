#!/usr/bin/env python3
"""The overnight charging decision as a model for `solve` (docs/use-cases.md section 4.2, U4c; the model of cancho-solve's docs/examples/ev_depot.sol, built per night from the data).

    python3 build_charging.py [--pred pred_base_wh] DAY DATA_DIR PRED.csv CHARGING.json OUT_DIR

For the trucks that ran a route on DAY: the need of each is the predicted energy of its route plus the safety, by the departure hour; a truck can draw from the hour after its last arrival; at most `chargers` draw
in an hour, each at most `pmax_kw`, and the sum of an hour is at most the depot's `cap_kw`; the price of an hour is the depot's tariff. Writes OUT_DIR/models/D<day>.sol and .json (the same numbers as data, which the oracles read).
It reads routes.csv, telemetry.csv (the last arrival) and depot.csv, and the predictions; never truth/.
"""
import csv
import json
import os
import sys

sys.dont_write_bytecode = True


def num(x):
    return ("%.9f" % x).rstrip("0").rstrip(".") or "0"


def arr(xs):
    return "[" + ", ".join(num(x) if isinstance(x, float) else str(x) for x in xs) + "]"


def instance(need, arrive_h, price_by_hour, cap_by_hour, cfg, dep_h):
    h0 = min(arrive_h)
    T = dep_h - h0
    V = len(need)
    return {"V": V, "T": T, "h0": h0, "need": need, "avail": [1 if h0 + t >= arrive_h[v] else 0 for v in range(V) for t in range(T)],
            "price": [price_by_hour[(h0 + t) % 24] for t in range(T)], "cap": [cap_by_hour[(h0 + t) % 24] for t in range(T)], "pmax": cfg["pmax_kw"], "chargers": cfg["chargers"]}


def model_text(d):
    t = "param V = %d;\nparam T = %d;\nparam price = %s;\nparam cap = %s;\nparam need = %s;\nparam avail = %s;\n" % (d["V"], d["T"], arr(d["price"]), arr(d["cap"]), arr(d["need"]), arr(d["avail"]))
    t += "var charge[0..V, 0..T] : real 0..%d;\nvar on[0..V, 0..T] : bool;\n" % d["pmax"]
    t += "minimize cost: sum v in 0..V: sum t in 0..T: price[t] * charge[v,t];\nsubject to\n"
    t += "    forall v in 0..V: energy: sum t in 0..T: charge[v,t] >= need[v];\n"
    t += "    forall v in 0..V: forall t in 0..T: plugged: on[v,t] <= avail[v*T+t];\n"
    t += "    forall v in 0..V: forall t in 0..T: link: charge[v,t] <= %d * on[v,t];\n" % d["pmax"]
    t += "    forall t in 0..T: chargers_free: sum v in 0..V: on[v,t] <= %d;\n" % d["chargers"]
    t += "    forall t in 0..T: grid_limit: sum v in 0..V: charge[v,t] <= cap[t];\n"
    return t


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main(argv):
    col = "pred_boost_wh"
    if len(argv) >= 2 and argv[0] == "--pred":
        col, argv = argv[1], argv[2:]
    if len(argv) != 5:
        sys.stderr.write('{"ok":false,"error":{"rule":"charging.usage","message":"build_charging.py [--pred COL] DAY DATA_DIR PRED.csv CHARGING.json OUT_DIR","repair":"give the five operands"}}\n')
        return 2
    day, data, pred_csv, cfg_path, out = argv
    day = int(day)
    cfg = json.load(open(cfg_path))
    pred = {r["route"]: float(r[col]) for r in read(pred_csv)}
    last = {}
    for r in read(os.path.join(data, "telemetry.csv")):
        last[r["route"]] = int(r["arrive_min"])
    depot = read(os.path.join(data, "depot.csv"))
    price = [int(r["tariff_milli"]) / 1000.0 for r in depot]
    cap = [int(r["cap_kw"]) for r in depot]
    routes = [r for r in read(os.path.join(data, "routes.csv")) if int(r["day"]) == day]
    if not routes or any(r["route"] not in pred for r in routes):
        sys.stderr.write('{"ok":false,"error":{"rule":"charging.no-night","message":"no routes on day %d, or a route without a prediction","repair":"use a day of the test file that has routes"}}\n' % day)
        return 2
    need = [pred[r["route"]] / 1000.0 + cfg["safety_kwh"] for r in routes]
    arrive_h = [-(-last[r["route"]] // 60) for r in routes]
    d = instance(need, arrive_h, price, cap, cfg, cfg["departure_hour"])
    d["day"], d["routes"], d["trucks"] = day, [r["route"] for r in routes], [r["truck"] for r in routes]
    os.makedirs(os.path.join(out, "models"), exist_ok=True)
    base = os.path.join(out, "models", "D%d" % day)
    with open(base + ".sol", "w", newline="\n") as f:
        f.write(model_text(d))
    with open(base + ".json", "w", newline="\n") as f:
        f.write(json.dumps(d, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
