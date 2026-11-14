#!/usr/bin/env python3
"""One row per pharmacy, item and week for the coupling A to C (docs/use-cases.md section 4.2, U4d, step 1).

    python3 features_ad.py DATA_DIR OUT.csv

Reads DATA_DIR/dispensing.csv, items.csv, routes.csv and telemetry.csv (never truth/). A pharmacy-week is *late* when a stop of that pharmacy in that week arrived after its window closed and *warm* when a stop had a cabin above
8.0 degrees: both are what the delivery files show, which is what the analysis side sees. Writes the stockout flag, late, warm, whether the item is cold-chain, the units received and whether anything was written off.
"""
import csv
import os
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('{"ok":false,"error":{"rule":"features.usage","message":"features_ad.py DATA_DIR OUT.csv","repair":"give the data directory and the output file"}}\n')
        return 2
    data, out = argv
    day_of = {r["route"]: int(r["day"]) for r in csv.DictReader(open(os.path.join(data, "routes.csv"), newline=""))}
    late, warm = set(), set()
    for r in csv.DictReader(open(os.path.join(data, "telemetry.csv"), newline="")):
        if r["pharmacy"] == "DEPOT":
            continue
        wk = day_of[r["route"]] // 7
        if int(r["arrive_min"]) > int(r["window_end_min"]):
            late.add((r["pharmacy"], wk))
        if int(r["cabin_temp_dc"]) > 80:
            warm.add((r["pharmacy"], wk))
    cold = {r["item"]: r["cold_chain"] for r in csv.DictReader(open(os.path.join(data, "items.csv"), newline=""))}
    with open(out, "w", newline="") as f, open(os.path.join(data, "dispensing.csv"), newline="") as g:
        w = csv.writer(f, lineterminator="\n")
        w.writerow("pharmacy item week stockout late warm cold received wo".split())
        for r in csv.DictReader(g):
            k = (r["pharmacy"], int(r["week"]))
            w.writerow([r["pharmacy"], r["item"], r["week"], r["stockout"], int(k in late), int(k in warm), cold[r["item"]], r["received"], int(int(r["written_off"]) > 0)])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
