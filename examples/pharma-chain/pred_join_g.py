#!/usr/bin/env python3
"""The label and the predicted probability of each row side by side, for any keys (docs/use-cases.md section 4.2, U4b; pred_join.py is the same for the refill events).

    python3 pred_join_g.py EVENTS.csv PRED.json OUT.csv LABEL KEY1,KEY2,...

PRED.json is what `ml predict --proba` printed for EVENTS.csv; the rows are in the same order. Writes the keys, LABEL and p.
"""
import csv
import json
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 5:
        sys.stderr.write('{"ok":false,"error":{"rule":"join.usage","message":"pred_join_g.py EVENTS.csv PRED.json OUT.csv LABEL KEYS","repair":"give the five operands"}}\n')
        return 2
    events, pred, out, label, keys = argv
    keys = keys.split(",")
    p = json.load(open(pred))["data"]
    rows = list(csv.DictReader(open(events, newline="")))
    if p.get("truncated") or len(p["rows"]) != len(rows):
        sys.stderr.write('{"ok":false,"error":{"rule":"join.rows","message":"the predictions have %d rows, the events %d (or they were truncated)","repair":"predict with --limit at least the number of rows"}}\n' % (len(p["rows"]), len(rows)))
        return 2
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(keys + [label, "p"])
        for r, (_, prob) in zip(rows, p["rows"]):
            w.writerow([r[k] for k in keys] + [r[label], repr(float(prob))])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
