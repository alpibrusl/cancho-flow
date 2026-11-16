#!/usr/bin/env python3
"""U10: the loop in a world with real space limits (docs/use-cases.md section 7a, G30 to G32 and the claims S1 to S4, committed before this was written).

    CANCHO=<compiler> SCIPY_PYTHON=<python with scipy> python3 scripts/experiment_cap.py --out DIR [--prev DIR_OF_U7C] [--seeds 20261112,1] [--judge-only]

The world is world.json with `enforce_capacity` 1. Arms: D2 (the batch twin, its own policy under the limit), C2, B2 and T2 (closed_loop.py --enforce, arms C, B and T), for each seed, the weeks of experiment.py. G21 to G23 by
experiment.judge, G32 by check_cap.plan_rooms, G30 on D2 and on every arm (room_violations, recompute_policy), then the claims.
"""
import csv
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import check_cap as cc  # noqa: E402
import experiment as ex  # noqa: E402

S1, S2, S3, S4 = 1.00, 1.10, 1.00, 0.90   # fixed before this was written
FIRST, LAST, END = 90, 101, 103
ARMS = ("C", "B", "T")


def by_class(data):
    """Stockout cells over weeks FIRST+1..END: all, critical items, cold-chain items."""
    items = {r["item"]: r for r in cc.read(pathlib.Path(data) / "items.csv")}
    n = {"all": 0, "critical": 0, "cold": 0}
    for r in cc.read(pathlib.Path(data) / "dispensing.csv"):
        if FIRST + 1 <= int(r["week"]) <= END:
            s = int(r["stockout"])
            n["all"] += s
            n["critical"] += s * int(items[r["item"]]["critical"])
            n["cold"] += s * int(items[r["item"]]["cold_chain"])
    return n


def main(argv):
    def arg(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    out = arg("--out")
    if not out:
        sys.stderr.write("experiment_cap.py --out DIR [--prev DIR_OF_U7C] [--mode 1|2] [--seeds a,b] [--judge-only]\n")
        return 2
    mode = int(arg("--mode", 1))
    base = pathlib.Path(out).resolve()
    prev = pathlib.Path(arg("--prev")).resolve() if arg("--prev") else None
    seeds = [int(x) for x in arg("--seeds", "20261112,1").split(",")]
    base.mkdir(parents=True, exist_ok=True)
    world = cc.world_cap(HERE, mode)
    if "--judge-only" not in argv:
        env = dict(os.environ, FLOW_TIMEOUT_MS=os.environ.get("FLOW_TIMEOUT_MS", "600000"))
        for s in seeds:  # the batch arm first: in mode 2 the stop rule (N1 to N3) is judged on it before any other arm runs
            dd = base / ("D_%d" % s)
            dd.mkdir(exist_ok=True)
            (dd / "world.json").write_text(json.dumps(world))
            r = subprocess.run([sys.executable, str(HERE / "twin.py"), "generate", "--world", "world.json", "--seed", str(s), "--size", "large", "--tables", "core,dispensing,refills,delivery,coupled", "--out", "data", "--overwrite"], cwd=str(dd), capture_output=True, text=True)
            if r.returncode != 0:
                print("experiment_cap: the batch arm D2 failed: " + r.stdout[-300:] + r.stderr[-300:])
                return 1
        if mode == 2:
            stop = False
            for s in seeds:
                rep_, probs_, diff_ = cc.world_checks(base / ("D_%d" % s) / "data", world, prev / ("D_%d" % s) / "data")
                print("STOP RULE seed %d: %s" % (s, "; ".join(rep_)))
                for pr in probs_:
                    print("STOP RULE FAILS: " + pr)
                    stop = True
                if diff_:
                    print("G34 FAILS: %d cells of D2' differ from the recomputed policy" % len(diff_))
                    stop = True
            if stop:
                print("experiment_cap: the stop rule or G34 failed; no arm was run, and the margins are not moved")
                return 3
        procs = [("%s_%d" % (a, s), subprocess.Popen([sys.executable, str(HERE / "scripts" / "closed_loop.py"), "--arm", a, "--seed", str(s), "--out", str(base / ("%s_%d" % (a, s))), "--first", str(FIRST), "--last", str(LAST), "--end", str(END), "--enforce", str(mode)],
                                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)) for s in seeds for a in ARMS]
        failed = []
        for name, p in procs:
            o = p.communicate()[0]
            if p.returncode != 0:
                failed.append("%s: %s" % (name, o.strip()[-300:]))
        if failed:
            print("experiment_cap: an arm stopped: " + "\n".join(failed))
            return 1

    def hook(name, root):
        n, probs = cc.plan_rooms(str(root / "c" / "models"), str(root / "data")) if (root / "c" / "models").exists() else (0, [])
        rep = ["G32 %s: the room of the model equals the world's room in %d plans: %s" % (name, n, "all" if not probs else "%d differ" % len(probs))]
        bad, binding, groups = cc.room_violations(root / "data", world)
        rep.append("G30 %s: %d pharmacy-class-weeks order more than their room; the room binds in %d of %d" % (name, len(bad), binding, groups))
        return rep, probs + ["G30: %s: %d pharmacy-class-weeks order more than their room" % (name, len(bad))] * (1 if bad else 0)
    rc = ex.judge(seeds, base, FIRST, LAST, END, arms=ARMS, with_claims=False, hook=hook)
    res, cls = {}, {}
    extra = []
    for s in seeds:
        d2 = base / ("D_%d" % s) / "data"
        paths = {"D2": d2}
        paths.update({a: base / ("%s_%d" % (a, s)) / "root" / "data" for a in ARMS})
        for a, pth in paths.items():
            res[(s, a)] = ex.outcomes(pth, FIRST, LAST, END)
            cls[(s, a)] = by_class(pth)
        bad, binding, groups = cc.room_violations(d2, world)
        diff = cc.recompute_policy(d2, world, mode)
        extra.append("G30 D2 seed %d: %d violations; %d cells differ from the recomputed policy; the room binds in %d of %d pharmacy-class-weeks" % (s, len(bad), len(diff), binding, groups))
        if bad or diff:
            rc = 1
            extra.append("G30 FAILS on D2 seed %d" % s)
        if prev is not None and (prev / ("D_%d" % s) / "data").exists():
            res[(s, "D")] = ex.outcomes(prev / ("D_%d" % s) / "data", FIRST, LAST, END)
    for e in extra:
        print(e)
    claims_t = (("T1", "C2' has at most 1.00 of D2''s stockout cells on critical items", lambda s: cls[(s, "C")]["critical"] / cls[(s, "D2")]["critical"], 1.00),
                ("T2", "C2' has at most 1.00 of D2''s stockout cells", lambda s: cls[(s, "C")]["all"] / cls[(s, "D2")]["all"], 1.00),
                ("T3", "C2' has at most 1.00 of D2''s lapses", lambda s: res[(s, "C")]["lapses"] / res[(s, "D2")]["lapses"], 1.00),
                ("T4", "T2' has at most 0.90 of D2''s lapses", lambda s: res[(s, "T")]["lapses"] / res[(s, "D2")]["lapses"], 0.90),
                ("T5", "C2' orders at most 1.10 of D2''s units", lambda s: res[(s, "C")]["orders_units"] / res[(s, "D2")]["orders_units"], 1.10))
    claims = (("S1", "C2 has at most %.2f of D2's stockout cells on critical items" % S1, lambda s: cls[(s, "C")]["critical"] / cls[(s, "D2")]["critical"], S1),
              ("S2", "C2 has at most %.2f of D2's stockout cells" % S2, lambda s: cls[(s, "C")]["all"] / cls[(s, "D2")]["all"], S2),
              ("S3", "T2 has at most %.2f of D2's lapses" % S3, lambda s: res[(s, "T")]["lapses"] / res[(s, "D2")]["lapses"], S3),
              ("S4", "B2 has at most %.2f of D2's lapses" % S4, lambda s: res[(s, "B")]["lapses"] / res[(s, "D2")]["lapses"], S4))
    bad_claims = 0
    for cid, text, f, lim in (claims_t if mode == 2 else claims):
        vals = [f(s) for s in seeds]
        holds = all(v <= lim for v in vals)
        print("CLAIM %s (%s): %s -> %s" % (cid, text, "; ".join("seed %d: %.3f" % (s, v) for s, v in zip(seeds, vals)), "holds on every seed" if holds else "FAILS"))
        bad_claims += 0 if holds else 1
    for s in seeds:
        for a in (("D",) if (s, "D") in res else ()) + ("D2",) + ARMS:
            o, c = res[(s, a)], cls.get((s, a))
            print("seed %d arm %s: orders %d units (weeks %d-%d), stockout cells %d (critical %s, cold-chain %s), units short %d, written off %d, events %d, lapses %d (weeks %d-%d)" % (
                s, a if a in ("D", "D2") else a + "2", o["orders_units"], FIRST, LAST, o["stockout_cells"], c["critical"] if c else "-", c["cold"] if c else "-", o["units_short"], o["written_off"], o["events"], o["lapses"], FIRST + 1, END))
    print("experiment_cap: gates %s, %d of %d claims fail" % ("hold" if rc == 0 else "FAIL", bad_claims, 5 if mode == 2 else 4))
    return 0 if rc == 0 and bad_claims == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
