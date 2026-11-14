#!/usr/bin/env python3
"""One row per leg (a stop, or the return to the depot) for the calibration of the twin's energy coefficients (docs/use-cases.md section 4.2, U4c).

    python3 features_a3.py DATA_DIR OUT.csv

Reads DATA_DIR/routes.csv, telemetry.csv and days.csv (never truth/): day, outside temperature, km, minutes, door-open minutes and the energy in watt-hours of each leg.
"""
import csv
import os
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('{"ok":false,"error":{"rule":"features.usage","message":"features_a3.py DATA_DIR OUT.csv","repair":"give the data directory and the output file"}}\n')
        return 2
    data, out = argv
    day_of = {r["route"]: int(r["day"]) for r in csv.DictReader(open(os.path.join(data, "routes.csv"), newline=""))}
    temp = {int(r["day"]): int(r["outside_temp_c"]) for r in csv.DictReader(open(os.path.join(data, "days.csv"), newline=""))}
    with open(out, "w", newline="") as f, open(os.path.join(data, "telemetry.csv"), newline="") as g:
        w = csv.writer(f, lineterminator="\n")
        w.writerow("route seq day temp_c km minutes door_min energy_wh".split())
        for r in csv.DictReader(g):
            d = day_of[r["route"]]
            w.writerow([r["route"], r["seq"], d, temp[d], r["km"], r["minutes"], r["door_open_min"], r["energy_wh"]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
