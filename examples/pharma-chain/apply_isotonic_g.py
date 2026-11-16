#!/usr/bin/env python3
"""Apply the monotone fit of `ml isotonic` to predicted probabilities, for any keys (docs/use-cases.md section 4.2, U4b; apply_isotonic.py is the same for the refill events).

    python3 apply_isotonic_g.py ISO.json PRED.csv OUT.csv LABEL KEY1,KEY2,...

The fitted function is a step function: a probability takes the fitted value of the largest fitted point at or below it, and the first fitted value below the fitted range. Writes the keys, LABEL, p_raw and p.
"""
import bisect
import csv
import json
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 5:
        sys.stderr.write('{"ok":false,"error":{"rule":"iso.usage","message":"apply_isotonic_g.py ISO.json PRED.csv OUT.csv LABEL KEYS","repair":"give the five operands"}}\n')
        return 2
    iso, pred, out, label, keys = argv
    keys = keys.split(",")
    fit = json.load(open(iso))["data"]["fit"]
    xs = [float(f["x"]) for f in fit]
    ys = [float(f["fitted"]) for f in fit]
    with open(pred, newline="") as g, open(out, "w", newline="") as f:
        rd = csv.DictReader(g)
        w = csv.writer(f, lineterminator="\n")
        w.writerow(keys + [label, "p_raw", "p"])
        for r in rd:
            p = float(r["p"])
            k = max(0, bisect.bisect_right(xs, p) - 1)
            w.writerow([r[c] for c in keys] + [r[label], r["p"], repr(ys[k])])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
