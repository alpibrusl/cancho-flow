#!/usr/bin/env python3
"""The refill events due in the NEXT week (docs/use-cases.md section 7a, U7b): what a pharmacist knows at the end of week W about the refills of week W+1.

    python3 events_next.py DATA_DIR WEEK WINDOW OUT.csv

WEEK is W+1. Reads DATA_DIR/refills.csv, patients.csv and dispensing.csv (never truth/), which hold the weeks up to W. A refill series continues exactly when its last refill was filled, and then the next one is due
one interval later: that is the event of WEEK. Writes the columns of features_b.py for each such event; the label `lapsed` is 0 (not known) and `stockout_seen` looks at the WINDOW weeks before WEEK (the stock of WEEK
itself is not known yet). Sorted by patient and item. Only the standard library.
"""
import csv
import os
import sys

sys.dont_write_bytecode = True
COPAY = ("low", "mid", "high")
AGE = ("18-39", "40-54", "55-64", "65-74", "75+")


def main(argv):
    if len(argv) != 4 or not argv[1].isdigit() or not argv[2].isdigit():
        sys.stderr.write('{"ok":false,"error":{"rule":"events.usage","message":"events_next.py DATA_DIR WEEK WINDOW OUT.csv","repair":"give the data directory, the week, the stockout window in weeks and the output file"}}\n')
        return 2
    data, week, window, out = argv[0], int(argv[1]), int(argv[2]), argv[3]
    pat = {r["patient"]: r for r in csv.DictReader(open(os.path.join(data, "patients.csv"), newline=""))}
    stock = set()
    for r in csv.DictReader(open(os.path.join(data, "dispensing.csv"), newline="")):
        if r["stockout"] == "1":
            stock.add((r["pharmacy"], r["item"], int(r["week"])))
    last, count = {}, {}
    for r in csv.DictReader(open(os.path.join(data, "refills.csv"), newline="")):
        key = (r["patient"], r["item"])
        last[key] = r
        count[key] = count.get(key, 0) + 1
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow("patient item due_week lapsed stockout_seen n_items copay copay_band age age_band interval_weeks fills_before".split())
        for key in sorted(last):
            r = last[key]
            interval = int(r["interval_weeks"])
            if r["filled"] != "1" or int(r["due_week"]) + interval != week:
                continue
            p = pat[key[0]]
            seen = int(any((r["pharmacy"], key[1], x) in stock for x in range(max(0, week - window), week)))
            w.writerow([key[0], key[1], week, 0, seen, p["n_items"], COPAY.index(p["copay_band"]), p["copay_band"], AGE.index(p["age_band"]), p["age_band"], interval, count[key]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
