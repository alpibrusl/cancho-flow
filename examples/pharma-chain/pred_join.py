#!/usr/bin/env python3
"""The label and the predicted probability of each refill event side by side (docs/use-cases.md section 4.3).

    python3 pred_join.py EVENTS.csv PRED.json OUT.csv

EVENTS.csv is the file the model was asked to predict, PRED.json is what `ml predict --proba` printed for it; the rows are in the same order. Writes lapsed and p, with the keys.
"""
import csv
import json
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 3:
        sys.stderr.write('{"ok":false,"error":{"rule":"join.usage","message":"pred_join.py EVENTS.csv PRED.json OUT.csv","repair":"give the three operands"}}\n')
        return 2
    events, pred, out = argv
    p = json.load(open(pred))["data"]
    rows = list(csv.DictReader(open(events, newline="")))
    if p.get("truncated") or len(p["rows"]) != len(rows):
        sys.stderr.write('{"ok":false,"error":{"rule":"join.rows","message":"the predictions have %d rows, the events %d (or they were truncated)","repair":"predict with --limit at least the number of rows"}}\n' % (len(p["rows"]), len(rows)))
        return 2
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["patient", "item", "due_week", "lapsed", "p"])
        for r, (_, prob) in zip(rows, p["rows"]):
            w.writerow([r["patient"], r["item"], r["due_week"], r["lapsed"], repr(float(prob))])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
