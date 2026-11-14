#!/usr/bin/env python3
"""The plans of a week as a decisions file (docs/use-cases.md section 7a, U7b).

    python3 plan_decisions.py c WEEK ROOT OUT          # orders from ROOT/c/models/W<WEEK+1>_P*.json and their plans: {"orders": [...]}
    python3 plan_decisions.py b WEEK ROOT OUT          # outreach from ROOT/b/models/W<WEEK+1>_P*.json and their plans: {"outreach": [...]}
    python3 plan_decisions.py merge WEEK OUT PART...   # week-<WEEK>.json from the parts that exist

WEEK is the week at whose end the decisions are made; the plans are for WEEK+1. An order is the plan's packs times the pack size, for every pharmacy and item the plan covers (an order of zero is a decision); an outreach is
the action the plan gives an event, left out when it gives none. Entries are sorted, so the same plans give the same bytes. Only the standard library.
"""
import glob
import json
import os
import sys

sys.dont_write_bytecode = True
KINDS = (("call", "xc"), ("reminder", "xr"), ("switch90", "xs"), ("delivery", "xd"))


def dump(path, doc):
    with open(path, "w", newline="\n") as f:
        f.write(json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n")


def plans(root, kind, week):
    for jf in sorted(glob.glob(os.path.join(root, kind, "models", "W%d_P*.json" % (week + 1)))):
        if jf.endswith(".plan.json") or jf.endswith(".verify.json"):
            continue
        yield json.load(open(jf)), json.load(open(jf[:-5] + ".plan.json"))


def orders(week, root, out):
    res = []
    for d, plan in plans(root, "c", week):
        for i, item in enumerate(d["items"]):
            res.append({"pharmacy": d["pharmacy"], "item": item, "units": d["pack"][i] * int(round(plan["x"]["q[%d]" % i]))})
    res.sort(key=lambda e: (e["pharmacy"], e["item"]))
    dump(out, {"orders": res})


def outreach(week, root, out):
    res = []
    for d, plan in plans(root, "b", week):
        for e, name in enumerate(d["events"]):
            patient, item = name.split("/")
            for action, key in KINDS:
                if plan["x"]["%s[%d]" % (key, e)] > 0.5:
                    res.append({"patient": patient, "item": item, "action": action})
    res.sort(key=lambda e: (e["patient"], e["item"]))
    dump(out, {"outreach": res})


def merge(week, out, parts):
    doc = {"week": week}
    for p in parts:
        doc.update(json.load(open(p)))
    dump(out, doc)


def main(argv):
    try:
        k = argv[0]
        if k == "c" and len(argv) == 4:
            orders(int(argv[1]), argv[2], argv[3])
        elif k == "b" and len(argv) == 4:
            outreach(int(argv[1]), argv[2], argv[3])
        elif k == "merge" and len(argv) >= 3:
            merge(int(argv[1]), argv[2], argv[3:])
        else:
            raise IndexError
    except (IndexError, ValueError, OSError, KeyError):
        sys.stderr.write('{"ok":false,"error":{"rule":"decisions.usage","message":"see the docstring of plan_decisions.py","repair":"give a kind and its operands"}}\n')
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
