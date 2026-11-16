#!/usr/bin/env python3
"""The lag features of the NEXT week of the weekly panel (docs/use-cases.md section 7a, U7b): what a forecast made at the end of week W knows about week W+1.

    python3 features_next.py DATA_DIR OUT.csv

Reads DATA_DIR/dispensing.csv, items.csv and pharmacies.csv (never truth/), which hold the weeks up to W, and writes one row per pharmacy and item for week W+1 in the columns of features.py: the target `units`
is written 0 (it is not known), the lags are those of features.py computed from the weeks up to W. Only the standard library; every number is an integer.
"""
import csv
import os
import sys

sys.dont_write_bytecode = True


def season(woy):
    if woy >= 47 or woy <= 7:
        return "winter"
    if 22 <= woy <= 33:
        return "summer"
    return "shoulder"


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('{"ok":false,"error":{"rule":"features.usage","message":"features_next.py DATA_DIR OUT.csv","repair":"give the data directory and the output file"}}\n')
        return 2
    data, out = argv
    rows = list(csv.DictReader(open(os.path.join(data, "dispensing.csv"), newline="")))
    items = {r["item"]: r for r in csv.DictReader(open(os.path.join(data, "items.csv"), newline=""))}
    phs = {r["pharmacy"]: r for r in csv.DictReader(open(os.path.join(data, "pharmacies.csv"), newline=""))}
    by = {}
    for r in rows:
        by.setdefault((r["pharmacy"], r["item"]), []).append(r)
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow("pharmacy item week units lag1 lag2 lag4sum stockout1 woy season pack_size shelf_life_days cold_chain group scale_ppm".split())
        for (p, i), rs in sorted(by.items()):
            u = [int(r["units"]) for r in rs]
            t = len(rs)  # the next week
            if t < 4:
                continue
            it = items[i]
            w.writerow([p, i, t, 0, u[t - 1], u[t - 2], sum(u[t - 4:t]), rs[t - 1]["stockout"], t % 52, season(t % 52), it["pack_size"], it["shelf_life_days"], it["cold_chain"], it["therapeutic_group"], phs[p]["scale_ppm"]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
