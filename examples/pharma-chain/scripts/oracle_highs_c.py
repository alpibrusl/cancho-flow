#!/usr/bin/env python3
"""The independent oracle of G5 for the charging decisions: HiGHS (through scipy) solves each night from the DATA of the model (models/D*.json), never from the model text, and its optimal cost must equal the one `solve` printed.

    python3 oracle_highs_c.py ROOT        # ROOT holds models/D*.json and models/D*.plan.json; prints one JSON line

Exit 3 and a JSON line with rule oracle.no-scipy when scipy is missing, so that a gate can say "not run".
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
    worst, n, bad = 0.0, 0, []
    for jf in sorted(glob.glob(os.path.join(argv[0], "models", "D*.json"))):
        if jf.endswith(".plan.json") or jf.endswith(".verify.json"):
            continue
        d = json.load(open(jf))
        plan = json.load(open(jf[:-5] + ".plan.json"))
        V, T = d["V"], d["T"]
        m = V * T
        c = np.concatenate([np.array([d["price"][t] for v in range(V) for t in range(T)]), np.zeros(m)])  # x = [charge (V*T), on (V*T)]
        rows, lo, hi = [], [], []
        for v in range(V):
            r = np.zeros(2 * m); r[v * T:(v + 1) * T] = 1.0
            rows.append(r); lo.append(d["need"][v]); hi.append(np.inf)
        for t in range(T):
            r = np.zeros(2 * m)
            for v in range(V):
                r[m + v * T + t] = 1.0
            rows.append(r); lo.append(-np.inf); hi.append(float(d["chargers"]))
            r = np.zeros(2 * m)
            for v in range(V):
                r[v * T + t] = 1.0
            rows.append(r); lo.append(-np.inf); hi.append(float(d["cap"][t]))
        for k in range(m):
            r = np.zeros(2 * m); r[k] = 1.0; r[m + k] = -float(d["pmax"])
            rows.append(r); lo.append(-np.inf); hi.append(0.0)
        ub = np.concatenate([np.full(m, float(d["pmax"])), np.array([float(a) for a in d["avail"]])])
        res = milp(c, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=np.concatenate([np.zeros(m), np.ones(m)]), bounds=Bounds(np.zeros(2 * m), ub))
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
