#!/usr/bin/env python3
"""G10 (docs/use-cases.md section 7a): how large a route-selection model `solve` takes. Random seeded instances, not the twin.

    SOLVE=<solve> [SCIPY_PYTHON=<python with scipy>] python3 scripts/route_pool_size.py [--sizes 10,14,18] [--seeds 1,2,3] [--runs 3]

D deliveries, each a pharmacy at a random point of a 40 km square with a 2-hour window starting on the hour between 08:00 and 14:00 and 15 minutes of service; every subset of up to 3
deliveries, in the order of their window ends, that meets every window (30 km/h, wait until a window opens) is a route; a route has an energy (0.45 kWh/km plus 2 kW of refrigeration for the
whole duration) and a cost (0.2 per kWh plus 30 a route). K = 8 trucks with batteries 60, 80, 100, 120 kWh (twice) and a reserve of 15 kWh; a truck takes a route only if energy + reserve fits. Each
delivery exactly once, each truck at most one route. All numbers are choices of this experiment. Prints one line per instance and a verdict per claim.
"""
import itertools
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
BATT = [60.0, 80.0, 100.0, 120.0] * 2
RESERVE = 15.0
K = 8


def instance(D, seed):
    rnd = random.Random(seed * 1000 + D)
    dels = []
    for _ in range(D):
        x, y = rnd.uniform(0, 40), rnd.uniform(0, 40)
        a = 8 + rnd.randrange(0, 7)
        dels.append((x, y, a * 60.0, (a + 2) * 60.0))  # minutes from midnight
    order = sorted(range(D), key=lambda i: (dels[i][3], i))
    routes = []
    for n in (1, 2, 3):
        for sub in itertools.combinations(order, n):
            t, px, py, dist, ok = 8 * 60.0 - 60.0, 0.0, 0.0, 0.0, True  # leaves the depot (at 0,0) at 07:00
            for i in sub:
                d = math.hypot(dels[i][0] - px, dels[i][1] - py)
                t += d / 30.0 * 60.0
                dist += d
                if t > dels[i][3]:
                    ok = False
                    break
                t = max(t, dels[i][2]) + 15.0
                px, py = dels[i][0], dels[i][1]
            if ok:
                dist += math.hypot(px, py)
                t += math.hypot(px, py) / 30.0 * 60.0
                dur_h = (t - (8 * 60.0 - 60.0)) / 60.0
                energy = 0.45 * dist + 2.0 * dur_h
                routes.append((sub, energy, 0.2 * energy + 30.0))
    return dels, routes


def model(D, routes):
    R = len(routes)
    cover = [1 if d in sub else 0 for d in range(D) for sub, _, _ in routes]
    ok = [1 if e + RESERVE <= BATT[k] else 0 for _, e, _ in routes for k in range(K)]
    t = "param D = %d;\nparam R = %d;\nparam K = %d;\n" % (D, R, K)
    t += "param cost = [%s];\n" % ", ".join("%.6f" % c for _, _, c in routes)
    t += "param cover = [%s];\n" % ", ".join(str(v) for v in cover)
    t += "param fits = [%s];\n" % ", ".join(str(v) for v in ok)
    t += "var y[0..R, 0..K] : bool;\n"
    t += "minimize total: sum r in 0..R: sum k in 0..K: cost[r] * y[r,k];\nsubject to\n"
    t += "    forall d in 0..D: once: sum r in 0..R: sum k in 0..K: cover[d*R+r] * y[r,k] == 1;\n"
    t += "    forall k in 0..K: one_route: sum r in 0..R: y[r,k] <= 1;\n"
    t += "    forall r in 0..R: forall k in 0..K: battery: y[r,k] <= fits[r*K+k];\n"
    return t


def highs(D, routes):
    py = os.environ.get("SCIPY_PYTHON", sys.executable)
    code = r'''
import json,sys
import numpy as np
from scipy.optimize import LinearConstraint, Bounds, milp
d=json.load(sys.stdin); D,R,K=d["D"],d["R"],d["K"]
c=np.repeat(np.array(d["cost"]),K)  # y[r,k] at r*K+k
rows,lo,hi=[],[],[]
for dl in range(D):
    r=np.zeros(R*K)
    for j in range(R):
        if d["cover"][dl*R+j]: r[j*K:(j+1)*K]=1
    rows.append(r);lo.append(1);hi.append(1)
for k in range(K):
    r=np.zeros(R*K); r[k::K]=1; rows.append(r);lo.append(-np.inf);hi.append(1)
ub=np.array(d["fits"],dtype=float)
res=milp(c,constraints=LinearConstraint(np.array(rows),lo,hi),integrality=np.ones(R*K),bounds=Bounds(np.zeros(R*K),ub))
print(json.dumps({"status":int(res.status),"obj":float(res.fun) if res.success else None}))
'''
    cover = [1 if d in sub else 0 for d in range(D) for sub, _, _ in routes]
    ok = [1 if e + RESERVE <= BATT[k] else 0 for _, e, _ in routes for k in range(K)]
    r = subprocess.run([py, "-c", code], input=json.dumps({"D": D, "R": len(routes), "K": K, "cost": [c for _, _, c in routes], "cover": cover, "fits": ok}), capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def main(argv):
    sizes, seeds, runs = [10, 14, 18], [1, 2, 3], 3
    for i, a in enumerate(argv):
        if a == "--sizes":
            sizes = [int(x) for x in argv[i + 1].split(",")]
        if a == "--seeds":
            seeds = [int(x) for x in argv[i + 1].split(",")]
        if a == "--runs":
            runs = int(argv[i + 1])
    solve = os.environ.get("SOLVE", "solve")
    try:
        load = open("/proc/loadavg").read().split()[:3]
    except OSError:
        load = ["?"]
    print("machine: %d cores, load average at start %s" % (os.cpu_count(), " ".join(load)))
    out = {}
    for D in sizes:
        for seed in seeds:
            dels, routes = instance(D, seed)
            text = model(D, routes)
            with tempfile.NamedTemporaryFile("w", suffix=".sol", delete=False) as f:
                f.write(text)
            best, doc = None, None
            for _ in range(runs):
                t0 = time.time()
                r = subprocess.run([solve, "run"] + (["--node-limit", "20000"] if D >= 18 else []), stdin=open(f.name), capture_output=True, text=True, timeout=1800)
                dt = time.time() - t0
                if best is None or dt < best:
                    best = dt
                try:
                    doc = json.loads(r.stdout)
                except ValueError:
                    doc = {"status": "no-json", "error": (r.stdout + r.stderr)[:200]}
            os.unlink(f.name)
            h = highs(D, routes) if doc.get("status") == "optimal" and os.environ.get("SKIP_ORACLE") != "1" else None
            gap = None
            if h and h.get("obj") is not None:
                gap = abs(h["obj"] - doc["objective"]) / max(1.0, abs(h["obj"]))
            out[(D, seed)] = (doc.get("status"), best, gap)
            print("D=%2d seed=%d routes=%4d binaries=%5d  status=%-8s objective=%s  time(min of %d)=%.2fs  nodes=%s  HiGHS gap=%s" % (
                D, seed, len(routes), len(routes) * K, doc.get("status"), ("%.4f" % doc["objective"]) if "objective" in doc else "-", runs, best,
                (doc.get("stats") or {}).get("nodes", "?"), ("%.1e" % gap) if gap is not None else "n/a"))
            sys.stdout.flush()
    bad = []
    for D, bound in ((10, 5.0), (14, 60.0)):
        if D in sizes:
            rows = [out[(D, s)] for s in seeds if (D, s) in out]
            ok = all(st == "optimal" and t <= bound for st, t, _ in rows)
            print("claim %s (D=%d optimal within %.0f s on every seed): %s" % ("a" if D == 10 else "b", D, bound, "holds" if ok else "FAILS"))
            if not ok:
                bad.append(D)
    gaps = [g for (_, _, g) in out.values() if g is not None]
    cl = all(g <= 1e-6 for g in gaps) and bool(gaps)
    print("claim c (every optimal objective equals HiGHS's to 1e-6 relative; %d compared): %s" % (len(gaps), "holds" if cl else "FAILS or not run"))
    return 0 if not bad and cl else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
