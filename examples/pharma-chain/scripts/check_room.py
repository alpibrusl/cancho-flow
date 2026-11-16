#!/usr/bin/env python3
"""G27 of U9 (docs/use-cases.md section 7a) and the mutants of the builder's `--no-room` and of the HiGHS oracle.

    CANCHO... SOLVE=<solve> SCIPY_PYTHON=<python with scipy> python3 scripts/check_room.py DATA_DIR REFERENCE_BUILDER [--mutants [name ...]]

DATA_DIR is the large twin's tables (check_lapse.py's fixture: week 95, pharmacy P001); REFERENCE_BUILDER is `build_models.py` as of U8 (`git show 531dc85:examples/pharma-chain/build_models.py`).
G27a: without the flag the builder writes what the reference writes, byte for byte. G27b: with `--no-room` the model text is the text without it less exactly the lines `coldroom:` and `shelfroom:`, and the .json is the same plus
`"no_room": true`. G27c: HiGHS (the oracle, which reads the data) equals `solve` on the plan of the model without rooms; with the room rows applied it must not (the fixture's cold room is zero). Standard library only here;
`solve` and scipy are needed for G27c, which is reported as not run without them.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import check_lapse as cl  # noqa: E402

BUILDER = os.path.join(HERE, "build_models.py")
ORACLE = os.path.join(HERE, "scripts", "oracle_highs.py")
ROOM = ("    coldroom:", "    shelfroom:")

MUTANTS = {
    "rooms-kept": (BUILDER, [('if cold and not d.get("no_room"):', "if cold:"), ('if warm and not d.get("no_room"):', "if warm:")]),
    "cold-room-removed-only": (BUILDER, [('if warm and not d.get("no_room"):', "if warm:")]),
    "shelf-room-removed-only": (BUILDER, [('if cold and not d.get("no_room"):', "if cold:")]),
    "no-room-not-written": (BUILDER, [('d["no_room"] = True', "pass")]),
    "oracle-applies-the-rows": (ORACLE, [('(() if d.get("no_room") else ((1, d["room_cold"]), (0, d["room_shelf"])))', '((1, d["room_cold"]), (0, d["room_shelf"]))')]),
}


def solve_bin():
    p = os.environ.get("SOLVE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "cancho-solve", "build", "solve")
    return p if os.path.isfile(p) else None


def run_builder(builder, data, tmp, name, extra):
    out = os.path.join(tmp, name)
    cmd = [sys.executable, builder, "--only", "%d:P001" % cl.WEEK] + extra + [data, os.path.join(tmp, "test.csv"), os.path.join(tmp, "pred.json"), os.path.join(tmp, "costs.json"), out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-200:]
    base = os.path.join(out, "models", "W%d_P001" % cl.WEEK)
    return (open(base + ".sol").read(), json.load(open(base + ".json")), base), ""


def gates(builder, oracle, data, ref, tmp):
    problems, notes = [], []
    plain, e = run_builder(ref, data, tmp, "ref", [])
    mine, e2 = run_builder(builder, data, tmp, "mine", [])
    nr, e3 = run_builder(builder, data, tmp, "noroom", ["--no-room"])
    if not (plain and mine and nr):
        return ["G27: a builder did not run: %s %s %s" % (e, e2, e3)], notes
    if plain[0] != mine[0] or plain[1] != mine[1]:
        problems.append("G27a: without the flag the builder is not the reference")
    sol_plain = plain[0].split("\n")
    if not all(any(l.startswith(r) for l in sol_plain) for r in ROOM):
        problems.append("G27: the fixture has no cold or no shelf room row: the gate is not exercised")
    want = [l for l in sol_plain if not l.startswith(ROOM)]
    d_want = dict(plain[1], no_room=True)
    if nr[0].split("\n") != want or nr[1] != d_want:
        problems.append("G27b: with --no-room the model is not the model less exactly the two room rows (and the data plus no_room)")
    # G27c
    sv, py = solve_bin(), os.environ.get("SCIPY_PYTHON")
    if not sv or not py:
        notes.append("G27c not run (no solve binary or no SCIPY_PYTHON)")
        return problems, notes
    if plain[1]["room_cold"] != 0:
        problems.append("G27c: the fixture's cold room is not zero: the oracle with the rows would not differ")
    mdir = os.path.join(tmp, "noroom")
    r = subprocess.run([sv, "run", "--node-limit", "20000"], stdin=open(nr[2] + ".sol"), capture_output=True, text=True)
    if r.stdout.strip() == "":
        problems.append("G27c: solve printed nothing")
        return problems, notes
    open(nr[2] + ".plan.json", "w").write(r.stdout)
    o = subprocess.run([py, oracle, mdir], capture_output=True, text=True)
    try:
        ok = json.loads(o.stdout.strip().splitlines()[-1]).get("ok")
    except (ValueError, IndexError):
        ok = False
    if not ok:
        problems.append("G27c: HiGHS and solve disagree on the plan of the model without rooms: %s" % o.stdout[-150:])
    return problems, notes


def main(argv):
    if len(argv) < 2 or argv[0].startswith("--"):
        sys.stderr.write("check_room.py DATA_DIR REFERENCE_BUILDER [--mutants [name ...]]\n")
        return 2
    data, ref = argv[0], os.path.abspath(argv[1])
    tmp = tempfile.mkdtemp(prefix="check_room_")
    cl.fixture(data, tmp)
    problems, notes = gates(BUILDER, ORACLE, data, ref, tmp)
    print("G27 on the committed builder and oracle: %s%s" % ("hold" if not problems else "FAIL: " + "; ".join(problems), ("  [" + "; ".join(notes) + "]") if notes else ""))
    if problems:
        return 1
    if "--mutants" in argv:
        names = argv[argv.index("--mutants") + 1:] or list(MUTANTS)
        survived = 0
        for n in names:
            target, edits = MUTANTS[n]
            text = open(target).read()
            for old, new in edits:
                if text.count(old) != 1:
                    print("%s: its text occurs %d times in %s" % (n, text.count(old), os.path.basename(target)))
                    return 2
                text = text.replace(old, new)
            mdir = os.path.join(tmp, "mut_" + n)
            os.makedirs(mdir)
            mp = os.path.join(mdir, os.path.basename(target))
            open(mp, "w").write(text)
            mp_problems, mnotes = gates(mp if target == BUILDER else BUILDER, mp if target == ORACLE else ORACLE, data, ref, tmp)
            if mnotes and not mp_problems:
                print("%s: NOT JUDGED (%s)" % (n, "; ".join(mnotes)))
                survived += 1
                continue
            print("%s: %s" % (n, "killed by " + mp_problems[0][:120] if mp_problems else "SURVIVED"))
            survived += 0 if mp_problems else 1
        print("check_room: %d of %d mutants killed" % (len(names) - survived, len(names)))
        return 1 if survived else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
