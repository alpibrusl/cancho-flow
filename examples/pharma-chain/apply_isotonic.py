#!/usr/bin/env python3
"""Apply the monotone fit of `ml isotonic` to predicted probabilities (docs/use-cases.md section 4.3).

    python3 apply_isotonic.py ISO.json PRED.csv OUT.csv

ISO.json is what `ml isotonic --x-col p --y-col lapsed` printed on a calibration file; PRED.csv has a column p. The fitted function is a step function: a probability takes the
fitted value of the largest fitted point at or below it, and the first (or last) fitted value outside the fitted range. Writes p_raw and p.
"""
import bisect
import csv
import json
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 3:
        sys.stderr.write('{"ok":false,"error":{"rule":"iso.usage","message":"apply_isotonic.py ISO.json PRED.csv OUT.csv","repair":"give the three operands"}}\n')
        return 2
    iso, pred, out = argv
    fit = json.load(open(iso))["data"]["fit"]
    xs = [float(f["x"]) for f in fit]
    ys = [float(f["fitted"]) for f in fit]
    with open(pred, newline="") as g, open(out, "w", newline="") as f:
        rd = csv.DictReader(g)
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["patient", "item", "due_week", "lapsed", "p_raw", "p"])
        for r in rd:
            p = float(r["p"])
            k = max(0, bisect.bisect_right(xs, p) - 1)
            w.writerow([r["patient"], r["item"], r["due_week"], r["lapsed"], r["p"], repr(ys[k])])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
