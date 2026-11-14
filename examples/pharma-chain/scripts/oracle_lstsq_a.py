#!/usr/bin/env python3
"""The independent oracle of G12: the four coefficients of the per-leg energy solved exactly by linear least squares (the model is linear in them after a change of variables), in scipy/numpy, apart from `opt`.

    python3 oracle_lstsq_a.py LEGS.csv     # prints one JSON line: the minimal sum of squared errors (millions of Wh squared) and the coefficients (Wh per km, W, ppm, W)

Exit 3 and a JSON line with rule oracle.no-scipy when numpy is missing.
"""
import csv
import json
import sys

sys.dont_write_bytecode = True


def main(argv):
    try:
        import numpy as np
    except ImportError:
        print(json.dumps({"ok": False, "rule": "oracle.no-scipy"}))
        return 3
    X, Y = [], []
    for r in csv.DictReader(open(argv[0], newline="")):
        T = int(r["temp_c"])
        X.append([int(r["km"]), int(r["minutes"]), int(r["minutes"]) * max(0, T - 20) / 10.0, int(r["door_min"]) / 60.0])
        Y.append(int(r["energy_wh"]))
    X, Y = np.array(X, float), np.array(Y, float)
    b = np.linalg.lstsq(X, Y, rcond=None)[0]
    sse = float(((Y - X @ b) ** 2).sum()) / 1e6
    fw = 60.0 * b[1]
    print(json.dumps({"ok": True, "sse": sse, "drive": float(b[0]), "fridge_w": float(fw), "ppm": float(b[2] * 60.0 / fw * 1e6), "door_w": float(b[3]), "n": len(Y)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
