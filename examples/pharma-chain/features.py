#!/usr/bin/env python3
"""The lag features of the weekly panel (docs/use-cases.md section 4.1, step 1).

    python3 features.py DATA_DIR OUT.csv

Reads DATA_DIR/dispensing.csv, items.csv and pharmacies.csv (never truth/) and writes one row per pharmacy, item and week from week 4: the units sold that
week (the target), last week's and the week before's, the sum of the four weeks before, whether last week was a stockout, the week of the year, a season
label for the calendar (winter, summer, shoulder), and what the pharmacy knows of the item and of itself. `table` has no computed columns and no window
functions (read from `table skill --full`, 2026-11-12), which is why this is a program and not a query.

Only the standard library; every number is an integer, so the bytes are the same everywhere.
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
        sys.stderr.write('{"ok":false,"error":{"rule":"features.usage","message":"features.py DATA_DIR OUT.csv","repair":"give the data directory and the output file"}}\n')
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
            it = items[i]
            for t in range(4, len(rs)):
                w.writerow([p, i, t, u[t], u[t - 1], u[t - 2], sum(u[t - 4:t]), rs[t - 1]["stockout"], t % 52, season(t % 52),
                            it["pack_size"], it["shelf_life_days"], it["cold_chain"], it["therapeutic_group"], phs[p]["scale_ppm"]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
