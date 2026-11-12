#!/usr/bin/env python3
"""Gate G1 of docs/use-cases.md: the twin is deterministic, honest about its parameters, and refuses what it should.

    python3 scripts/check_twin.py              # the checks, on the committed twin
    python3 scripts/check_twin.py --mutants    # each deliberate fault in a copy of the twin must be caught by the check it targets

The checks (each says what it found, never just "failed"):
  known-answer  SplitMix64 from seed 0 gives the three published reference values
  normal        normal_micro has mean 0 and standard deviation 1,000,000 over 20,000 draws, within fixed bounds
  determinism   the same world, seed and size twice: every file the same bytes
  seed          another seed: items.csv and patients.csv differ
  independence  one more item moves neither pharmacies.csv nor patients.csv; one more pharmacy does not move items.csv
  rows          the rows of each file are the counts the world says
  share         on the large size, the realised shares are within 5 standard deviations of the world's parameters, recounted from the CSV
  extremes      a share of 0 gives none and a share of 1,000,000 gives all
  path          no output holds the working directory or the host name; every file ends in one newline and has no carriage return
  refusal       each bad input is exit 2, one JSON line on standard error with the expected rule tag, nothing on standard output, nothing written
  fuzz          300 random argument lists: exit 0 or 2, never a traceback (not in --mutants)
"""
import json
import math
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from twinlib.prng import SplitMix64  # noqa: E402  (the gate's own random numbers: the fuzz, not the twin under test)

FILES = ("items.csv", "pharmacies.csv", "patients.csv", "truth.json")


def run(tree, args, cwd):
    return subprocess.run([sys.executable, str(tree / "twin.py")] + args, cwd=cwd, capture_output=True, text=True, timeout=120)


def gen(tree, work, world, seed, size, out):
    r = run(tree, ["generate", "--world", world, "--seed", str(seed), "--size", size, "--out", out], work)
    if r.returncode != 0:
        return None, r
    return {f: (pathlib.Path(work) / out / f).read_bytes() for f in FILES}, r


def lib(tree, code):
    r = subprocess.run([sys.executable, "-c", "import sys; sys.dont_write_bytecode=True; sys.path.insert(0, %r)\n%s" % (str(tree), code)], capture_output=True, text=True, timeout=120)
    return r


def rows(b):
    return b.decode().count("\n") - 1


def table(b):
    lines = b.decode().splitlines()
    head = lines[0].split(",")
    return [dict(zip(head, ln.split(","))) for ln in lines[1:]]


def sigma(n, p):
    return math.sqrt(n * p * (1 - p))


def check(tree, fast=False):
    """Returns the list of problems found; empty when the twin holds."""
    problems = []
    world_path = tree / "world.json"
    world = json.loads(world_path.read_text())
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td)
        shutil.copy(world_path, work / "world.json")

        # known-answer
        r = lib(tree, "from twinlib.prng import SplitMix64\nr=SplitMix64(0)\nprint(json.dumps([r.next_u64() for _ in range(3)]) if False else [r.next_u64() for _ in range(3)])")
        want = [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]
        if r.returncode != 0 or str(want) != r.stdout.strip():
            problems.append("known-answer: SplitMix64 from seed 0 gave %s, not %s" % (r.stdout.strip() or r.stderr.strip()[-80:], want))

        # normal
        r = lib(tree, "from twinlib.prng import SplitMix64\nr=SplitMix64(12345)\nx=[r.normal_micro() for _ in range(20000)]\nm=sum(x)/len(x)\nv=sum((a-m)**2 for a in x)/len(x)\nprint(m, v**0.5)")
        try:
            m, sd = (float(t) for t in r.stdout.split())
            if abs(m) > 5 * 1_000_000 / math.sqrt(20000) or abs(sd - 1_000_000) > 30_000:
                problems.append("normal: mean %.0f and sd %.0f over 20,000 draws, not 0 and 1,000,000 within bounds" % (m, sd))
        except ValueError:
            problems.append("normal: the draw did not run: %s" % r.stderr.strip()[-100:])

        # determinism, seed
        a, ra = gen(tree, work, "world.json", 20261112, "small", "a")
        b, rb = gen(tree, work, "world.json", 20261112, "small", "b")
        if a is None or b is None:
            return problems + ["determinism: the twin did not run: %s" % ((ra.stderr if a is None else rb.stderr).strip()[-120:])]
        for f in FILES:
            if a[f] != b[f]:
                problems.append("determinism: two runs of the same world, seed and size differ in %s" % f)
        c, _ = gen(tree, work, "world.json", 20261113, "small", "c")
        if c is not None:
            for f in ("items.csv", "patients.csv"):
                if c[f] == a[f]:
                    problems.append("seed: another seed gives the same %s" % f)

        # independence
        for label, key, same in (("items", "items", ("pharmacies.csv", "patients.csv")), ("pharmacies", "pharmacies", ("items.csv",))):
            w2 = json.loads(json.dumps(world))
            w2["sizes"]["small"][key] += 1
            (work / ("w_%s.json" % label)).write_text(json.dumps(w2))
            d, _ = gen(tree, work, "w_%s.json" % label, 20261112, "small", "d_" + label)
            if d is not None:
                for f in same:
                    if d[f] != a[f]:
                        problems.append("independence: one more %s moves %s" % (label, f))

        # rows
        n = world["sizes"]["small"]
        for f, key in (("items.csv", "items"), ("pharmacies.csv", "pharmacies"), ("patients.csv", "patients")):
            if rows(a[f]) != n[key]:
                problems.append("rows: %s has %d rows, the world says %d" % (f, rows(a[f]), n[key]))

        # share: the large size, recounted from the CSV
        big, _ = gen(tree, work, "world.json", 20261112, "large", "big")
        if big is not None:
            P = {k: v["value"] for k, v in world["params"].items()}
            items, patients = table(big["items.csv"]), table(big["patients.csv"])
            for col, key in (("cold_chain", "cold_chain_share_ppm"), ("controlled", "controlled_share_ppm"), ("critical", "critical_share_ppm")):
                got, p = sum(int(r[col]) for r in items), P[key] / 1e6
                if abs(got - len(items) * p) > 5 * sigma(len(items), p):
                    problems.append("share: %d of %d items are %s, the parameter %s says %.0f" % (got, len(items), col, key, len(items) * p))
            for col, key in (("refill_interval_days", "refill_interval_days"), ("n_items", "items_per_patient")):
                tot = sum(w for _, w in P[key])
                for v, w in P[key]:
                    got, p = sum(1 for r in patients if int(r[col]) == v), w / tot
                    if abs(got - len(patients) * p) > 5 * sigma(len(patients), p):
                        problems.append("share: %d of %d patients have %s = %d, the parameter says %.0f" % (got, len(patients), col, v, len(patients) * p))
            tot = sum(P["age_band_weights"])
            for band, w in zip(("18-39", "40-54", "55-64", "65-74", "75+"), P["age_band_weights"]):
                got, p = sum(1 for r in patients if r["age_band"] == band), w / tot
                if abs(got - len(patients) * p) > 5 * sigma(len(patients), p):
                    problems.append("share: %d of %d patients are in band %s, the parameter says %.0f" % (got, len(patients), band, len(patients) * p))
            truth = json.loads(big["truth.json"])
            if truth["realised"]["cold_chain_items"] != sum(int(r["cold_chain"]) for r in items):
                problems.append("share: truth.json says %d cold-chain items, items.csv holds %d" % (truth["realised"]["cold_chain_items"], sum(int(r["cold_chain"]) for r in items)))

        # extremes
        for ppm, want_all in ((0, False), (1_000_000, True)):
            w2 = json.loads(json.dumps(world))
            w2["params"]["cold_chain_share_ppm"]["value"] = ppm
            (work / "w_ext.json").write_text(json.dumps(w2))
            d, _ = gen(tree, work, "w_ext.json", 5, "small", "e%d" % ppm)
            if d is not None:
                cold = sum(int(r["cold_chain"]) for r in table(d["items.csv"]))
                if cold != (n["items"] if want_all else 0):
                    problems.append("extremes: a cold-chain share of %d ppm gave %d of %d items" % (ppm, cold, n["items"]))

        # path
        host = socket.gethostname().encode()
        for name, data in a.items():
            if str(work).encode() in data or str(HERE).encode() in data or (host and host in data):
                problems.append("path: %s holds the working directory or the host name" % name)
            if b"\r" in data or not data.endswith(b"\n") or data.endswith(b"\n\n"):
                problems.append("path: %s does not end in exactly one newline, or holds a carriage return" % name)

        # refusal
        def refused(label, args, rule, world_text=None):
            wp = "rw.json"
            if world_text is not None:
                (work / wp).write_text(world_text)
            out = "refused_%s" % label
            r = run(tree, args(wp, out), work)
            err = r.stderr.strip().splitlines()
            tag = None
            if len(err) == 1:
                try:
                    tag = json.loads(err[0])["error"]["rule"]
                except (ValueError, KeyError, TypeError):
                    pass
            if r.returncode != 2 or tag != rule or r.stdout or "Traceback" in r.stderr:
                problems.append("refusal: %s: exit %s, rule %s, wanted exit 2 and %s" % (label, r.returncode, tag, rule))
            if label not in ("exists",) and (work / out).exists():
                problems.append("refusal: %s wrote %s" % (label, out))

        base = json.dumps(world)

        def mut(fn):
            w2 = json.loads(base)
            fn(w2)
            return json.dumps(w2)

        def ok_args(wp, out, extra=()):
            return ["generate", "--world", wp, "--seed", "1", "--size", "small", "--out", out] + list(extra)

        refused("no-args", lambda wp, out: [], "twin.usage", base)
        refused("bad-size", lambda wp, out: ["generate", "--world", wp, "--seed", "1", "--size", "huge", "--out", out], "twin.bad-size", base)
        refused("bad-seed", lambda wp, out: ["generate", "--world", wp, "--seed", "x", "--size", "small", "--out", out], "twin.bad-seed", base)
        refused("neg-seed", lambda wp, out: ["generate", "--world", wp, "--seed", "-1", "--size", "small", "--out", out], "twin.bad-seed", base)
        refused("dotdot", lambda wp, out: ok_args(wp, "../" + out), "twin.bad-path", base)
        refused("absolute", lambda wp, out: ok_args(wp, "/" + out), "twin.bad-path", base)
        refused("no-world", lambda wp, out: ok_args("nowhere.json", out), "twin.world-unreadable", base)
        refused("not-json", lambda wp, out: ok_args(wp, out), "twin.bad-world", "{not json")
        refused("schema", lambda wp, out: ok_args(wp, out), "twin.bad-world", mut(lambda w: w.update(schema="twin.world.v0")))
        refused("unknown-param", lambda wp, out: ok_args(wp, out), "twin.unknown-param", mut(lambda w: w["params"].update(surprise=w["params"]["regions"])))
        refused("missing-param", lambda wp, out: ok_args(wp, out), "twin.missing-param", mut(lambda w: w["params"].pop("regions")))
        refused("bad-share", lambda wp, out: ok_args(wp, out), "twin.bad-param", mut(lambda w: w["params"]["cold_chain_share_ppm"].update(value=2_000_000)))
        refused("fitted-without-from", lambda wp, out: ok_args(wp, out), "twin.bad-param", mut(lambda w: w["params"]["regions"].update(source="fitted")))
        refused("zero-weight", lambda wp, out: ok_args(wp, out), "twin.bad-param", mut(lambda w: w["params"]["age_band_weights"].update(value=[0, 1, 1, 1, 1])))
        (work / "taken").mkdir(exist_ok=True)
        (work / "taken" / "x").write_text("x")
        refused("exists", lambda wp, out: ok_args(wp, "taken"), "twin.exists", base)
        r = run(tree, ok_args("world.json", "taken", ["--overwrite"]), work)
        if r.returncode != 0:
            problems.append("refusal: --overwrite on a non-empty directory exited %d" % r.returncode)

        # fuzz
        if not fast:
            rng = SplitMix64(20261112)
            toks = ["generate", "--world", "world.json", "--seed", "--size", "--out", "--overwrite", "small", "large", "7", "-1", "99999999999999999999", "x", "", "..", "/", "fz", "--zzz", "\x00"]
            for i in range(300):
                args = [toks[rng.below(len(toks))] for _ in range(rng.below(9))]
                try:
                    r = run(tree, args, work)
                except ValueError:  # an argument with a NUL cannot be passed to a process: the harness, not the twin
                    continue
                if r.returncode not in (0, 2) or "Traceback" in r.stderr or (r.returncode == 2 and not r.stderr.strip().startswith("{")):
                    problems.append("fuzz: %r gave exit %d and %r" % (args, r.returncode, r.stderr.strip()[-100:]))
                    break
                for p in work.glob("fz*"):
                    shutil.rmtree(p, ignore_errors=True)
    return problems


MUTANTS = [
    ("seed-ignored", "twinlib/prng.py", '("%d:%s" % (self.seed, label))', '(":%s" % (label))', "seed"),
    ("path-in-truth", "twinlib/core.py", '"world": world["name"],', '"world": world["name"] + __import__("os").getcwd(),', "path"),
    ("one-patient-too-many", "twinlib/core.py", 'for i in range(n["patients"]):', 'for i in range(n["patients"] + 1):', "rows"),
    ("cold-share-ignored", "twinlib/core.py", 'c = r.bernoulli(p["cold_chain_share_ppm"])', "c = r.bernoulli(0)", "extremes"),
    ("weights-ignored", "twinlib/prng.py", "total = sum(w for _, w in weighted)\n        r = self.below(total)",
     "total = len(weighted)\n        r = self.below(total)\n        weighted = [[v, 1] for v, _ in weighted]", "share"),
    ("eleven-uniforms", "twinlib/prng.py", "for _ in range(12)", "for _ in range(11)", "normal"),
    ("dotdot-allowed", "twin.py", 'or ".." in out.replace("\\\\", "/").split("/")', "", "refusal"),
    ("streams-shared", "twinlib/prng.py", 'return SplitMix64(int.from_bytes(h[:8], "big"))', "return self", "independence"),
    ("unknown-param-allowed", "twinlib/world.py", "if k not in PARAMS:", "if False:", "refusal"),
    ("python-random", "twinlib/core.py", '1 + r.below(p["regions"])', '1 + __import__("random").randrange(p["regions"])', "determinism"),
    ("wrong-generator-constant", "twinlib/prng.py", "0x9E3779B97F4A7C15", "0x9E3779B97F4A7C16", "known-answer"),
]


def mutants():
    base = check(HERE)
    if base:
        print("control FAILED (the unmodified twin is refused):")
        for p in base:
            print("  " + p)
        return 1
    print("control passes")
    survived = 0
    for name, rel, old, new, want in MUTANTS:
        with tempfile.TemporaryDirectory() as td:
            tree = pathlib.Path(td) / "t"
            shutil.copytree(HERE, tree, ignore=shutil.ignore_patterns("__pycache__", "scripts", "*.pyc"))
            f = tree / rel
            text = f.read_text()
            if text.count(old) != 1:
                print("mutant %-26s CANNOT BE APPLIED: the text occurs %d times in %s" % (name, text.count(old), rel))
                survived += 1
                continue
            f.write_text(text.replace(old, new))
            found = check(tree, fast=True)
            hit = [p for p in found if p.startswith(want)]
            if hit:
                print("killed   %-26s by %s" % (name, hit[0][:90]))
            else:
                survived += 1
                print("SURVIVED %-26s wanted a %s problem; found %s" % (name, want, [p[:50] for p in found] or "none"))
    print("%d mutants, %d survived" % (len(MUTANTS), survived))
    return 1 if survived else 0


def main():
    if "--mutants" in sys.argv:
        return mutants()
    problems = check(HERE)
    for p in problems:
        print("check_twin: " + p)
    if problems:
        return 1
    print("check_twin: ok (G1: known answer, determinism, seed, independence, rows, shares, extremes, path, refusals, fuzz)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
