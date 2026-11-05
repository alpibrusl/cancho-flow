#!/usr/bin/env python3
"""The gates of docs/design.md section 10, as far as M1 builds them. Each is a function; each can fail.

    FLOW=... FLOW_RECORDS=... PROGRAMS=... python3 tests/gates.py [name ...]

FLOW and FLOW_RECORDS are the two programs built for PROGRAMS (scripts/flow_build.py); PROGRAMS is the directory they start programs from.
scripts/check.sh builds them and runs every gate; scripts/mutants.py breaks the source and requires a gate to fail.
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time

FLOW = os.environ["FLOW"]
RECORDS = os.environ["FLOW_RECORDS"]
PROGRAMS = os.environ["PROGRAMS"]
HEX = "0123456789abcdef"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(binary, args, cwd, stdin=None, raw=False):
    p = subprocess.run([binary] + args, cwd=cwd, input=stdin, capture_output=True)
    try:
        doc = json.loads(p.stdout.decode()) if p.stdout and not raw else None
    except ValueError:
        doc = None
    return p.returncode, doc, p


def flow(cwd, *args, stdin=None):
    return run(FLOW, ["step", "--root", "."] + list(args), cwd, stdin)


def recs(cwd, *args):
    return run(RECORDS, list(args[:1]) + ["--root", "."] + list(args[1:]), cwd)


def rule(doc):
    return doc["error"]["rule"] if doc and not doc["ok"] else None


class World:
    """A scratch directory with a records directory and an input."""

    def __init__(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="flowgate-"))
        (self.d / "records").mkdir()
        (self.d / "in.txt").write_text("hello\n")

    def files(self):
        return sorted(os.listdir(self.d / "records"))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.d, ignore_errors=True)


def must(cond, message):
    if not cond:
        raise AssertionError(message)


STEP = ["--record", "records", "--in", "in.txt", "--out", "out.txt", "--deterministic", "--", "sh", "-c", "cat in.txt > out.txt; echo done"]


def make_record(w):
    rc, doc, _ = flow(w.d, *STEP)
    must(rc == 0 and doc["ok"], "the reference step failed: %s" % doc)
    return doc["data"]["record"]["file"], doc


# ---- G1 canonical ------------------------------------------------------------

def g1_canonical():
    with World() as a, World() as b:
        name, _ = make_record(a)
        rc, doc, _ = flow(a.d, *STEP)
        must(doc["data"]["record"]["written"] is False, "the same step twice must be idempotent (written:false)")
        must(a.files() == [name], "the same step twice must leave one record, found %s" % a.files())
        # a pure function of its inputs: the same step in another directory gives the same file, byte for byte
        name_b, _ = make_record(b)
        must(name == name_b, "another root gave another record name")
        ra, rb = (a.d / "records" / name).read_bytes(), (b.d / "records" / name).read_bytes()
        must(ra == rb, "another root gave other record bytes")
        # no clock time, host, process id, absolute path, payload
        for forbidden in (str(a.d), str(b.d), "/tmp", socket.gethostname()):
            must(forbidden.encode() not in ra, "the record holds %r" % forbidden)
        must(ra.endswith(b"}\n") and ra.count(b"\n") == 1, "a record is one line")


# ---- G2 damage (exhaustive) --------------------------------------------------

def g2_damage():
    with World() as w:
        name, _ = make_record(w)
        target = w.d / "records" / name
        good = target.read_bytes()
        text = good.decode()
        a_in, b_in = text.index('"inputs":') + 9, text.index(',"outcome":')
        a_out, b_out = b_in + 11, text.index(',"flow":')
        id_ = name[:64]

        def show(variant):
            target.write_bytes(variant)
            rc, doc, _ = recs(w.d, "show", "records", id_)
            return rc, doc

        variants = [("flip %d" % i, bytes(good[:i]) + bytes([good[i] ^ 0x01]) + good[i + 1:], i) for i in range(len(good))]
        variants += [("cut %d" % i, good[:i], None) for i in range(len(good))]
        variants += [("extra byte", good + b"x", None), ("extra line", good + b"\n", None)]
        reasons_in, reasons_out = set(), set()
        for label, v, at in variants:
            rc, doc = show(v)
            must(rc != 0 and rule(doc) == "flow.record.damaged", "%s: not refused as damaged (%s)" % (label, rule(doc) if doc else rc))
            # the reason says where: a byte of `inputs` breaks the layout (a quote or a brace the scanner needs) or the id, never only the check;
            # a byte of `outcome` breaks the layout or the oid. A mutant that skips the id (or oid) comparison would let such a byte through to the
            # check (reason 4), and is killed here.
            if at is not None and a_in <= at < b_in:
                reasons_in.add(doc["error"]["detail"]["reason"])
                must(doc["error"]["detail"]["reason"] in (1, 2), "%s: a byte of inputs must be reason 1 or 2, got %s" % (label, doc["error"]["detail"]["reason"]))
            if at is not None and a_out <= at < b_out:
                reasons_out.add(doc["error"]["detail"]["reason"])
                must(doc["error"]["detail"]["reason"] in (1, 3), "%s: a byte of outcome must be reason 1 or 3, got %s" % (label, doc["error"]["detail"]["reason"]))
        must(2 in reasons_in and 3 in reasons_out, "no flip reached the id or the oid comparison (inputs %s, outcome %s)" % (reasons_in, reasons_out))
        target.write_bytes(good)
        rc, doc, _ = recs(w.d, "show", "records", id_)
        must(rc == 0 and doc["ok"], "the intact record must read back")
    return len(variants)


# ---- G3 refusals -------------------------------------------------------------

def fixtures():
    """tag -> function(world) -> (doc), the answer that must carry the tag."""
    f = {}

    def step(w, *more, args=None):
        return flow(w.d, "--record", "records", *more)[1]

    f["flow.verb"] = lambda w: run(FLOW, ["bogus", "--root", ".", "--record", "records"], w.d)[1]
    f["flow.program-name"] = lambda w: step(w, "--", "a/b")
    f["flow.program-not-found"] = lambda w: step(w, "--", "nosuchprogram")
    f["flow.spawn-failed"] = lambda w: step(w, "--", "noexec")
    f["flow.args.not-utf8"] = lambda w: run(FLOW, ["step", "--root", ".", "--record", "records", "--", "true", b"\xff"], w.d)[1]
    f["flow.args.too-many"] = lambda w: step(w, "--", "true", *(["a"] * 4100))
    f["flow.stdin.conflict"] = lambda w: step(w, "--stdin", "--stdin-file", "in.txt", "--", "true")
    f["flow.stdout.undeclared"] = lambda w: step(w, "--stdout-file", "o.txt", "--", "true")
    f["flow.files.too-many"] = lambda w: step(w, "--in", ",".join("f%d" % i for i in range(65)), "--", "true")

    def too_many_records(w):
        for i in range(1000):
            (w.d / "records" / ("x%04d.json" % i)).write_text("")
        return step(w, "--", "true")
    f["flow.record.too-many"] = too_many_records

    def damaged_existing(w):
        name, _ = make_record(w)
        with open(w.d / "records" / name, "ab") as fh:
            fh.write(b" ")
        return flow(w.d, *STEP)[1]
    f["flow.record.damaged"] = damaged_existing
    f["flow.step.failed"] = lambda w: step(w, "--", "sh", "-c", "exit 3")
    f["flow.step.output-missing"] = lambda w: step(w, "--out", "nothere", "--", "true")

    def not_deterministic(w):
        flow(w.d, "--record", "records", "--deterministic", "--", "sh", "-c", "echo $$")
        return flow(w.d, "--record", "records", "--deterministic", "--", "sh", "-c", "echo $$")[1]
    f["flow.step.not-deterministic"] = not_deterministic
    f["limit.timeout"] = lambda w: step(w, "--timeout-ms", "200", "--", "sleep", "5")
    f["limit.output-too-large"] = lambda w: step(w, "--max-output", "1000", "--", "yes")
    f["limit.input-too-large"] = lambda w: flow(w.d, "--record", "records", "--stdin", "--max-stdin", "10", "--", "cat", stdin=b"x" * 100)[1]
    f["path.dotdot"] = lambda w: step(w, "--in", "../x", "--", "true")
    f["path.absolute"] = lambda w: step(w, "--in", "/etc/passwd", "--", "true")
    f["path.empty"] = lambda w: step(w, "--in", "in.txt,,x", "--", "true")
    f["io.not-found"] = lambda w: step(w, "--in", "absent.txt", "--", "true")
    f["args.unknown-flag"] = lambda w: step(w, "--nosuchflag", "--", "true")
    f["args.missing-operand"] = lambda w: run(FLOW, ["step", "--root", ".", "--record", "records"], w.d)[1]

    # flow-records
    f["flow.verb#records"] = lambda w: run(RECORDS, ["bogus", "--root", "."], w.d)[1]
    f["flow.record.unknown"] = lambda w: recs(w.d, "show", "records", "0" * 64)[1]

    def ambiguous(w):
        for _ in range(2):
            flow(w.d, "--record", "records", "--", "sh", "-c", "echo $$")
        names = w.files()
        return recs(w.d, "show", "records", names[0][:64])[1]
    f["flow.record.ambiguous"] = ambiguous

    def too_large(w):
        (w.d / "records" / ("a" * 64 + "." + "b" * 64 + ".json")).write_bytes(b"x" * 262145)
        return recs(w.d, "show", "records", "a" * 64)[1]
    f["flow.record.too-large"] = too_large

    def checked(kind):
        def go(w):
            name, _ = make_record(w)
            if kind == "inputs":
                (w.d / "in.txt").write_text("changed\n")
            elif kind == "outputs":
                (w.d / "out.txt").unlink()
            return recs(w.d, "check", "records", name[:64])[1]
        return go
    f["flow.check.inputs-changed"] = checked("inputs")
    f["flow.check.outputs-changed"] = checked("outputs")

    def program_changed(w):
        rc, doc, _ = flow(w.d, "--record", "records", "--", "tool")
        must(rc == 0, "the tool step failed: %s" % doc)
        (pathlib.Path(PROGRAMS) / "tool").write_text("#!/bin/sh\necho changed\n")
        os.chmod(pathlib.Path(PROGRAMS) / "tool", 0o755)
        try:
            return recs(w.d, "check", "records", doc["data"]["record"]["id"])[1]
        finally:
            (pathlib.Path(PROGRAMS) / "tool").write_text("#!/bin/sh\necho original\n")
            os.chmod(pathlib.Path(PROGRAMS) / "tool", 0o755)
    f["flow.check.program-changed"] = program_changed
    return f


def g3_refusals():
    fx = fixtures()
    seen = set()
    for tag, make in sorted(fx.items()):
        with World() as w:
            doc = make(w)
            got = rule(doc)
            want = tag.split("#")[0]
            must(got == want, "fixture %s answered %r" % (tag, got))
            seen.add(want)
    # every tag the two programs register, flow.* and limit.*, has a fixture; no fixture raises a tag outside the registered ones
    registered = set()
    for binary in (FLOW, RECORDS):
        rules = json.loads(subprocess.run([binary, "introspect"], capture_output=True).stdout)["rules"]
        names = [r["rule"] for r in rules]
        registered |= set(names)
    for tag in sorted(registered):
        if tag.startswith("flow.") or tag.startswith("limit."):
            must(tag in seen, "the rule %s is registered and no fixture raises it" % tag)
    for tag in sorted(seen):
        must(tag in registered, "a fixture raised %s, which is not registered" % tag)
    return len(seen)


# ---- G4 bounds ---------------------------------------------------------------

def g4_bounds():
    with World() as w:
        t = time.time()
        rc, doc, _ = flow(w.d, "--record", "records", "--timeout-ms", "300", "--", "sleep", "5")
        took = time.time() - t
        must(rule(doc) == "limit.timeout" and took < 1.5, "a 300 ms deadline took %.2f s (%s)" % (took, rule(doc)))
        must(doc["data"]["outcome"]["timed_out"] is True and doc["data"]["outcome"]["exit"] is None, "a timeout must be recorded as one")
        must(len(w.files()) == 1, "a timed-out step must leave its record")
        rc, doc, _ = flow(w.d, "--record", "records", "--max-output", "1000", "--", "yes")
        must(rule(doc) == "limit.output-too-large" and doc["data"]["outcome"]["truncated"]["stdout"] is True, "the output cap did not end `yes`")
    # refused before the child starts: a child that leaves a marker must not have run
    refusals = {
        "65 declared files": ["--in", ",".join("f%d" % i for i in range(65))],
        "a missing input": ["--in", "absent.txt"],
        "a `..` path": ["--in", "../in.txt"],
        "a bad flag value": ["--timeout-ms", "0"],
    }
    for label, extra in refusals.items():
        with World() as w:
            rc, doc, _ = flow(w.d, "--record", "records", *extra, "--", "sh", "-c", "touch marker")
            must(rc != 0 and not (w.d / "marker").exists(), "%s: refused too late (the child ran)" % label)
    with World() as w:
        rc, doc, _ = flow(w.d, "--record", "records", "--", "sh", "-c", "touch marker", *["a"] * 4100)
        must(rc != 0 and not (w.d / "marker").exists(), "4100 arguments: refused too late")
    with World() as w:
        for i in range(1000):
            (w.d / "records" / ("x%04d.json" % i)).write_text("")
        rc, doc, _ = flow(w.d, "--record", "records", "--", "sh", "-c", "touch marker")
        must(rule(doc) == "flow.record.too-many" and not (w.d / "marker").exists(), "a full record directory must refuse before the child starts")


# ---- G5 determinism claims ---------------------------------------------------

def g5_determinism():
    with World() as w:
        flow(w.d, "--record", "records", "--deterministic", "--", "sh", "-c", "echo $$")
        before = w.files()
        rc, doc, _ = flow(w.d, "--record", "records", "--deterministic", "--", "sh", "-c", "echo $$")
        must(rule(doc) == "flow.step.not-deterministic" and w.files() == before, "a falsified determinism claim must be refused and write nothing")
    with World() as w:
        for _ in range(2):
            flow(w.d, "--record", "records", "--", "sh", "-c", "echo $$")
        must(len(w.files()) == 2, "an undeclared step must keep every distinct outcome, found %d" % len(w.files()))
        rc, doc, _ = recs(w.d, "list", "records")
        must(doc["ok"] and doc["data"]["count"] == 2, "list must show both attempts")


# ---- G7 check ----------------------------------------------------------------

def g7_check():
    with World() as w:
        name, doc = make_record(w)
        rc, doc, _ = recs(w.d, "check", "records", name[:64])
        must(rc == 0 and doc["data"]["program_matches"] and doc["data"]["inputs_checked"] == 1 and doc["data"]["outputs_checked"] == 1, "an untouched step must check clean: %s" % doc)
        (w.d / "out.txt").write_text("tampered\n")
        rc, doc, _ = recs(w.d, "check", "records", name[:64])
        must([e["rule"] for e in doc["errors"]] == ["flow.check.outputs-changed"], "a changed output must be named: %s" % [e["rule"] for e in doc["errors"]])
        must(doc["errors"][0]["detail"]["path"] == "out.txt" and doc["errors"][0]["detail"]["recorded"] != doc["errors"][0]["detail"]["found"], "the path and both digests must be in the detail")


# ---- G11 answer output (the stream is in the answer and never in the record) ------

def g11_answer_output():
    # the program builds its output from pieces, so the words of the output are not among the arguments the record keeps
    script = "a=pay; echo ${a}load; echo ${a}err >&2"
    with World() as w:
        rc, doc, _ = flow(w.d, "--record", "records", "--answer-output", "--", "sh", "-c", script)
        must(rc == 0 and doc["data"]["stdout"] == "payload\n" and doc["data"]["stderr"] == "payerr\n", "the streams must be in the answer: %s" % doc["data"])
        record = (w.d / "records" / w.files()[0]).read_bytes()
        must(b"payload" not in record and b"payerr" not in record, "a stream's text must never be in the record")
        rc, doc, _ = flow(w.d, "--record", "records", "--", "sh", "-c", script)
        must("stdout" not in doc["data"], "without --answer-output the answer carries no stream text")


# ---- G12 the standard input and output of a step as files (design section 14, G2; gate P3) -------------------------------------------------

def sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def read_record(w, rec):
    return json.loads((w.d / "records" / rec["file"]).read_text())


def g12_stdio_files():
    with World() as w:
        w.d.joinpath("in.txt").write_bytes(b"b\na\n")
        # a pipeline of two steps joined by a file: the second step's recorded input digest is the first step's recorded output digest
        rc, d1, _ = flow(w.d, "--record", "records", "--stdin-file", "in.txt", "--stdout-file", "a.txt", "--out", "a.txt", "--", "cat")
        must(rc == 0 and d1["ok"], "step 1: %s" % d1)
        rc, d2, _ = flow(w.d, "--record", "records", "--stdin-file", "a.txt", "--stdout-file", "b.txt", "--out", "b.txt", "--", "cat")
        must(rc == 0 and d2["ok"], "step 2: %s" % d2)
        r1, r2 = read_record(w, d1["data"]["record"]), read_record(w, d2["data"]["record"])
        want = sha(b"b\na\n")
        must(w.d.joinpath("a.txt").read_bytes() == b"b\na\n" and w.d.joinpath("b.txt").read_bytes() == b"b\na\n", "the files hold the program's output")
        must(r1["outcome"]["out"][0]["sha256"] == want and r1["outcome"]["stdout"]["sha256"] == want, "step 1 records the output digest")
        must(r2["inputs"]["stdin"]["sha256"] == r1["outcome"]["out"][0]["sha256"], "step 2's input digest must be step 1's output digest")
        must(r2["inputs"]["stdin"]["bytes"] == 4, "the recorded input size")
        # the same step again is the same record, and an overwritten output is the program's new output
        rc, d1b, _ = flow(w.d, "--record", "records", "--stdin-file", "in.txt", "--stdout-file", "a.txt", "--out", "a.txt", "--", "cat")
        must(d1b["data"]["record"]["written"] is False and d1b["data"]["record"]["file"] == d1["data"]["record"]["file"], "the same step is the same record")
        w.d.joinpath("in.txt").write_bytes(b"zzz\n")
        rc, d3, _ = flow(w.d, "--record", "records", "--stdin-file", "in.txt", "--stdout-file", "a.txt", "--out", "a.txt", "--", "cat")
        must(w.d.joinpath("a.txt").read_bytes() == b"zzz\n" and d3["data"]["record"]["file"] != d1["data"]["record"]["file"], "a rerun replaces the file")
        # a subdirectory that exists, and one that does not
        (w.d / "sub").mkdir()
        rc, d4, _ = flow(w.d, "--record", "records", "--stdin-file", "in.txt", "--stdout-file", "sub/x.txt", "--out", "sub/x.txt", "--", "cat")
        must(rc == 0 and w.d.joinpath("sub/x.txt").read_bytes() == b"zzz\n", "a file in a subdirectory")
        rc, d5, _ = flow(w.d, "--record", "records", "--stdin-file", "in.txt", "--stdout-file", "nosub/x.txt", "--out", "nosub/x.txt", "--", "cat")
        must(rc != 0 and rule(d5) == "io.not-found" and not (w.d / "nosub").exists(), "a missing directory is io.not-found and nothing is made: %s" % rule(d5))
        # paths are checked as every declared path is
        for given, tag in (("../o", "path.dotdot"), ("/abs/o", "path.absolute")):
            rc, d6, _ = flow(w.d, "--record", "records", "--stdin-file", "in.txt", "--stdout-file", given, "--out", given, "--", "cat")
            must(rule(d6) == tag, "%s -> %s" % (given, rule(d6)))
        rc, d7, _ = flow(w.d, "--record", "records", "--stdin-file", "../in.txt", "--", "cat")
        must(rule(d7) == "path.dotdot", "stdin-file path: %s" % rule(d7))
        rc, d8, _ = flow(w.d, "--record", "records", "--stdin-file", "missing.txt", "--", "cat")
        must(rule(d8) == "io.not-found", "a missing stdin file: %s" % rule(d8))
        rc, d9, _ = flow(w.d, "--record", "records", "--stdin-file", "in.txt", "--max-stdin", "2", "--", "cat")
        must(rule(d9) == "limit.input-too-large", "a stdin file above --max-stdin: %s" % rule(d9))
        # a program that is killed leaves no standard-output file
        before = sorted(os.listdir(w.d / "records"))
        rc, d10, _ = flow(w.d, "--record", "records", "--timeout-ms", "100", "--stdout-file", "k.txt", "--out", "k.txt", "--", "sleep", "5")
        must(rule(d10) == "limit.timeout" and not (w.d / "k.txt").exists(), "a killed program writes no file: %s" % rule(d10))
        # a refused step starts nothing and writes nothing
        before = sorted(os.listdir(w.d / "records"))
        rc, d11, _ = flow(w.d, "--record", "records", "--stdout-file", "n.txt", "--", "touch", "side-effect")
        must(rule(d11) == "flow.stdout.undeclared" and not (w.d / "side-effect").exists() and sorted(os.listdir(w.d / "records")) == before, "an undeclared stdout file refuses before anything runs")


# ---- G10 files ---------------------------------------------------------------

def g10_files():
    for d in ("lib", "tools", "scripts", "tests"):
        for p in (ROOT / d).rglob("*"):
            if p.is_file() and p.suffix in (".cho", ".py", ".sh", ".js"):
                n = len(p.read_text().splitlines())
                must(n <= 2000, "%s has %d lines (the budget is 2000)" % (p, n))


GATES = [("G1 canonical", g1_canonical), ("G2 damage", g2_damage), ("G3 refusals", g3_refusals), ("G4 bounds", g4_bounds),
         ("G5 determinism", g5_determinism), ("G7 check", g7_check), ("G10 files", g10_files), ("G11 answer output", g11_answer_output), ("G12 stdio files", g12_stdio_files)]


def main():
    want = sys.argv[1:]
    failed = 0
    for name, fn in GATES:
        if want and not any(name.lower().startswith(x.lower()) for x in want):
            continue
        t = time.time()
        try:
            n = fn()
            print("ok    %-16s (%.1f s%s)" % (name, time.time() - t, "" if n is None else ", %d cases" % n))
        except AssertionError as e:
            failed += 1
            print("FAIL  %-16s %s" % (name, e))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
