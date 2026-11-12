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

FILES = ("items.csv", "pharmacies.csv", "patients.csv", "truth.json", "dispensing.csv", "truth/demand.csv", "refills.csv")
CORE_FILES = ("items.csv", "pharmacies.csv", "patients.csv", "truth.json")


def run(tree, args, cwd):
    return subprocess.run([sys.executable, str(tree / "twin.py")] + args, cwd=cwd, capture_output=True, text=True, timeout=120)


def gen(tree, work, world, seed, size, out, tables=None):
    r = run(tree, ["generate", "--world", world, "--seed", str(seed), "--size", size, "--out", out] + (["--tables", tables] if tables else []), work)
    if r.returncode != 0:
        return None, r
    return {f: (pathlib.Path(work) / out / f).read_bytes() for f in (CORE_FILES if tables == "core" else FILES)}, r


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
        work = pathlib.Path(td) / "w"  # one level in, so that a `..` that gets through writes inside td and is removed with it
        work.mkdir()
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

        # poisson
        r = lib(tree, "from twinlib.prng import SplitMix64\nr=SplitMix64(7)\nout=[]\nfor lam in (500, 3000, 20000):\n    x=[r.poisson_milli(lam) for _ in range(20000)]\n    m=sum(x)/len(x)\n    v=sum((a-m)**2 for a in x)/len(x)\n    out.append((lam/1000, m, v))\nprint(out)")
        try:
            for lam, m, v in eval(r.stdout):
                if abs(m - lam) > 5 * math.sqrt(lam / 20000) or abs(v - lam) > 0.1 * lam + 0.05:
                    problems.append("poisson: mean %.3f and variance %.3f at mean %.1f" % (m, v, lam))
        except Exception:
            problems.append("poisson: the draw did not run: %s" % r.stderr.strip()[-100:])

        # determinism, seed
        a, ra = gen(tree, work, "world.json", 20261112, "small", "a")
        a_core = {f: a[f] for f in CORE_FILES} if a else None
        b, rb = gen(tree, work, "world.json", 20261112, "small", "b")
        if a is None or b is None:
            return problems + ["determinism: the twin did not run: %s" % ((ra.stderr if a is None else rb.stderr).strip()[-120:])]
        for f in FILES:
            if a[f] != b[f]:
                problems.append("determinism: two runs of the same world, seed and size differ in %s" % f)
        c, _ = gen(tree, work, "world.json", 20261113, "small", "c")
        if c is not None:
            for f in ("items.csv", "patients.csv", "dispensing.csv"):
                if c[f] == a[f]:
                    problems.append("seed: another seed gives the same %s" % f)

        # independence
        for label, key, same in (("items", "items", ("pharmacies.csv", "patients.csv")), ("pharmacies", "pharmacies", ("items.csv",))):
            w2 = json.loads(json.dumps(world))
            w2["sizes"]["small"][key] += 1
            (work / ("w_%s.json" % label)).write_text(json.dumps(w2))
            d, _ = gen(tree, work, "w_%s.json" % label, 20261112, "small", "d_" + label, "core")
            if d is not None:
                for f in same:
                    if d[f] != a_core[f]:
                        problems.append("independence: one more %s moves %s" % (label, f))

        # rows
        n = world["sizes"]["small"]
        for f, key in (("items.csv", "items"), ("pharmacies.csv", "pharmacies"), ("patients.csv", "patients")):
            if rows(a[f]) != n[key]:
                problems.append("rows: %s has %d rows, the world says %d" % (f, rows(a[f]), n[key]))

        # ledger: the stock accounting and the censoring, recounted from the CSVs (the truth file is read here, as the gates may)
        W = n["weeks"]
        if rows(a["dispensing.csv"]) != n["pharmacies"] * n["items"] * W:
            problems.append("rows: dispensing.csv has %d rows, the world says %d" % (rows(a["dispensing.csv"]), n["pharmacies"] * n["items"] * W))
        disp, dem = table(a["dispensing.csv"]), table(a["truth/demand.csv"])
        pack = {r["item"]: int(r["pack_size"]) for r in table(a["items.csv"])}
        grp = {r["item"]: r["therapeutic_group"] for r in table(a["items.csv"])}
        prev, bad = {}, {}
        if len(dem) != len(disp):
            problems.append("ledger: truth/demand.csv has %d rows, dispensing.csv %d" % (len(dem), len(disp)))
        else:
            for r, t in zip(disp, dem):
                ss, rc, wo, u, so, se, od = (int(r[k]) for k in ("stock_start", "received", "written_off", "units", "stockout", "stock_end", "ordered"))
                d = int(t["demand"])
                key = (r["pharmacy"], r["item"])
                if (r["pharmacy"], r["item"], r["week"]) != (t["pharmacy"], t["item"], t["week"]):
                    bad["order"] = "dispensing and demand rows are not the same cells in the same order"
                if min(ss, rc, wo, u, so, se, od, d) < 0:
                    bad["negative"] = "a negative quantity in %s" % r
                if se != ss - u:
                    bad["identity"] = "stock_end %d is not stock_start %d minus units %d" % (se, ss, u)
                if u != min(d, ss):
                    bad["censor"] = "units %d is not min(demand %d, stock_start %d)" % (u, d, ss)
                if so != int(d > ss):
                    bad["flag"] = "stockout %d with demand %d and stock_start %d" % (so, d, ss)
                if od % pack[r["item"]]:
                    bad["pack"] = "ordered %d is not a multiple of the pack size %d" % (od, pack[r["item"]])
                if key in prev and ss != prev[key][0] + rc - wo:
                    bad["chain"] = "stock_start %d is not last week's stock_end %d plus received %d minus written_off %d" % (ss, prev[key][0], rc, wo)
                if key in prev and rc != prev[key][1]:
                    bad["arrival"] = "received %d is not what was ordered last week, %d" % (rc, prev[key][1])
                prev[key] = (se, od)
        for k, v in bad.items():
            problems.append("ledger: %s: %s" % (k, v))
        # refills: the series of every patient-item, recounted from the CSVs
        ref = table(a["refills.csv"])
        pat = {r["patient"]: r for r in table(a["patients.csv"])}
        stockouts = {(r["pharmacy"], r["item"], int(r["week"])) for r in disp if r["stockout"] == "1"}
        window = world["params"]["stockout_window_weeks"]["value"]
        series, rbad = {}, {}
        for r in ref:
            series.setdefault((r["patient"], r["item"]), []).append(r)
        for (pid, it), rs in series.items():
            pr = pat[pid]
            if grp.get(it) != "chronic":
                rbad["chronic"] = "%s takes %s, which is %s" % (pid, it, grp.get(it))
            if any(x["pharmacy"] != pr["home_pharmacy"] for x in rs):
                rbad["home"] = "%s is refilled at a pharmacy other than %s" % (pid, pr["home_pharmacy"])
            iv = int(rs[0]["interval_weeks"])
            if int(pr["refill_interval_days"]) // 7 != iv:
                rbad["interval"] = "%s has interval %d weeks, patients.csv says %s days" % (pid, iv, pr["refill_interval_days"])
            ws = [int(x["due_week"]) for x in rs]
            if ws[0] >= iv or any(b - a_ != iv for a_, b in zip(ws, ws[1:])) or ws[-1] >= W:
                rbad["schedule"] = "%s %s due weeks %s are not one every %d weeks from a start below %d" % (pid, it, ws[:4], iv, iv)
            if any(x["filled"] != "1" for x in rs[:-1]) or rs[-1]["filled"] not in ("0", "1"):
                rbad["series"] = "%s %s has a refill after a lapse" % (pid, it)
            for x in rs:
                seen = int(any((x["pharmacy"], it, k) in stockouts for k in range(max(0, int(x["due_week"]) - window + 1), int(x["due_week"]) + 1)))
                if seen != int(x["stockout_seen"]):
                    rbad["seen"] = "%s %s week %s says stockout_seen %s, dispensing.csv says %d" % (pid, it, x["due_week"], x["stockout_seen"], seen)
        per_patient = {}
        for (pid, it) in series:
            per_patient[pid] = per_patient.get(pid, 0) + 1
        if any(c > int(pat[pid]["n_items"]) for pid, c in per_patient.items()):
            rbad["items"] = "a patient takes more items than n_items"
        tr = json.loads(a["truth.json"])["realised"]
        if tr.get("refill_events") != len(ref) or tr.get("refill_lapses") != sum(1 for x in ref if x["filled"] == "0"):
            rbad["truth"] = "truth.json counts %s events and %s lapses, refills.csv holds %d and %d" % (tr.get("refill_events"), tr.get("refill_lapses"), len(ref), sum(1 for x in ref if x["filled"] == "0"))
        for k, v in rbad.items():
            problems.append("refills: %s: %s" % (k, v))

        # coupling: seen against not seen, at the parameter's value and with it set to zero (a 4-standard-deviation check of the twin, not the margin of G3)
        def diff(rows):
            a1 = [x for x in rows if x["stockout_seen"] == "1"]
            a0 = [x for x in rows if x["stockout_seen"] == "0"]
            if len(a1) < 50 or len(a0) < 50:
                return None, None
            p1, p0 = sum(x["filled"] == "0" for x in a1) / len(a1), sum(x["filled"] == "0" for x in a0) / len(a0)
            se = math.sqrt(p1 * (1 - p1) / len(a1) + p0 * (1 - p0) / len(a0))
            return p1 - p0, se
        dv, se = diff(ref)
        want = world["params"]["lapse_stockout_ppm"]["value"] / 1e6
        if dv is None or abs(dv - want) > 4 * se:
            problems.append("coupling: lapse proportion seen minus not seen is %s (se %s), the parameter says %.3f" % (("%.4f" % dv) if dv is not None else "undefined", ("%.4f" % se) if se else "-", want))
        w0 = json.loads(json.dumps(world))
        w0["params"]["lapse_stockout_ppm"]["value"] = 0
        (work / "w_noc.json").write_text(json.dumps(w0))
        z0, _ = gen(tree, work, "w_noc.json", 20261112, "small", "noc")
        if z0 is not None:
            dz, sz = diff(table(z0["refills.csv"]))
            if dz is None or abs(dz) > 4 * sz:
                problems.append("coupling: with the parameter set to zero the difference is %s (se %s), not zero" % (("%.4f" % dz) if dz is not None else "undefined", ("%.4f" % sz) if sz else "-"))

        # the seasonal shape: respiratory demand at the peak week against half a year away, chronic flat
        tot = {}
        for t in dem:
            w = int(t["week"]) % 52
            tot[(grp[t["item"]], w)] = tot.get((grp[t["item"]], w), 0) + int(t["demand"])
        P0 = {k: v["value"] for k, v in world["params"].items()}
        for gi, g in enumerate(("chronic", "respiratory", "allergy")):
            pk, am = P0["season_peak_week"][gi], P0["season_amplitude_ppm"][gi]
            hi, lo = tot.get((g, pk), 0), tot.get((g, (pk + 26) % 52), 0)
            want = (1_000_000 + am) / (1_000_000 - am)
            if hi == 0 or lo == 0 or abs(hi / lo - want) > 0.2 * want:
                problems.append("seasonal: %s demand at its peak week against half a year away is %s, the parameters say %.2f" % (g, ("%.2f" % (hi / lo)) if lo else "undefined", want))

        # share: the large size, recounted from the CSV
        big, _ = gen(tree, work, "world.json", 20261112, "large", "big", "core")
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
            d, _ = gen(tree, work, "w_ext.json", 5, "small", "e%d" % ppm, "core")
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
    ("poisson-mean-ignored", "twinlib/prng.py", "lam = Decimal(mean_milli) / Decimal(1000)", "lam = Decimal(3)", "poisson"),
    ("season-ignored", "twinlib/core.py", 'seas = season_ppm(week, p["season_peak_week"][g], p["season_amplitude_ppm"][g])', "seas = 1_000_000", "seasonal"),
    ("no-censoring", "twinlib/core.py", "sold = min(demand, stock_start)", "sold = demand", "ledger"),
    ("stockout-flag-wrong", "twinlib/core.py", "int(demand > stock_start)", "int(demand >= stock_start)", "ledger"),
    ("pack-rounding-off", "twinlib/core.py", "ordered = -(-want // pack) * pack if want else 0", "ordered = want", "ledger"),
    ("expiry-lost", "twinlib/core.py", "if exp <= week:\n                    written_off += u", "if exp <= week:\n                    pass", "ledger"),
    ("coupling-ignored", "twinlib/core.py", 'p["lapse_stockout_ppm"] * seen', "0 * seen", "coupling"),
    ("window-off-by-one", "twinlib/core.py", "range(max(0, w - window + 1), w + 1)", "range(max(0, w - window + 1), w)", "refills"),
    ("refills-after-a-lapse", "twinlib/core.py", "                if lapse:\n                    lapses += 1\n                    break\n", "                if lapse:\n                    lapses += 1\n", "refills"),
    ("wrong-home-pharmacy", "twinlib/core.py", "rows.append((pid, it, home, w, interval, seen, int(not lapse)))", 'rows.append((pid, it, "P001", w, interval, seen, int(not lapse)))', "refills"),
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
