#!/usr/bin/env python3
"""The predicted energy of each test route side by side (docs/use-cases.md section 4.2, U4c).

    python3 pred_routes.py TEST_E.csv PRED_BOOST.json PRED_BASE.json OUT.csv

TEST_E.csv is the file the two models were asked to predict, the two JSON files are what `ml predict` printed for it; the rows are in the same order. Writes route, day, pred_boost_wh and pred_base_wh.
"""
import csv
import json
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 4:
        sys.stderr.write('{"ok":false,"error":{"rule":"join.usage","message":"pred_routes.py TEST_E.csv PRED_BOOST.json PRED_BASE.json OUT.csv","repair":"give the four operands"}}\n')
        return 2
    test, pb, pl, out = argv
    rows = list(csv.DictReader(open(test, newline="")))
    a, b = json.load(open(pb))["data"], json.load(open(pl))["data"]
    if a.get("truncated") or b.get("truncated") or len(a["rows"]) != len(rows) or len(b["rows"]) != len(rows):
        sys.stderr.write('{"ok":false,"error":{"rule":"join.rows","message":"the predictions do not have the rows of the test file (or were truncated)","repair":"predict with --limit at least the number of rows"}}\n')
        return 2
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["route", "day", "pred_boost_wh", "pred_base_wh"])
        for r, x, y in zip(rows, a["rows"], b["rows"]):
            w.writerow([r["route"], r["day"], repr(float(x[0])), repr(float(y[0]))])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
