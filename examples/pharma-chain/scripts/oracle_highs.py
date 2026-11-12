#!/usr/bin/env python3
"""The independent oracle of G5: HiGHS (through scipy) solves each decision from the DATA of the model (models/*.json), never from the model text, and its optimal
objective must equal the one `solve` printed.

    python3 oracle_highs.py ROOT        # ROOT holds models/W*_P*.json and models/W*_P*.plan.json; prints one JSON line

Needs scipy (a Python with scipy: set SCIPY_PYTHON for the caller). Exit 3 and a JSON line with rule oracle.no-scipy when it is missing, so that a gate can say "not run".
"""
import glob
import json
import os
import sys

sys.dont_write_bytecode = True


def main(argv):
    try:
        import numpy as np
        from scipy.optimize import LinearConstraint, Bounds, milp
    except ImportError:
        print(json.dumps({"ok": False, "rule": "oracle.no-scipy"}))
        return 3
    root = argv[0]
    worst, n = 0.0, 0
    bad = []
    for jf in sorted(glob.glob(os.path.join(root, "models", "W*_P*.json"))):
        if jf.endswith(".plan.json") or jf.endswith(".verify.json"):
            continue
        d = json.load(open(jf))
        plan = json.load(open(jf[:-5] + ".plan.json"))
        m = d["n"]
        # x = [q (m), s (m), over (m)]
        c = np.concatenate([np.full(m, 0.0) + np.array([d["holding"] * p for p in d["pack"]]), np.array(d["pen"], dtype=float), np.full(m, float(d["waste"]))])
        rows, lo, hi = [], [], []
        for i in range(m):
            r = np.zeros(3 * m); r[i] = d["pack"][i]; r[m + i] = 1.0
            rows.append(r); lo.append(d["target"][i] - d["stock"][i]); hi.append(np.inf)
            r = np.zeros(3 * m); r[2 * m + i] = 1.0; r[i] = -d["pack"][i]
            rows.append(r); lo.append(d["stock"][i] - d["cover"][i]); hi.append(np.inf)
        for flag, room in ((1, d["room_cold"]), (0, d["room_shelf"])):
            r = np.zeros(3 * m)
            for i in range(m):
                if d["cold"][i] == flag:
                    r[i] = d["pack"][i]
            if r.any():
                rows.append(r); lo.append(-np.inf); hi.append(float(room))
        ub = np.concatenate([np.array(d["qmax"], dtype=float), np.full(2 * m, 1e6)])
        integrality = np.concatenate([np.ones(m), np.zeros(2 * m)])
        res = milp(c, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=integrality, bounds=Bounds(np.zeros(3 * m), ub))
        if not res.success:
            bad.append("%s: HiGHS status %s" % (os.path.basename(jf), res.status))
            continue
        gap = abs(res.fun - plan["objective"]) / max(1.0, abs(res.fun))
        worst, n = max(worst, gap), n + 1
        if gap > 1e-6:
            bad.append("%s: HiGHS %.9f, solve %.9f" % (os.path.basename(jf), res.fun, plan["objective"]))
    print(json.dumps({"ok": not bad, "instances": n, "worst_relative_gap": worst, "bad": bad[:5]}))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
