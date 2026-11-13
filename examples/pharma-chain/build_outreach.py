#!/usr/bin/env python3
"""The outreach decision as a model for `solve` (docs/use-cases.md section 4.3, step 4).

    python3 build_outreach.py [--only WEEK:PHARMACY] [--true-p] TEST_CAL.csv DATA_DIR OUTREACH.json OUT_DIR

For every pharmacy and test week it writes OUT_DIR/models/W<week>_<pharmacy>.sol (the model for `solve`) and .json (the same numbers as data, which the oracles read: they never parse
the model text). The events are the refills due that week at the patients' home pharmacy; the probability is the calibrated `p` of the file. It reads patients.csv (what the pharmacy
knows) and never truth/ -- except with --true-p, which swaps in the twin's true probability (DATA_DIR/truth/refill_hazard.csv) to make the *oracle plan* that G9 compares against.

    maximize  sum_e days_e * p_e * ( u_call xc_e + u_rem xr_e + u_sw xs_e + u_del xd_e )
    xc_e + xr_e + xs_e + xd_e <= 1                                   at most one outreach for an event
    sum_e ( m_call xc_e + m_rem xr_e + m_sw xs_e + m_del xd_e )  <= minutes
    sum_e ( c_call xc_e + ... )                                  <= money
    sum_e xd_e                                                   <= delivery slots
"""
import csv
import json
import os
import sys

sys.dont_write_bytecode = True
ACTIONS = ("call", "reminder", "switch90", "delivery")


def num(x):
    return ("%.9f" % x).rstrip("0").rstrip(".") or "0"


def arr(xs):
    return "[" + ", ".join(num(x) for x in xs) + "]"


def instance(events, cfg):
    """events: list of (days, p). The data of one decision."""
    return {"n": len(events), "days": [d for d, _ in events], "p": [p for _, p in events],
            "uplift": [cfg["uplift"][a] for a in ACTIONS], "minutes": [cfg["minutes"][a] for a in ACTIONS], "money": [cfg["money"][a] for a in ACTIONS],
            "cap_minutes": cfg["capacity_per_pharmacy_week"]["minutes"], "cap_money": cfg["capacity_per_pharmacy_week"]["money"],
            "cap_slots": cfg["capacity_per_pharmacy_week"]["delivery_slots"]}


def model_text(d):
    n = d["n"]
    g = [[d["days"][e] * d["p"][e] * d["uplift"][k] for e in range(n)] for k in range(4)]
    t = "param n = %d;\n" % n
    for k, a in enumerate(("gc", "gr", "gs", "gd")):
        t += "param %s = %s;\n" % (a, arr(g[k]))
    for a in ("xc", "xr", "xs", "xd"):
        t += "var %s[0..n] : int 0..1;\n" % a
    t += "maximize gain: sum e in 0..n: (gc[e] * xc[e] + gr[e] * xr[e] + gs[e] * xs[e] + gd[e] * xd[e]);\nsubject to\n"
    t += "    forall e in 0..n: one: xc[e] + xr[e] + xs[e] + xd[e] <= 1;\n"
    t += "    minutes: sum e in 0..n: (%s * xc[e] + %s * xr[e] + %s * xs[e] + %s * xd[e]) <= %s;\n" % (*[num(m) for m in d["minutes"]], num(d["cap_minutes"]))
    t += "    money: sum e in 0..n: (%s * xc[e] + %s * xr[e] + %s * xs[e] + %s * xd[e]) <= %s;\n" % (*[num(m) for m in d["money"]], num(d["cap_money"]))
    t += "    slots: sum e in 0..n: xd[e] <= %d;\n" % d["cap_slots"]
    return t


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main(argv):
    only, true_p = None, False
    while argv and argv[0] in ("--only", "--true-p"):
        if argv[0] == "--only" and len(argv) >= 2:
            only, argv = argv[1], argv[2:]
        elif argv[0] == "--true-p":
            true_p, argv = True, argv[1:]
        else:
            break
    if len(argv) != 4:
        sys.stderr.write('{"ok":false,"error":{"rule":"outreach.usage","message":"build_outreach.py [--only W:P] [--true-p] TEST_CAL.csv DATA_DIR OUTREACH.json OUT_DIR","repair":"give the four operands"}}\n')
        return 2
    test, data, cfg_path, out = argv
    cfg = json.load(open(cfg_path))
    home = {r["patient"]: (r["home_pharmacy"], int(r["refill_interval_days"])) for r in read(os.path.join(data, "patients.csv"))}
    tp = {}
    if true_p:
        tp = {(r["patient"], r["item"], int(r["due_week"])): int(r["true_lapse_ppm"]) / 1e6 for r in read(os.path.join(data, "truth", "refill_hazard.csv"))}
    cells = {}
    for r in read(test):
        ph, days = home[r["patient"]]
        w = int(r["due_week"])
        p = tp[(r["patient"], r["item"], w)] if true_p else float(r["p"])
        cells.setdefault((w, ph), []).append(((r["patient"], r["item"]), days, p))
    if only is not None and not any(only == "%d:%s" % k for k in cells):
        sys.stderr.write('{"ok":false,"error":{"rule":"outreach.no-such-cell","message":"no cell %s in the test file","repair":"use --only WEEK:PHARMACY of a test week"}}\n' % only)
        return 2
    os.makedirs(os.path.join(out, "models"), exist_ok=True)
    index = ["week,pharmacy,events"]
    for (w, ph), ev in sorted(cells.items()):
        if only is not None and only != "%d:%s" % (w, ph):
            continue
        d = instance([(days, p) for _, days, p in ev], cfg)
        d["week"], d["pharmacy"], d["events"] = w, ph, ["%s/%s" % k for k, _, _ in ev]
        base = os.path.join(out, "models", "W%d_%s" % (w, ph))
        with open(base + ".sol", "w", newline="\n") as f:
            f.write(model_text(d))
        with open(base + ".json", "w", newline="\n") as f:
            f.write(json.dumps(d, sort_keys=True, separators=(",", ":")) + "\n")
        index.append("%d,%s,%d" % (w, ph, len(ev)))
    if only is None:
        with open(os.path.join(out, "models", "index.csv"), "w", newline="\n") as f:
            f.write("\n".join(index) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
