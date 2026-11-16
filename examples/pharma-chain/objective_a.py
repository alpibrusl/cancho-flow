#!/usr/bin/env python3
"""The objective of the calibration of the twin's energy coefficients, in the protocol of `opt minimize` (docs/use-cases.md section 4.2, U4c).

    opt minimize --x0 3.5,1.2,1.5,1.5 -- ./objective_a.py legs.csv

The point arrives on standard input (four numbers: the driving rate in units of 100 Wh per km, the refrigeration power in kW, the heat fraction in units of 100,000 ppm per 10 degrees, the door power in kW) and the
sum of squared errors, in millions of squared watt-hours, is printed. The model of a leg: km * drive + minutes * (fridge_w / 60) * (1 + ppm / 1e6 * max(0, T - 20) / 10) + door_min * door_w / 60.
"""
import csv
import sys

sys.dont_write_bytecode = True


def main(argv):
    x = [float(v) for v in sys.stdin.read().split()]
    if len(x) != 4 or len(argv) != 1:
        sys.stderr.write("objective_a.py: four numbers on standard input and the legs file as the argument\n")
        return 2
    drive, fridge_w, ppm, door_w = x[0] * 100.0, x[1] * 1000.0, x[2] * 100000.0, x[3] * 1000.0
    sse = 0.0
    with open(argv[0], newline="") as f:
        for r in csv.DictReader(f):
            T = int(r["temp_c"])
            m = int(r["minutes"])
            model = int(r["km"]) * drive + m * (fridge_w / 60.0) * (1.0 + ppm / 1e6 * max(0, T - 20) / 10.0) + int(r["door_min"]) * door_w / 60.0
            e = int(r["energy_wh"]) - model
            sse += e * e
    print(repr(sse / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
