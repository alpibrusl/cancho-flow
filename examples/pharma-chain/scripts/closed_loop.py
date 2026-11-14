#!/usr/bin/env python3
"""U7b: one arm of the closed loop (docs/use-cases.md section 7a, margins G21 to G23 and the claims, committed before this was written).

    CANCHO=<compiler> python3 scripts/closed_loop.py --arm C|B|T --seed N --out DIR [--first 90 --last 101 --end 103]

The stepping twin (U7a) runs from week 0 through each decision week with the decisions made so far; the tools read what it wrote and decide for the week after: C, the replenishment orders (a boost fitted once on weeks 38 to 89,
the 20 plans in `solve`), B, the outreach (a boost fitted once on events due before week 64, isotonic calibration on weeks 64 to 89, the 20 plans in `solve`); their plans become `decisions/week-<W>.json`. Arm C does
C only, arm B does B only, arm T both. The last step runs the twin through week END with every decision. Every step is a recorded `flow` step; DIR/root holds the files, DIR/root/rec the records.
"""
import csv
import json
import os
import pathlib
import shutil
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scripts"))
import pipeline_a as pa  # noqa: E402
import pipeline_b as pb  # noqa: E402
import pipeline_c as pc  # noqa: E402

FULL = "core,dispensing,refills,delivery,coupled"
OUTS = ["items.csv", "pharmacies.csv", "patients.csv", "truth.json", "dispensing.csv", "truth/demand.csv", "refills.csv", "truth/refill_hazard.csv", "trucks.csv", "locations.csv", "days.csv", "deliveries.csv",
        "routes.csv", "telemetry.csv", "depot.csv", "truth/energy_parts.csv", "truth/excursion.csv", "truth/coupling.csv"]
TWINX = pa.TWIN + ["twinlib/step.py", "twinlib/decisions.py"]
HELPERS = ("features_b.py", "features_next.py", "events_next.py", "pred_join.py", "apply_isotonic.py", "build_models.py", "build_outreach.py", "verify_input.py", "plan_decisions.py", "costs.json", "outreach.json")
TB = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]
NODE_LIMIT = "20000"
C_FIT_FROM, B_FIT_BEFORE = 38, 64     # fitted once, on what is known through week 89 (the week before the first decision)
FIT_THROUGH = 89
STOCK_WINDOW = 4                      # the stockout window of the lapse feature, in weeks (the twin's `stockout_window_weeks`)


def solve_chain(fl, base):
    fl.step([base + ".sol"], [], ["solve", "run", "--node-limit", NODE_LIMIT], stdin_file=base + ".sol", stdout_file=base + ".plan.json", allow_failure=True)
    fl.step(["verify_input.py", base + ".sol", base + ".plan.json"], [base + ".verify.in"], ["python3", "verify_input.py", base + ".sol", base + ".plan.json", base + ".verify.in"])
    fl.step([], [], ["solve", "verify"], stdin_file=base + ".verify.in", stdout_file=base + ".verify.json")


def twin_step(fl, seed, through, decided):
    ins = TWINX + ["world_main.json"] + ["decisions/week-%d.json" % w for w in decided]
    fl.step(ins, ["data/" + f for f in OUTS], ["python3", "twin.py", "generate", "--world", "world_main.json", "--seed", str(seed), "--size", "large", "--tables", FULL, "--through", str(through),
                                                "--decisions", "decisions", "--out", "data", "--overwrite"])
    mx = max(int(r["week"]) for r in pc.table(fl.read("data/dispensing.csv")))
    if mx != through:  # a guard of the loop, not a gate: the tools must read the world through the decision week and no further
        sys.exit("closed_loop: the twin ran through week %d, not %d" % (mx, through))


def prep(fl, seed, arm):
    """The models, fitted once on the world through week 89."""
    pa.world(fl, "main", None)
    twin_step(fl, seed, FIT_THROUGH, [])
    if arm in ("C", "T"):
        fl.step(["features.py", "data/dispensing.csv", "data/items.csv", "data/pharmacies.csv"], ["c_feat.csv"], ["python3", "features.py", "data", "c_feat.csv"])
        fl.step(["c_feat.csv"], ["c_train.csv"], TB + ["c_train.csv", "--where", "week:int >= %d and week:int <= %d" % (C_FIT_FROM, FIT_THROUGH), "c_feat.csv"])
        fl.step(["c_train.csv"], ["c_model.ml"], ["ml", "--root", ".", "--model", "boost", "--cat", "group,season", "--step", "encode column=group,season kind=onehot", "--target", "units", "--drop", "pharmacy,item,week",
                                                   "--output", "c_model.ml", "fit", "c_train.csv"], stdout_file="c_fit.json")
    if arm in ("B", "T"):
        fl.step(["features_b.py", "data/refills.csv", "data/patients.csv"], ["b_events.csv"], ["python3", "features_b.py", "data", "b_events.csv"])
        fl.step(["b_events.csv"], ["b_fit.csv"], TB + ["b_fit.csv", "--where", "due_week:int < %d" % B_FIT_BEFORE, "b_events.csv"])
        fl.step(["b_events.csv"], ["b_cal.csv"], TB + ["b_cal.csv", "--where", "due_week:int >= %d and due_week:int <= %d" % (B_FIT_BEFORE, FIT_THROUGH), "b_events.csv"])
        fl.step(["b_fit.csv"], ["b_model.ml"], ["ml", "--root", ".", "--model", "boost", "--task", "classification", "--positive", "1", "--target", "lapsed", "--drop", pb.DROP, "--output", "b_model.ml", "fit", "b_fit.csv"],
                stdout_file="b_fit.json")
        fl.step(["b_model.ml", "b_cal.csv"], [], ["ml", "--root", ".", "--model-file", "b_model.ml", "--drop", pb.DROP, "--proba", "--limit", "1000000", "predict", "b_cal.csv"], stdout_file="b_pred_cal.json", max_output=33554432)
        fl.step(["pred_join.py", "b_cal.csv", "b_pred_cal.json"], ["b_pred_cal.csv"], ["python3", "pred_join.py", "b_cal.csv", "b_pred_cal.json", "b_pred_cal.csv"])
        fl.step(["b_pred_cal.csv"], [], ["ml", "--root", ".", "--x-col", "p", "--y-col", "lapsed", "isotonic", "b_pred_cal.csv"], stdout_file="b_iso.json")


def decide_c(fl, w):
    """The replenishment plans for week w+1, from the world through week w."""
    fl.step(["features_next.py", "data/dispensing.csv", "data/items.csv", "data/pharmacies.csv"], ["c_next.csv"], ["python3", "features_next.py", "data", "c_next.csv"])
    fl.step(["c_model.ml", "c_next.csv"], [], ["ml", "--root", ".", "--model-file", "c_model.ml", "--drop", "pharmacy,item,week", "--limit", "6000", "predict", "c_next.csv"], stdout_file="c_pred.json")
    phs = sorted({r["pharmacy"] for r in pc.table(fl.read("c_next.csv"))})
    for ph in phs:
        b = "c/models/W%d_%s" % (w + 1, ph)
        fl.step(["build_models.py", "data/dispensing.csv", "data/items.csv", "data/pharmacies.csv", "c_next.csv", "c_pred.json", "costs.json"], [b + ".sol", b + ".json"],
                ["python3", "build_models.py", "--only", "%d:%s" % (w + 1, ph), "data", "c_next.csv", "c_pred.json", "costs.json", "c"])
        solve_chain(fl, b)
    fl.step(["plan_decisions.py"] + ["c/models/W%d_%s.%s" % (w + 1, ph, e) for ph in phs for e in ("json", "plan.json")], ["c_dec.json"], ["python3", "plan_decisions.py", "c", str(w), ".", "c_dec.json"])


def decide_b(fl, w):
    """The outreach plans for week w+1, from the world through week w."""
    fl.step(["events_next.py", "data/refills.csv", "data/patients.csv", "data/dispensing.csv"], ["b_next.csv"], ["python3", "events_next.py", "data", str(w + 1), str(STOCK_WINDOW), "b_next.csv"])
    fl.step(["b_model.ml", "b_next.csv"], [], ["ml", "--root", ".", "--model-file", "b_model.ml", "--drop", pb.DROP, "--proba", "--limit", "1000000", "predict", "b_next.csv"], stdout_file="b_pred.json", max_output=33554432)
    fl.step(["pred_join.py", "b_next.csv", "b_pred.json"], ["b_pred.csv"], ["python3", "pred_join.py", "b_next.csv", "b_pred.json", "b_pred.csv"])
    fl.step(["apply_isotonic.py", "b_iso.json", "b_pred.csv"], ["b_next_cal.csv"], ["python3", "apply_isotonic.py", "b_iso.json", "b_pred.csv", "b_next_cal.csv"])
    home = {r["patient"]: r["home_pharmacy"] for r in pc.table(fl.read("data/patients.csv"))}
    phs = sorted({home[r["patient"]] for r in pc.table(fl.read("b_next_cal.csv"))})
    for ph in phs:
        b = "b/models/W%d_%s" % (w + 1, ph)
        fl.step(["build_outreach.py", "b_next_cal.csv", "data/patients.csv", "outreach.json"], [b + ".sol", b + ".json"], ["python3", "build_outreach.py", "--only", "%d:%s" % (w + 1, ph), "b_next_cal.csv", "data", "outreach.json", "b"])
        solve_chain(fl, b)
    fl.step(["plan_decisions.py"] + ["b/models/W%d_%s.%s" % (w + 1, ph, e) for ph in phs for e in ("json", "plan.json")], ["b_dec.json"], ["python3", "plan_decisions.py", "b", str(w), ".", "b_dec.json"])


def run_arm(arm, seed, out, first=90, last=101, end=103):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fl = pc.Flow(out)
    for f in HELPERS:
        shutil.copy2(HERE / f, fl.root / f)
    shutil.copy(HERE / "features.py", fl.root / "features.py")
    for f in ("step.py", "decisions.py", "delivery.py"):
        shutil.copy(HERE / "twinlib" / f, fl.root / "twinlib" / f)
    (fl.root / "decisions").mkdir()
    prep(fl, seed, arm)
    decided = []
    for w in range(first, last + 1):
        twin_step(fl, seed, w, decided)
        parts = []
        if arm in ("C", "T"):
            decide_c(fl, w)
            parts.append("c_dec.json")
        if arm in ("B", "T"):
            decide_b(fl, w)
            parts.append("b_dec.json")
        fl.step(["plan_decisions.py"] + parts, ["decisions/week-%d.json" % w], ["python3", "plan_decisions.py", "merge", str(w), "decisions/week-%d.json" % w] + parts)
        decided.append(w)
    twin_step(fl, seed, end, decided)
    (out / "arm.json").write_text(json.dumps({"arm": arm, "seed": seed, "first": first, "last": last, "end": end, "steps": fl.steps, "ms": fl.ms}, sort_keys=True))
    return fl


def main(argv):
    def arg(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    arm, seed, out = arg("--arm"), arg("--seed"), arg("--out")
    if arm not in ("C", "B", "T") or not seed or not out:
        sys.stderr.write("closed_loop.py --arm C|B|T --seed N --out DIR [--first 90 --last 101 --end 103]\n")
        return 2
    run_arm(arm, int(seed), out, int(arg("--first", 90)), int(arg("--last", 101)), int(arg("--end", 103)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
