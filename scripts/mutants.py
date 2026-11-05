#!/usr/bin/env python3
"""Mutants: each breaks one rule in a scratch copy of the source, rebuilds, and requires a gate to fail (docs/design.md section 10:
"all killed, or each survivor explained"). A gate that cannot fail proves nothing.

    FLOW=... FLOW_RECORDS=... PROGRAMS=... python3 scripts/mutants.py [--only N]

FLOW and FLOW_RECORDS are the unmutated programs built for PROGRAMS (scripts/test_programs.sh); a mutant replaces the one it changes.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROGRAMS = os.environ["PROGRAMS"]

SCAN = "lib/flow/scan.cho"
STEP = "tools/flow/flow.cho"
READ = "tools/flow-records/records.cho"

MUTANTS = [
    (SCAN, "if !hash_equals(heap, t[0..before_check], t[check_at..check_at + 64]) {", "if false && !hash_equals(heap, t[0..before_check], t[check_at..check_at + 64]) {", ["G2"],
     "the check (every byte before it) is not compared"),
    (SCAN, "if !hash_equals(heap, t[inputs_a..inputs_b], t[id_at..id_at + 64]) {", "if false && !hash_equals(heap, t[inputs_a..inputs_b], t[id_at..id_at + 64]) {", ["G2"],
     "the id is not compared with the hash of inputs"),
    (SCAN, "if !hash_equals(heap, t[outcome_a..outcome_b], t[oid_at..oid_at + 64]) {", "if false && !hash_equals(heap, t[outcome_a..outcome_b], t[oid_at..oid_at + 64]) {", ["G2"],
     "the oid is not compared with the hash of outcome"),
    (SCAN, "if end + len(tail) != len(t) || !bytes.equal(t[end..len(t)], tail) {", "if end + len(tail) > len(t) || !bytes.equal(t[end..end + len(tail)], tail) {", ["G2"],
     "bytes after the record's end are not refused"),
    (STEP, "if deterministic && held.same_id_other_outcome {", "if false && held.same_id_other_outcome {", ["G5", "G3"],
     "a falsified determinism claim is accepted"),
    (STEP, "if held_records >= config.most_records() {", "if held_records >= config.most_records() + 1000 {", ["G4", "G3"],
     "the record bound is not enforced"),
    (STEP, "} else if (code != 0 || signal >= 0) && !allow_failure {", "} else if false && (code != 0 || signal >= 0) && !allow_failure {", ["G3"],
     "a failed child is not a refusal"),
    (STEP, "} else if code == 0 && missing_any {", "} else if false && code == 0 && missing_any {", ["G3"],
     "a declared output that was not left is not a refusal"),
    (STEP, "outcome = canon.boolean(heap, outcome, timed_out);", "outcome = canon.boolean(heap, outcome, false);", ["G4"],
     "a timeout is not recorded as one"),
    (STEP, "inputs = canon.raw(heap, inputs, buffer.bytes(ij));", "inputs = canon.raw(heap, inputs, \"\");", ["G3", "G7"],
     "the declared inputs are left out of the record"),
    ("lib/flow/files.cho", "if path.has_dotdot(given) {", "if false && path.has_dotdot(given) {", ["G3"],
     "a `..` in a declared path is accepted"),
    (READ, "if !program_match {", "if false && !program_match {", ["G3"],
     "a changed program is not reported by check"),
    (READ, "same = !recorded_missing && bytes.equal(buffer.bytes(hx), buffer.bytes(rc));", "same = true;", ["G3", "G7"],
     "a changed declared file is not reported by check"),
    (STEP, "if len(stdout_file) > 0 && killed == 0 {", "if len(stdout_file) > 0 {", ["G12"],
     "a killed program's standard output is written to the file"),
    (STEP, "    if !stdout_listed {", "    if false && !stdout_listed {", ["G12", "G3"],
     "a standard-output file that --out does not list is accepted"),
    (STEP, "write_declared(heap, fs, root, stdout_file, buffer.bytes(sot0));", "write_declared(heap, fs, root, stdout_file, \"\");", ["G12"],
     "the file written is empty"),
    (STEP, "cli.has(parsed, table, \"stdin\") || cli.has(parsed, table, \"stdin-file\");", "cli.has(parsed, table, \"stdin\") || false;", ["G12"],
     "the standard input from a file is not recorded"),
    (STEP, "if cli.has(parsed, table, \"stdin\") && cli.has(parsed, table, \"stdin-file\") {", "if false && cli.has(parsed, table, \"stdin\") && cli.has(parsed, table, \"stdin-file\") {", ["G3"],
     "--stdin and --stdin-file together are accepted"),
    (STEP, "} else if big {", "} else if false {", ["G12"],
     "a standard-input file above --max-stdin is accepted"),
    ("lib/flow/argvp.cho", "            seen = seen + 1;\n            from = i + 1;\n        }\n        i = i + 1;\n    }\n    return p[0..0];", "            seen = seen + 1;\n            from = i + 2;\n        }\n        i = i + 1;\n    }\n    return p[0..0];", ["G1", "G3", "G12", "G5"],
     "a packed argument after the first starts one byte late"),
]


def build(tree, which, out):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "flow_build.py"), "--programs", PROGRAMS, "--out", str(out), "--bin", which, "--tree", str(tree)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("a mutant did not build:\n" + r.stdout + r.stderr)


def main():
    only = None
    if "--only" in sys.argv:
        only = int(sys.argv[sys.argv.index("--only") + 1])
    survivors = 0
    for n, (path, old, new, gates, what) in enumerate(MUTANTS):
        if only is not None and n != only:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "tree"
            for d in ("lib", "tools", "generated"):
                shutil.copytree(ROOT / d, tree / d)
            f = tree / path
            text = f.read_text()
            if text.count(old) != 1:
                sys.exit("mutant %d: the text to break is not in %s exactly once (%d times)" % (n, path, text.count(old)))
            f.write_text(text.replace(old, new))
            env = dict(os.environ)
            flow, records = env["FLOW"], env["FLOW_RECORDS"]
            if path.startswith("tools/flow-records/"):
                records = str(pathlib.Path(tmp) / "fr")
                build(tree, "flow-records", records)
            elif path.startswith("tools/flow/"):
                flow = str(pathlib.Path(tmp) / "f")
                build(tree, "flow", flow)
            else:
                flow, records = str(pathlib.Path(tmp) / "f"), str(pathlib.Path(tmp) / "fr")
                build(tree, "flow", flow)
                build(tree, "flow-records", records)
            env.update(FLOW=flow, FLOW_RECORDS=records)
            r = subprocess.run([sys.executable, str(ROOT / "tests" / "gates.py")] + gates, env=env, capture_output=True, text=True)
            killed = r.returncode != 0
            print("%s mutant %2d: %s%s" % ("killed  " if killed else "SURVIVED", n, what, "" if killed else "   (gates run: %s)" % " ".join(gates)))
            survivors += 0 if killed else 1
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
