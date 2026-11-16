#!/usr/bin/env python3
"""U9: the replenishment plan without its room constraint (docs/use-cases.md section 7a, G27, G28 and the claims R1 to R5, committed before this was written).

    CANCHO=<compiler> SCIPY_PYTHON=<python with scipy> python3 scripts/experiment_room.py --prev DIR_OF_U7C --out DIR [--seeds 20261112,1] [--judge-only]

Arms CR (replenishment plans, no room), CLR (CR with the lapse term) and TLR (CLR and the outreach plans) for each seed, the weeks of experiment.py; D, C and T are those of the U7c run in --prev. G21 to G24 and G27 by
experiment.judge, then the claims.
"""
import csv
import os
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import experiment as ex  # noqa: E402

R1, R2, R3, R4, R5 = 0.85, 0.50, 0.95, 0.97, 1.00   # fixed before this was written
FIRST, LAST, END = 90, 101, 103
ARMS = ("CR", "CLR", "TLR")


def cold_cells(data):
    cold = {r["item"] for r in csv.DictReader(open(os.path.join(data, "items.csv"), newline="")) if r["cold_chain"] == "1"}
    n = 0
    for r in csv.DictReader(open(os.path.join(data, "dispensing.csv"), newline="")):
        if FIRST + 1 <= int(r["week"]) <= END and r["item"] in cold:
            n += int(r["stockout"])
    return n


def main(argv):
    def arg(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    prev, out = arg("--prev"), arg("--out")
    if not prev or not out:
        sys.stderr.write("experiment_room.py --prev DIR --out DIR [--seeds a,b] [--judge-only]\n")
        return 2
    prev, base = pathlib.Path(prev).resolve(), pathlib.Path(out).resolve()
    seeds = [int(x) for x in arg("--seeds", "20261112,1").split(",")]
    base.mkdir(parents=True, exist_ok=True)
    if "--judge-only" not in argv:
        env = dict(os.environ, FLOW_TIMEOUT_MS=os.environ.get("FLOW_TIMEOUT_MS", "600000"))
        procs = [("%s_%d" % (a, s), subprocess.Popen([sys.executable, str(HERE / "scripts" / "closed_loop.py"), "--arm", a, "--seed", str(s), "--out", str(base / ("%s_%d" % (a, s))), "--first", str(FIRST), "--last", str(LAST), "--end", str(END)],
                                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)) for s in seeds for a in ARMS]
        failed = []
        for name, p in procs:
            o = p.communicate()[0]
            if p.returncode != 0:
                failed.append("%s: %s" % (name, o.strip()[-300:]))
        if failed:
            print("experiment_room: an arm stopped: " + "\n".join(failed))
            return 1
    for s in seeds:
        link = base / ("D_%d" % s)
        if not link.exists():
            os.symlink(prev / ("D_%d" % s), link)
    rc = ex.judge(seeds, base, FIRST, LAST, END, arms=ARMS, with_claims=False)
    res, cold = {}, {}
    for s in seeds:
        paths = {"D": prev / ("D_%d" % s) / "data", "C": prev / ("C_%d" % s) / "root" / "data", "CL": base.parent / "lapse" / ("CL_%d" % s) / "root" / "data"}
        for a in ARMS:
            paths[a] = base / ("%s_%d" % (a, s)) / "root" / "data"
        for a, pth in paths.items():
            if pth.exists():
                res[(s, a)] = ex.outcomes(pth, FIRST, LAST, END)
                cold[(s, a)] = cold_cells(pth)
    claims = (("R1", "CR has at most %.2f of C's stockout cells" % R1, lambda s: res[(s, "CR")]["stockout_cells"] / res[(s, "C")]["stockout_cells"], R1),
              ("R2", "CR has at most %.2f of C's cold-chain stockout cells" % R2, lambda s: cold[(s, "CR")] / cold[(s, "C")], R2),
              ("R3", "CR has at most %.2f of C's lapses" % R3, lambda s: res[(s, "CR")]["lapses"] / res[(s, "C")]["lapses"], R3),
              ("R4", "CLR has at most %.2f of CR's lapses" % R4, lambda s: res[(s, "CLR")]["lapses"] / res[(s, "CR")]["lapses"], R4),
              ("R5", "TLR has at most %.2f of D's lapses" % R5, lambda s: res[(s, "TLR")]["lapses"] / res[(s, "D")]["lapses"], R5))
    bad = 0
    for cid, text, f, lim in claims:
        vals = [f(s) for s in seeds]
        holds = all(v <= lim for v in vals)
        print("CLAIM %s (%s): %s -> %s" % (cid, text, "; ".join("seed %d: %.3f" % (s, v) for s, v in zip(seeds, vals)), "holds on every seed" if holds else "FAILS"))
        bad += 0 if holds else 1
    for s in seeds:
        for a in ("D", "C", "CL", "CR", "CLR", "TLR"):
            if (s, a) in res:
                o = res[(s, a)]
                print("seed %d arm %s: orders %d units (weeks %d-%d), stockout cells %d (cold-chain %d), units short %d, written off %d, events %d, lapses %d (weeks %d-%d)" % (
                    s, a, o["orders_units"], FIRST, LAST, o["stockout_cells"], cold[(s, a)], o["units_short"], o["written_off"], o["events"], o["lapses"], FIRST + 1, END))
    print("experiment_room: gates %s, %d of 5 claims fail" % ("hold" if rc == 0 else "FAIL", bad))
    return 0 if rc == 0 and bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
