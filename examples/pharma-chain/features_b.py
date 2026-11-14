#!/usr/bin/env python3
"""The refill events of the adherence model (docs/use-cases.md section 4.3, step 1).

    python3 features_b.py DATA_DIR OUT.csv

Reads DATA_DIR/refills.csv and patients.csv (never truth/) and writes one row per refill event: the label (lapsed, 1 when the refill was not filled), whether the home pharmacy
was out of the item in the weeks before, what the pharmacy knows of the patient (the number of chronic items, the co-payment band and the age band, as labels for the tests and as
integers for the model), the interval, and how many refills of that item were filled before this one. `table` has no computed columns (read 2026-11-12), hence a program.
"""
import csv
import os
import sys

sys.dont_write_bytecode = True
COPAY = ("low", "mid", "high")
AGE = ("18-39", "40-54", "55-64", "65-74", "75+")


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('{"ok":false,"error":{"rule":"features.usage","message":"features_b.py DATA_DIR OUT.csv","repair":"give the data directory and the output file"}}\n')
        return 2
    data, out = argv
    pat = {r["patient"]: r for r in csv.DictReader(open(os.path.join(data, "patients.csv"), newline=""))}
    before = {}
    with open(out, "w", newline="") as f, open(os.path.join(data, "refills.csv"), newline="") as g:
        w = csv.writer(f, lineterminator="\n")
        w.writerow("patient item due_week lapsed stockout_seen n_items copay copay_band age age_band interval_weeks fills_before".split())
        for r in csv.DictReader(g):
            p = pat[r["patient"]]
            key = (r["patient"], r["item"])
            k = before.get(key, 0)
            before[key] = k + 1
            w.writerow([r["patient"], r["item"], r["due_week"], 1 - int(r["filled"]), r["stockout_seen"], p["n_items"], COPAY.index(p["copay_band"]), p["copay_band"],
                        AGE.index(p["age_band"]), p["age_band"], r["interval_weeks"], k])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
