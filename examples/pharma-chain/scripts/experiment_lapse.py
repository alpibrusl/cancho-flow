#!/usr/bin/env python3
"""U8: the replenishment plan with the lapse cost (docs/use-cases.md section 7a, G24 to G26 and the claims L1 to L3, committed before this was written).

    CANCHO=<compiler> SCIPY_PYTHON=<python with scipy> python3 scripts/experiment_lapse.py --prev DIR_OF_U7C --out DIR [--seeds 20261112,1] [--judge-only]

Runs the arms CL (the replenishment plans with the lapse cost) and TL (CL and the outreach plans) for each seed, same weeks as experiment.py; D, C and T are those of the U7c run in --prev (their outcomes are read, not
recomputed: that run was repeated byte for byte). Then G21 to G24 for the new arms (experiment.judge), and the claims.
"""
import os
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import experiment as ex  # noqa: E402

L1, L2, L3 = 0.95, 0.97, 1.00   # the margins of docs/use-cases.md section 7a (U8), fixed before this was written
FIRST, LAST, END = 90, 101, 103


def main(argv):
    def arg(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    prev, out = arg("--prev"), arg("--out")
    if not prev or not out:
        sys.stderr.write("experiment_lapse.py --prev DIR --out DIR [--seeds a,b] [--judge-only]\n")
        return 2
    prev, base = pathlib.Path(prev).resolve(), pathlib.Path(out).resolve()
    seeds = [int(x) for x in arg("--seeds", "20261112,1").split(",")]
    base.mkdir(parents=True, exist_ok=True)
    if "--judge-only" not in argv:
        env = dict(os.environ, FLOW_TIMEOUT_MS=os.environ.get("FLOW_TIMEOUT_MS", "600000"))
        procs = [("%s_%d" % (a, s), subprocess.Popen([sys.executable, str(HERE / "scripts" / "closed_loop.py"), "--arm", a, "--seed", str(s), "--out", str(base / ("%s_%d" % (a, s))), "--first", str(FIRST), "--last", str(LAST), "--end", str(END)],
                                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)) for s in seeds for a in ("CL", "TL")]
        failed = []
        for name, p in procs:
            o = p.communicate()[0]
            if p.returncode != 0:
                failed.append("%s: %s" % (name, o.strip()[-300:]))
        if failed:
            print("experiment_lapse: an arm stopped: " + "\n".join(failed))
            return 1
    for s in seeds:
        link = base / ("D_%d" % s)
        if not link.exists():
            os.symlink(prev / ("D_%d" % s), link)
    rc = ex.judge(seeds, base, FIRST, LAST, END, arms=("CL", "TL"), with_claims=False)
    res = {}
    for s in seeds:
        res[(s, "D")] = ex.outcomes(prev / ("D_%d" % s) / "data", FIRST, LAST, END)
        for a in ("C", "T"):
            res[(s, a)] = ex.outcomes(prev / ("%s_%d" % (a, s)) / "root" / "data", FIRST, LAST, END)
        for a in ("CL", "TL"):
            res[(s, a)] = ex.outcomes(base / ("%s_%d" % (a, s)) / "root" / "data", FIRST, LAST, END)
    claims = (("L1", "CL has at most %.2f of C's stockout cells" % L1, lambda s: res[(s, "CL")]["stockout_cells"] / res[(s, "C")]["stockout_cells"], lambda r: r <= L1),
              ("L2", "CL has at most %.2f of C's lapses" % L2, lambda s: res[(s, "CL")]["lapses"] / res[(s, "C")]["lapses"], lambda r: r <= L2),
              ("L3", "TL has at most %.2f of D's lapses" % L3, lambda s: res[(s, "TL")]["lapses"] / res[(s, "D")]["lapses"], lambda r: r <= L3))
    bad = 0
    for cid, text, f, ok in claims:
        vals = [f(s) for s in seeds]
        holds = all(ok(v) for v in vals)
        print("CLAIM %s (%s): %s -> %s" % (cid, text, "; ".join("seed %d: %.3f" % (s, v) for s, v in zip(seeds, vals)), "holds on every seed" if holds else "FAILS"))
        bad += 0 if holds else 1
    for s in seeds:
        for a in ("D", "C", "CL", "T", "TL"):
            o = res[(s, a)]
            print("seed %d arm %s: orders %d units (weeks %d-%d), stockout cells %d, units short %d, written off %d, events %d, lapses %d (weeks %d-%d)" % (
                s, a, o["orders_units"], FIRST, LAST, o["stockout_cells"], o["units_short"], o["written_off"], o["events"], o["lapses"], FIRST + 1, END))
    print("experiment_lapse: gates %s, %d of 3 claims fail" % ("hold" if rc == 0 else "FAIL", bad))
    return 0 if rc == 0 and bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
