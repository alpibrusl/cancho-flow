#!/usr/bin/env python3
"""One row per route for the energy model (docs/use-cases.md section 4.2, U4b).

    python3 features_a2.py DATA_DIR OUT.csv

Reads DATA_DIR/routes.csv and telemetry.csv (never truth/) and writes, per route: the day, the number of stops, the distance in km, the day's outside temperature, the span in minutes from 07:00 to the end of the
last window (all known when the route is planned) and the energy in watt-hours (the target).
"""
import csv
import os
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('{"ok":false,"error":{"rule":"features.usage","message":"features_a2.py DATA_DIR OUT.csv","repair":"give the data directory and the output file"}}\n')
        return 2
    data, out = argv
    last_end = {}
    for r in csv.DictReader(open(os.path.join(data, "telemetry.csv"), newline="")):
        if r["pharmacy"] != "DEPOT":
            last_end[r["route"]] = int(r["window_end_min"])
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow("route day stops distance_km temp_c span_min energy_wh".split())
        for r in csv.DictReader(open(os.path.join(data, "routes.csv"), newline="")):
            w.writerow([r["route"], r["day"], r["stops"], r["distance_km"], r["outside_temp_c"], last_end[r["route"]] - int(r["depart_min"]), r["energy_wh"]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
