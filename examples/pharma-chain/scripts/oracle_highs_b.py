#!/usr/bin/env python3
"""The independent oracle of G5 for the outreach decisions: HiGHS (through scipy) solves each decision from the DATA of the model (models/*.json), never from the model text, and its
optimal objective must equal the one `solve` printed.

    python3 oracle_highs_b.py ROOT        # ROOT holds models/W*_P*.json and models/W*_P*.plan.json; prints one JSON line

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
    root = argv[0]
    worst, n, bad = 0.0, 0, []
    for jf in sorted(glob.glob(os.path.join(root, "models", "W*_P*.json"))):
        if jf.endswith(".plan.json") or jf.endswith(".verify.json"):
            continue
        d = json.load(open(jf))
        plan = json.load(open(jf[:-5] + ".plan.json"))
        m = d["n"]
        # x = [xc (m), xr (m), xs (m), xd (m)]; minimise the negated gain
        c = np.concatenate([-np.array([d["days"][e] * d["p"][e] * d["uplift"][k] for e in range(m)]) for k in range(4)])
        rows, hi = [], []
        for e in range(m):
            r = np.zeros(4 * m)
            for k in range(4):
                r[k * m + e] = 1.0
            rows.append(r); hi.append(1.0)
        for coef, cap in ((d["minutes"], d["cap_minutes"]), (d["money"], d["cap_money"])):
            r = np.zeros(4 * m)
            for k in range(4):
                r[k * m:(k + 1) * m] = coef[k]
            rows.append(r); hi.append(float(cap))
        r = np.zeros(4 * m)
        r[3 * m:] = 1.0
        rows.append(r); hi.append(float(d["cap_slots"]))
        res = milp(c, constraints=LinearConstraint(np.array(rows), -np.inf, np.array(hi)), integrality=np.ones(4 * m), bounds=Bounds(np.zeros(4 * m), np.ones(4 * m)))
        if not res.success:
            bad.append("%s: HiGHS status %s" % (os.path.basename(jf), res.status))
            continue
        gap = abs(-res.fun - plan["objective"]) / max(1.0, abs(res.fun))
        worst, n = max(worst, gap), n + 1
        if gap > 1e-6:
            bad.append("%s: HiGHS %.9f, solve %.9f" % (os.path.basename(jf), -res.fun, plan["objective"]))
    print(json.dumps({"ok": not bad, "instances": n, "worst_relative_gap": worst, "bad": bad[:5]}))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
