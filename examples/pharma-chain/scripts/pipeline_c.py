#!/usr/bin/env python3
"""U2a: pharmacy forecast pipeline, run as recorded `flow` steps, and the gates G2, G4 and G7 of docs/use-cases.md (section 7 and the margins of 7a).

    CANCHO=<compiler> python3 scripts/pipeline_c.py [--mutants] [--keep DIR]

The programs are the built binaries of the sibling repositories, found next to this repository (../cancho-table/build/table, ../cancho-stats/build/stats,
../cancho-ml/build/ml) or named by TABLE, STATS and ML. `flow` is built here with a programs directory that holds links to them and to python3.

Every stage is one `flow step`; its record is checked at the end (G7). The margins below are the ones of section 7a, written there before the first run.
"""
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent  # examples/pharma-chain
REPO = pathlib.Path(os.environ.get("FLOW_REPO") or HERE.parent.parent)  # cancho-flow
SIB = REPO.parent

# --- the margins of docs/use-cases.md section 7a, fixed before any measurement ---
G2_P_FOUND = 1e-6            # a seasonal effect: p below this
G2_P_ABSENT = 1e-3           # no seasonal effect: p at or above this
G2_RATIO_TOL = 0.25          # winter/summer ratio of means within 25 percent of the parameters' ratio
G4_IMPROVE = 0.90            # model MAE at most this times the smaller baseline MAE
G4_FLOOR = 0.90              # and at least this times the noise floor
HOLDOUT_FROM = 92            # held-out weeks: 92 to 103 (the last 12 of 104)

SEED = 20261112


def exe(name, env):
    p = os.environ.get(env) or str(SIB / ("cancho-" + name) / "build" / name)
    if not os.path.isfile(p):
        sys.exit("pipeline_c: %s is not built (set %s, or build it in ../cancho-%s)" % (p, env, name))
    return p


class Flow:
    def __init__(self, tmp):
        self.tmp = pathlib.Path(tmp)
        prog = self.tmp / "programs"
        prog.mkdir()
        for name, path in (("python3", shutil.which("python3")), ("table", exe("table", "TABLE")), ("stats", exe("stats", "STATS")), ("ml", exe("ml", "ML")), ("solve", exe("solve", "SOLVE"))):
            os.symlink(path, prog / name)
        for b in ("flow", "flow-records"):
            r = subprocess.run([sys.executable, str(REPO / "scripts" / "flow_build.py"), "--programs", str(prog), "--out", str(self.tmp / b), "--bin", b], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit("pipeline_c: building %s failed: %s" % (b, (r.stdout + r.stderr)[-400:]))
        self.flow, self.records = str(self.tmp / "flow"), str(self.tmp / "flow-records")
        self.root = self.tmp / "root"
        (self.root / "rec").mkdir(parents=True)
        shutil.copytree(HERE / "twinlib", self.root / "twinlib", ignore=shutil.ignore_patterns("__pycache__"))
        for f in ("twin.py", "features.py", "world.json"):
            shutil.copy(HERE / f, self.root / f)
        self.steps = 0

    def step(self, ins, outs, argv, stdout_file=None, stdin_file=None, max_output=None):
        outs = list(outs) + ([stdout_file] if stdout_file else [])
        rec = "rec/%d" % (self.steps // 800)  # a record directory holds at most 1000 records: a new one every 800 steps; `flow-records check --recursive` reads them all
        (self.root / rec).mkdir(parents=True, exist_ok=True)
        cmd = [self.flow, "step", "--root", ".", "--record", rec] + (["--in", ",".join(ins)] if ins else []) + (["--out", ",".join(outs)] if outs else [])
        if stdout_file:
            cmd += ["--stdout-file", stdout_file]
        if stdin_file:
            cmd += ["--stdin-file", stdin_file]
        if max_output:
            cmd += ["--max-output", str(max_output)]
        r = subprocess.run(cmd + ["--"] + argv, cwd=self.root, capture_output=True, text=True, timeout=900)
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            sys.exit("pipeline_c: flow printed no JSON for %r: %s" % (argv, r.stderr[-300:]))
        if not doc.get("ok") or doc["data"]["outcome"]["exit"] != 0:
            sys.exit("pipeline_c: step %r failed: %s" % (argv, r.stdout[:600]))
        self.steps += 1
        return doc

    def read(self, rel):
        return (self.root / rel).read_text()


TWIN_FILES = ["twin.py", "twinlib/__init__.py", "twinlib/prng.py", "twinlib/world.py", "twinlib/core.py"]
DATA = ["items.csv", "pharmacies.csv", "patients.csv", "truth.json", "dispensing.csv", "truth/demand.csv"]


def make_world(fl, name, amp_zero):
    w = json.loads((HERE / "world.json").read_text())
    if amp_zero:
        w["params"]["season_amplitude_ppm"]["value"] = [0, 0, 0]
    (fl.root / name).write_text(json.dumps(w))


def forecast(fl, tag, features_py="features.py"):
    """twin -> features -> split -> fits -> evals, every one a flow step. Returns the paths."""
    d = "data_" + tag
    fl.step(TWIN_FILES + ["world_%s.json" % tag], ["%s/%s" % (d, f) for f in DATA], ["python3", "twin.py", "generate", "--world", "world_%s.json" % tag, "--seed", str(SEED), "--size", "small", "--out", d])
    fl.step([features_py, d + "/dispensing.csv", d + "/items.csv", d + "/pharmacies.csv"], ["features_%s.csv" % tag], ["python3", features_py, d, "features_%s.csv" % tag])
    return d


def run_main(fl, features_py="features.py", stats_only=False):
    make_world(fl, "world_main.json", False)
    d = forecast(fl, "main", features_py)
    tb = ["table", "--root", ".", "--format", "csv", "--limit", "1000000", "--out"]
    fl.step(["features_main.csv"], ["train.csv"], tb + ["train.csv", "--where", "week:int < %d" % HOLDOUT_FROM, "features_main.csv"])
    fl.step(["features_main.csv"], ["test.csv"], tb + ["test.csv", "--where", "week:int >= %d" % HOLDOUT_FROM, "features_main.csv"])
    drop = "pharmacy,item,week"
    fl.step(["train.csv"], ["m_constant.ml"], ["ml", "--root", ".", "--model", "constant", "--target", "units", "--drop", drop + ",group,season", "--output", "m_constant.ml", "fit", "train.csv"], stdout_file="fit_constant.json")
    for m in ("boost", "forest"):
        fl.step(["train.csv"], ["m_%s.ml" % m], ["ml", "--root", ".", "--model", m, "--cat", "group,season", "--step", "encode column=group,season kind=onehot", "--target", "units", "--drop", drop,
                                                 "--output", "m_%s.ml" % m, "fit", "train.csv"], stdout_file="fit_%s.json" % m)
        fl.step(["m_%s.ml" % m, "test.csv"], [], ["ml", "--root", ".", "--model-file", "m_%s.ml" % m, "--drop", drop, "eval", "test.csv"], stdout_file="eval_%s.json" % m)
    # G2: the seasonal effect, on the items whose group the pharmacy knows
    for g in ("respiratory", "chronic"):
        fl.step(["features_main.csv"], ["%s_main.csv" % g], tb + ["%s_main.csv" % g, "--where", "group = '%s' and season != 'shoulder'" % g, "features_main.csv"])
        fl.step(["%s_main.csv" % g], [], ["stats", "--root", ".", "test", "t2", "--cols", "units", "--group", "season", "%s_main.csv" % g], stdout_file="t2_%s_main.json" % g)
        fl.step(["%s_main.csv" % g], [], ["stats", "--root", ".", "describe", "--cols", "units", "--by", "season", "%s_main.csv" % g], stdout_file="describe_%s_main.json" % g)
    # the control: the same system with its seasonal amplitude set to zero
    make_world(fl, "world_zero.json", True)
    forecast(fl, "zero", features_py)
    fl.step(["features_zero.csv"], ["respiratory_zero.csv"], tb + ["respiratory_zero.csv", "--where", "group = 'respiratory' and season != 'shoulder'", "features_zero.csv"])
    fl.step(["respiratory_zero.csv"], [], ["stats", "--root", ".", "test", "t2", "--cols", "units", "--group", "season", "respiratory_zero.csv"], stdout_file="t2_respiratory_zero.json")


def mad_poisson(lam):
    """E|X - lam| for X ~ Poisson(lam): the noise floor of a forecaster that knows the mean exactly (float arithmetic: this is the gate, not the twin)."""
    if lam <= 0:
        return 0.0
    p, k, tot = math.exp(-lam), 0, 0.0
    cum = 0.0
    while cum < 1 - 1e-12 and k < 2000:
        tot += p * abs(k - lam)
        cum += p
        k += 1
        p = p * lam / k
    return tot


def table(text):
    lines = text.splitlines()
    head = lines[0].split(",")
    return [dict(zip(head, ln.split(","))) for ln in lines[1:]]


def judge(fl):
    problems, report = judge_forecast(fl)
    p2, r2 = judge_records(fl)
    return problems + p2, report + r2


def judge_forecast(fl):
    problems, report = [], []
    J = lambda rel: json.loads(fl.read(rel))
    # ---- G2 ----
    def t2(rel):
        t = J(rel)["data"]["tests"][0]
        lv = J(rel)["data"]["levels"]
        assert lv == {"a": "summer", "b": "winter"}, lv
        return t["p_value"], -t["interval"]["estimate"]  # winter minus summer
    def means(rel):
        cols = J(rel)["data"]["groups"]
        return {g["value"]: float(g["columns"][0]["mean"]) for g in cols}
    sys.path.insert(0, str(HERE))
    from twinlib.core import season_ppm
    P = json.loads((HERE / "world.json").read_text())["params"]
    def expected_ratio(gi):
        winter = [w for w in range(52) if w >= 47 or w <= 7]
        summer = [w for w in range(22, 34)]
        f = lambda ws: sum(season_ppm(w, P["season_peak_week"]["value"][gi], P["season_amplitude_ppm"]["value"][gi]) for w in ws) / len(ws)
        return f(winter) / f(summer)
    p, diff = t2("t2_respiratory_main.json")
    m = means("describe_respiratory_main.json")
    ratio, want = m["winter"] / m["summer"], expected_ratio(1)
    report.append("G2 respiratory: winter minus summer %+.2f units, p = %.2e, ratio of means %.3f (the parameters give %.3f without stockouts)" % (diff, p, ratio, want))
    if not (diff > 0 and p < G2_P_FOUND):
        problems.append("G2: the respiratory seasonal effect was not found (difference %+.2f, p = %.2e, wanted a positive difference and p < %g)" % (diff, p, G2_P_FOUND))
    if abs(ratio - want) > G2_RATIO_TOL * want:
        problems.append("G2: respiratory winter/summer ratio %.3f is not within %.0f%% of %.3f" % (ratio, 100 * G2_RATIO_TOL, want))
    pc, dc = t2("t2_chronic_main.json")
    report.append("G2 chronic (no effect in the twin): difference %+.2f, p = %.3f" % (dc, pc))
    if pc < G2_P_ABSENT:
        problems.append("G2: an effect was found on chronic items, where the twin has none (p = %.2e < %g)" % (pc, G2_P_ABSENT))
    pz, dz = t2("t2_respiratory_zero.json")
    report.append("G2 control (amplitude set to zero): difference %+.2f, p = %.3f" % (dz, pz))
    if pz < G2_P_ABSENT:
        problems.append("G2: an effect was found with the seasonal amplitude set to zero (p = %.2e < %g)" % (pz, G2_P_ABSENT))
    # ---- G4 ----
    test = table(fl.read("test.csv"))
    train = table(fl.read("train.csv"))
    last_train, first_test = max(int(r["week"]) for r in train), min(int(r["week"]) for r in test)
    shared = {(r["pharmacy"], r["item"], r["week"]) for r in train} & {(r["pharmacy"], r["item"], r["week"]) for r in test}
    report.append("G4 split hygiene: training weeks end at %d, held-out weeks start at %d, %d rows in both" % (last_train, first_test, len(shared)))
    if last_train >= first_test or shared:
        problems.append("G4: the training file holds weeks up to %d and the held-out file starts at %d (%d shared rows): the held-out weeks leaked into training" % (last_train, first_test, len(shared)))
    truth = {(r["pharmacy"], r["item"], r["week"]): int(r["true_mean_milli"]) for r in table(fl.read("data_main/truth/demand.csv"))}
    const_mean = float(J("fit_constant.json")["data"]["summary"]["mean"])
    n = len(test)
    mae_const = sum(abs(int(r["units"]) - const_mean) for r in test) / n
    mae_last = sum(abs(int(r["units"]) - int(r["lag1"])) for r in test) / n
    floor = sum(mad_poisson(truth[(r["pharmacy"], r["item"], r["week"])] / 1000.0) for r in test) / n
    base = min(mae_const, mae_last)
    report.append("G4 held-out weeks %d to 103, %d rows: baselines MAE: training mean %.3f, last week %.3f; noise floor %.3f" % (HOLDOUT_FROM, n, mae_const, mae_last, floor))
    for mdl in ("boost", "forest"):
        mae = float(J("eval_%s.json" % mdl)["data"]["metrics"]["mae"])
        report.append("G4 %s: MAE %.3f = %s of the best baseline, %s of the noise floor" % (mdl, mae, ("%.3f" % (mae / base)) if base else "n/a", ("%.3f" % (mae / floor)) if floor else "n/a"))
        if mdl == "boost":
            if mae > G4_IMPROVE * base:
                problems.append("G4: boost MAE %.3f is not at most %.2f times the best baseline %.3f" % (mae, G4_IMPROVE, base))
            if mae < G4_FLOOR * floor:
                problems.append("G4: boost MAE %.3f is below %.2f times the noise floor %.3f: it has seen something it should not" % (mae, G4_FLOOR, floor))
    return problems, report


def judge_records(fl, victim_file="features_main.csv"):
    problems, report = [], []
    # ---- G7 ----
    r = subprocess.run([fl.records, "check", "--recursive", "--root", ".", "rec"], cwd=fl.root, capture_output=True, text=True)
    ok = json.loads(r.stdout).get("ok") if r.stdout.strip().startswith("{") else False
    report.append("G7 flow-records check on %d steps: %s" % (fl.steps, "clean" if r.returncode == 0 and ok else "NOT CLEAN"))
    if r.returncode != 0 or not ok:
        problems.append("G7: flow-records check was not clean on the untouched records: %s" % r.stdout[:300])
    victim = fl.root / victim_file
    original = victim.read_bytes()
    victim.write_bytes(original[:-2] + (b"9\n" if original[-2:-1] != b"9" else b"8\n"))
    r = subprocess.run([fl.records, "check", "--recursive", "--root", ".", "rec"], cwd=fl.root, capture_output=True, text=True)
    victim.write_bytes(original)
    report.append("G7 after changing one byte of %s: flow-records check exit %d%s" % (victim_file, r.returncode, "" if r.returncode else " (NOT DETECTED)"))
    if r.returncode == 0:
        problems.append("G7: changing a byte of a recorded output was not detected")
    return problems, report


def _x(*parts):
    return "".join(parts)  # a mutant's `old` text is assembled here so that it does not also occur, literally, in this list


MUTANTS = [
    # name, file, old, new, the gate that must fail
    ("leaks-the-target", "features.py", _x("u[t - 1], u[t - ", "2], sum("), _x("u[t - 1], u[", "t], sum("), "G4"),
    ("seasons-swapped", "features.py", 'return "winter"\n    if 22 <= woy <= 33:\n        return "summer"', 'return "summer"\n    if 22 <= woy <= 33:\n        return "winter"', "G2"),
    ("holdout-leaks-into-training", "scripts/pipeline_c.py", _x('"week:int < %d" % HOLD', 'OUT_FROM'), _x('"week:int < %d" % (HOLD', 'OUT_FROM + 12)'), "G4"),
    ("model-without-lags-or-item", "scripts/pipeline_c.py", _x('drop = "pharmacy,item,week', '"\n    fl.step(["train.csv"]'), _x('drop = "pharmacy,item,week,lag1,lag2,lag4sum,stockout1,pack_size,shelf_life_days,cold_chain,scale_ppm', '"\n    fl.step(["train.csv"]'), "G4"),
]


def run(keep=None):
    with tempfile.TemporaryDirectory() as td:
        fl = Flow(td)
        run_main(fl)
        problems, report = judge(fl)
        if keep:
            shutil.copytree(fl.root, keep, dirs_exist_ok=True)
        return problems, report


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
    real = HERE
    for name, rel, old, new, gate in MUTANTS:
        if only and name != only:
            continue
        with tempfile.TemporaryDirectory() as td:
            tree = pathlib.Path(td) / "pharma-chain"
            shutil.copytree(real, tree, ignore=shutil.ignore_patterns("__pycache__"))
            f = tree / rel
            text = f.read_text()
            if text.count(old) != 1:
                print("mutant %-28s CANNOT BE APPLIED (%d occurrences in %s)" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            # the mutated copy is run as the pipeline: its own files are the ones copied into the flow root
            env = dict(os.environ, FLOW_REPO=str(REPO), TABLE=exe("table", "TABLE"), STATS=exe("stats", "STATS"), ML=exe("ml", "ML"))
            r = subprocess.run([sys.executable, str(tree / "scripts" / "pipeline_c.py")], capture_output=True, text=True, env=env, cwd=td, timeout=3000)
            if only:
                print((r.stdout + r.stderr)[-1800:])
            hit = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith(gate + ":")]
            if r.returncode != 0 and hit:
                print("killed   %-28s by %s" % (name, hit[0][:110]))
            else:
                survived += 1
                print("SURVIVED %-28s wanted a %s failure; exit %d, said %r" % (name, gate, r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:]))
    print("%d mutants, %d survived" % (len(MUTANTS), survived))
    return 1 if survived else 0


def main():
    if "--mutant" in sys.argv:
        return mutants(sys.argv[sys.argv.index("--mutant") + 1])
    if "--mutants" in sys.argv:
        return mutants()
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    problems, report = run(keep)
    for ln in report:
        print(ln)
    for p in problems:
        print(p)
    if problems:
        return 1
    print("pipeline_c: ok (G2, G4 and G7 hold at the margins of docs/use-cases.md section 7a)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
