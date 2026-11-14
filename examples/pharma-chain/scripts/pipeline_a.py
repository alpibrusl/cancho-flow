#!/usr/bin/env python3
"""U4a: the delivery twin run as recorded `flow` steps, and G2 for A and G7 (docs/use-cases.md, margins of 7a for U4a, committed before the delivery tables were written).

    CANCHO=<compiler> python3 scripts/pipeline_a.py [--mutants] [--mutant NAME] [--keep DIR]

The large size. The twin as it is and three controls (the refrigeration-temperature fraction zero; the door term of the excursion zero; its temperature term zero); `table` and `stats` look:
  energy per minute on days at or above 25 degrees against days at or below 15 (`stats test t2`), and the excursion against the door-open band and against the temperature band (`stats test chisq`).
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import pipeline_c as pc  # noqa: E402

# --- the margins of docs/use-cases.md section 7a (G2 for A), fixed before the delivery tables were written ---
G2_P_FOUND = 1e-6
G2_P_ABSENT = 1e-3
SEED = 20261112
DEL_FILES = ["trucks.csv", "locations.csv", "days.csv", "deliveries.csv", "routes.csv", "telemetry.csv", "depot.csv", "truth.json", "truth/energy_parts.csv", "truth/excursion.csv", "items.csv", "pharmacies.csv", "patients.csv"]
TWIN = pc.TWIN_FILES + ["twinlib/delivery.py"]
# (tag, the parameter set to zero in the world file)
WORLDS = (("main", None), ("fridge0", "fridge_temp_ppm"), ("door0", "excursion_per_door_min_ppm"), ("temp0", "excursion_per_10c_ppm"))


def world(fl, tag, zero):
    w = json.loads((HERE / "world.json").read_text())
    if zero:
        w["params"][zero]["value"] = 0
    (fl.root / ("world_%s.json" % tag)).write_text(json.dumps(w))


def run_steps(fl):
    tb = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]
    for tag, zero in WORLDS:
        world(fl, tag, zero)
        d = "data_" + tag
        fl.step(TWIN + ["world_%s.json" % tag], ["%s/%s" % (d, f) for f in DEL_FILES],
                ["python3", "twin.py", "generate", "--world", "world_%s.json" % tag, "--seed", str(SEED), "--size", "large", "--tables", "core,delivery", "--out", d])
        fl.step(["features_a.py", d + "/routes.csv", d + "/telemetry.csv", d + "/days.csv"], ["stops_%s.csv" % tag], ["python3", "features_a.py", d, "stops_%s.csv" % tag])
    for tag in ("main", "fridge0"):
        fl.step(["stops_%s.csv" % tag], ["tempgroups_%s.csv" % tag], tb + ["tempgroups_%s.csv" % tag, "--where", "temp_band != 'mild'", "stops_%s.csv" % tag])
        fl.step(["tempgroups_%s.csv" % tag], [], ["stats", "--root", ".", "test", "t2", "--cols", "wh_per_min", "--group", "temp_band", "tempgroups_%s.csv" % tag], stdout_file="t2_%s.json" % tag)
        fl.step(["tempgroups_%s.csv" % tag], [], ["stats", "--root", ".", "describe", "--cols", "wh_per_min", "--by", "temp_band", "tempgroups_%s.csv" % tag], stdout_file="describe_%s.json" % tag)
    for tag in ("main", "door0", "temp0"):
        fl.step(["stops_%s.csv" % tag], [], ["stats", "--root", ".", "test", "chisq", "--cols", "excursion", "--vs", "door_band", "stops_%s.csv" % tag], stdout_file="chisq_door_%s.json" % tag)
        fl.step(["stops_%s.csv" % tag], [], ["stats", "--root", ".", "test", "chisq", "--cols", "excursion", "--vs", "temp_band", "stops_%s.csv" % tag], stdout_file="chisq_temp_%s.json" % tag)


def judge(fl):
    problems, report = [], []
    J = lambda rel: json.loads(fl.read(rel))
    t = J("t2_main.json")["data"]
    lv = t["levels"]
    p_main = t["tests"][0]["p_value"]
    diff = -t["tests"][0]["interval"]["estimate"] if lv == {"a": "cool", "b": "hot"} else None
    means = {g["value"]: float(g["columns"][0]["mean"]) for g in J("describe_main.json")["data"]["groups"]}
    pz = J("t2_fridge0.json")["data"]["tests"][0]["p_value"]
    report.append("G2 energy per minute, hot (at or above 25) against cool (at or below 15) days: p = %.2e, hot minus cool = %s (means hot %.2f, cool %.2f Wh per minute); control with the refrigeration-temperature fraction zero: p = %.3f" % (
        p_main, ("%.2f" % diff) if diff is not None else "?", means.get("hot", float("nan")), means.get("cool", float("nan")), pz))
    if lv != {"a": "cool", "b": "hot"}:
        problems.append("G2: the groups of the t2 are %s, not cool and hot" % lv)
    elif not (p_main < G2_P_FOUND and diff > 0):
        problems.append("G2: the refrigeration effect on the energy per minute was not found (p = %.2e, hot minus cool = %.2f, wanted p < %g and positive)" % (p_main, diff, G2_P_FOUND))
    if not pz >= G2_P_ABSENT:
        problems.append("G2: an effect of the temperature on the energy per minute was found in the control where there is none (p = %.2e, wanted >= %g)" % (pz, G2_P_ABSENT))
    for name, ctl in (("door", "door0"), ("temp", "temp0")):
        pm = J("chisq_%s_main.json" % name)["data"]["tests"][0]["p_value"]
        pc_ = J("chisq_%s_%s.json" % (name, ctl))["data"]["tests"][0]["p_value"]
        report.append("G2 excursion against the %s band: p = %.2e in the twin, %.3f in the control with that term zero" % (name, pm, pc_))
        if not pm < G2_P_FOUND:
            problems.append("G2: the effect of the %s band on the excursion was not found (p = %.2e, wanted < %g)" % (name, pm, G2_P_FOUND))
        if not pc_ >= G2_P_ABSENT:
            problems.append("G2: an effect of the %s band on the excursion was found in the control where there is none (p = %.2e, wanted >= %g)" % (name, pc_, G2_P_ABSENT))
    # the twin's counts, for the record
    tj = json.loads(fl.read("data_main/truth.json"))["delivery_realised"]
    report.append("twin (large): %d deliveries in %d routes, %d excursions, %d late stops, %d routes beyond their battery" % (tj["deliveries"], tj["routes"], tj["excursions"], tj["late_stops"], tj["energy_violations"]))
    p7, r7 = pc.judge_records(fl, "stops_main.csv")
    return problems + p7, report + r7


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = pc.Flow(td)
        shutil.copy(HERE / "features_a.py", fl.root / "features_a.py")
        shutil.copy(HERE / "twinlib" / "delivery.py", fl.root / "twinlib" / "delivery.py")
        run_steps(fl)
        out = judge(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return out


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    ("twin-ignores-the-temperature-in-the-fridge", "twinlib/delivery.py", _x('fridge_wh = p["fridge_w"] * elapsed * ', 'fridge_ppm // (1_000_000 * 60)'), 'fridge_wh = p["fridge_w"] * elapsed * 1_000_000 // (1_000_000 * 60)', "G2"),
    ("twin-ignores-the-doors-in-the-excursion", "twinlib/delivery.py", _x('p["excursion_base_ppm"] + p["excursion_per_door_min_ppm"] * door', ' + p'), 'p["excursion_base_ppm"] + p', "G2"),
    ("twin-ignores-the-heat-in-the-excursion", "twinlib/delivery.py", _x('prob = min(1_000_000, p["excursion_base_ppm"] + p["excursion_per_door_min_ppm"] * door + p["excursion_per_10c_ppm"] * ', 'max(0, T - 20) // 10)'), 'prob = min(1_000_000, p["excursion_base_ppm"] + p["excursion_per_door_min_ppm"] * door + 0 * ', "G2"),
    ("control-not-zeroed", "scripts/pipeline_a.py", _x('(("fridge0", "fridge_temp', '_ppm"),'), '(("fridge0", "noise_ppm"),', "G2"),
    ("wrong-column-for-the-temperature-band", "scripts/pipeline_a.py", _x('"--cols", "excursion", "--vs", "temp', '_band", "stops_%s.csv" % tag]'), '"--cols", "excursion", "--vs", "door_band", "stops_%s.csv" % tag]', "G2"),
]


def mutants(only=None):
    if only is None:
        problems, report = run()
        for ln in report:
            print(ln)
        if problems:
            print("control FAILED:")
            for p in problems:
                print("  " + p)
            return 1
        print("control passes")
    survived = 0
    for name, rel, old, new, gate in MUTANTS:
        if only and name != only:
            continue
        with tempfile.TemporaryDirectory() as td:
            tree = pathlib.Path(td) / "pharma-chain"
            shutil.copytree(HERE, tree, ignore=shutil.ignore_patterns("__pycache__"))
            f = tree / rel
            text = f.read_text()
            if text.count(old) != 1:
                print("mutant %-44s CANNOT BE APPLIED (%d occurrences in %s)" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            env = dict(os.environ, FLOW_REPO=str(pc.REPO), TABLE=pc.exe("table", "TABLE"), STATS=pc.exe("stats", "STATS"), ML=pc.exe("ml", "ML"), SOLVE=pc.exe("solve", "SOLVE"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "pipeline_a.py")], capture_output=True, text=True, env=env, cwd=td, timeout=3600)
            out = r.stdout + r.stderr
            if only:
                print(out[-2500:])
            hit = [ln for ln in out.splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-44s by %s" % (name, hit[0][:130]))
            else:
                survived += 1
                print("SURVIVED %-44s wanted a %s failure; exit %d, last line %r" % (name, gate, r.returncode, out.strip().splitlines()[-1:]))
    print("%d mutants, %d survived" % (len(MUTANTS), survived))
    return 1 if survived else 0


def main():
    if "--mutant" in sys.argv:
        return mutants(sys.argv[sys.argv.index("--mutant") + 1])
    if "--mutants" in sys.argv:
        return mutants()
    problems, report = run(sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None)
    for ln in report:
        print(ln)
    for p in problems:
        print(p)
    if problems:
        return 1
    print("pipeline_a: ok (G2 and G7 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
