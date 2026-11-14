#!/usr/bin/env python3
"""The stops of the delivery analysis (docs/use-cases.md section 4.2, step 1).

    python3 features_a.py DATA_DIR OUT.csv

Reads DATA_DIR/routes.csv, telemetry.csv and days.csv (never truth/) and writes one row per delivery stop (the return to the depot is left out): the outside temperature and its band
(cool at or below 15, hot at or above 25, mild between), the minutes the doors were open and their band (0 to 2, 3 to 5, 6 or more), the minutes since the last stop, the energy of the
leg and the energy per minute (two decimals), and whether the cabin went above 8.0 degrees. `table` has no computed columns (read 2026-11-12), hence a program.
"""
import csv
import os
import sys

sys.dont_write_bytecode = True


def temp_band(t):
    return "hot" if t >= 25 else ("cool" if t <= 15 else "mild")


def door_band(m):
    return "0-2" if m <= 2 else ("3-5" if m <= 5 else "6+")


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('{"ok":false,"error":{"rule":"features.usage","message":"features_a.py DATA_DIR OUT.csv","repair":"give the data directory and the output file"}}\n')
        return 2
    data, out = argv
    day_of = {r["route"]: int(r["day"]) for r in csv.DictReader(open(os.path.join(data, "routes.csv"), newline=""))}
    temp = {int(r["day"]): int(r["outside_temp_c"]) for r in csv.DictReader(open(os.path.join(data, "days.csv"), newline=""))}
    with open(out, "w", newline="") as f, open(os.path.join(data, "telemetry.csv"), newline="") as g:
        w = csv.writer(f, lineterminator="\n")
        w.writerow("route seq day pharmacy temp_c temp_band door_min door_band minutes energy_wh wh_per_min excursion".split())
        for r in csv.DictReader(g):
            if r["pharmacy"] == "DEPOT":
                continue
            d = day_of[r["route"]]
            t = temp[d]
            mins, wh, door = int(r["minutes"]), int(r["energy_wh"]), int(r["door_open_min"])
            per = wh * 100 // mins
            w.writerow([r["route"], r["seq"], d, r["pharmacy"], t, temp_band(t), door, door_band(door), mins, wh, "%d.%02d" % (per // 100, per % 100), int(int(r["cabin_temp_dc"]) > 80)])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
