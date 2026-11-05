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
STEP = "tools/flow/stepper.cho"
RUN = "tools/flow/runplan.cho"
PLAN = "lib/flow/plan.cho"
BODY = "tools/flow/flow.cho"   # the command line of `flow step` and `flow run`
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
    (BODY, "cli.has(parsed, table, \"stdin\") || cli.has(parsed, table, \"stdin-file\");", "cli.has(parsed, table, \"stdin\") || false;", ["G12"],
     "the standard input from a file is not recorded"),
    (BODY, "if cli.has(parsed, table, \"stdin\") && cli.has(parsed, table, \"stdin-file\") {", "if false && cli.has(parsed, table, \"stdin\") && cli.has(parsed, table, \"stdin-file\") {", ["G3"],
     "--stdin and --stdin-file together are accepted"),
    (BODY, "} else if big {", "} else if false {", ["G12"],
     "a standard-input file above --max-stdin is accepted"),
    ("lib/flow/argvp.cho", "            seen = seen + 1;\n            from = i + 1;\n        }\n        i = i + 1;\n    }\n    return p[0..0];", "            seen = seen + 1;\n            from = i + 2;\n        }\n        i = i + 1;\n    }\n    return p[0..0];", ["G1", "G3", "G12", "G5"],
     "a packed argument after the first starts one byte late"),
    (RUN, "                    go = code != sp.when_n;", "                    go = code == sp.when_n;", ["G14"],
     "exit_not selects the steps that exit is for"),
    (RUN, "                if state != 1 {\n                    go = false;", "                if state == 0 {\n                    go = false;", ["G14"],
     "a condition on a skipped step reads the exit it never had"),
    (RUN, "        e = check_plan(heap, fs, root, text, n, e);", "        e = e;", ["G13"],
     "the plan is not checked before it runs"),
    (RUN, "    if known(ids, id) {", "    if false && known(ids, id) {", ["G13"],
     "two steps with one id are accepted"),
    (RUN, "if len(plan.after_of(spec)) > 0 && !known(ids, plan.after_of(spec)) {", "if false && len(plan.after_of(spec)) > 0 && !known(ids, plan.after_of(spec)) {", ["G13"],
     "`after` may name a later step"),
    (RUN, "if spec.when_kind != 0 && !known(ids, plan.when_step_of(spec)) {", "if false && spec.when_kind != 0 && !known(ids, plan.when_step_of(spec)) {", ["G13"],
     "`when` may name a step that is not earlier"),
    (RUN, "|| !bytes.equal(step1, step2) || n1 != n2 {", "|| !bytes.equal(step1, step2) {", ["G13"],
     "exit 0 and exit_not 1 count as exclusive"),
    (RUN, "return (kind1 == 1 && kind2 == 2) || (kind1 == 2 && kind2 == 1);", "return kind1 != kind2;", ["G13"],
     "a step with no condition counts as exclusive with one that has"),
    (RUN, "        if did_stop {\n            k = n;", "        if did_stop {\n            k = k + 1;", ["G14"],
     "the plan goes on after the first failure"),
    (RUN, "            start = rf;", "            start = 0;", ["G14"],
     "a resume starts again from the first step"),
    (RUN, "same = bytes.equal(buffer.bytes(wb), src[cut + 10..cut + 74]);", "same = true;", ["G16"],
     "the check of a plan record is not compared"),
    (RUN, "same_plan = bytes.equal(buffer.bytes(shb), plan_hex);", "same_plan = true;", ["G15"],
     "a plan record of another plan is accepted for a resume"),
    (RUN, "did_stop = buffer.size(stz) > 0;", "did_stop = true;", ["G15"],
     "a plan record of a run that finished is accepted for a resume"),
    (RUN, "    } else if n > max_steps {", "    } else if n > max_steps + 1000 {", ["G13", "G15", "G3"],
     "the bound on steps is not enforced"),
    (RUN, "                    t_ms = sp.timeout;", "                    t_ms = timeout_default;", ["G14"],
     "a step's own timeout is ignored"),
    (RUN, "if cut <= 0 || !bytes.equal(src[cut..cut + 10], \",\\\"check\\\":\\\"\") || !bytes.equal(src[cut + 74..len(src)], \"\\\"}\\n\") {", "if cut <= 0 || !bytes.equal(src[cut..cut + 10], \",\\\"check\\\":\\\"\") {", ["G16"],
     "bytes after the check of a plan record are not compared"),
    (PLAN, "    } else if (seen / pow2(m)) % 2 == 1 {", "    } else if false && (seen / pow2(m)) % 2 == 1 {", ["G13"],
     "a member given twice is accepted"),
    (PLAN, "                if has_byte(b, 0) {", "                if false && has_byte(b, 0) {", ["G13"],
     "a zero byte in an argument is accepted"),
    (PLAN, "} else if len(b) == 0 || has_byte(b, ',') {", "} else if len(b) == 0 {", ["G13"],
     "a comma in a path is accepted"),
    (PLAN, "    if len(id) < 1 || len(id) > 64 {", "    if len(id) < 1 || len(id) > 640 {", ["G13"],
     "an id of 65 characters is accepted"),
    (PLAN, "if m == 12 && (n < 1 || n > 600000) {", "if m == 12 && (n < 0 || n > 600000) {", ["G13"],
     "a timeout of 0 is accepted"),
    (PLAN, "if when_n < 0 || when_n > 255 {", "if when_n < 0 || when_n > 2550 {", ["G13"],
     "an exit status of 256 is accepted"),
    (STEP, "if len(stdout_file) > 0 && killed == 0 {", "if len(stdout_file) > 0 && killed == 0 && false {", ["G14", "G12"],
     "the standard output of a plan step is not written"),
    (READ, "if !bytes.equal(buffer.bytes(wb), src[check_at + 10..check_at + 74]) {", "if false && !bytes.equal(buffer.bytes(wb), src[check_at + 10..check_at + 74]) {", ["G17"],
     "the check of a plan record is not compared"),
    (READ, "} else if !bytes.equal(buffer.bytes(ib), src[len(prefix)..id_end]) {", "} else if false && !bytes.equal(buffer.bytes(ib), src[len(prefix)..id_end]) {", ["G17"],
     "the id of a plan record is not the hash of its claim"),
    (READ, "} else if len(name) < 64 || !bytes.equal(name[0..64], src[len(prefix)..id_end]) {", "} else if false {", ["G17"],
     "a plan record under another id's name is accepted"),
    (READ, "if errno != 0 || !bytes.equal(buffer.bytes(fb), buffer.bytes(rb)) {", "if errno != 0 {", ["G17"],
     "an edited plan file is not reported"),
    (READ, "var same = have == want;", "var same = true;", ["G17"],
     "a plan record and a step record may disagree about the exit"),
    (READ, "    if now > before {\n        var d = fail.open_in", "    if now > before + 1000 {\n        var d = fail.open_in", ["G17"],
     "a directory with a bad record is not named"),
    (READ, "if json_name(name) && !plan_name(name) {", "if json_name(name) {", ["G17"],
     "list reads a plan record as a step record"),
    (READ, "|| !bytes.equal(src[check_at + 74..len(src)], \"\\\"}\\n\") ||", "||", ["G17"],
     "bytes after the check of a plan record are not compared"),
    (READ, "if buffer.size(runb) == 129 {", "if buffer.size(runb) == 1290 {", ["G17"],
     "the step records a plan names are not checked"),
    (READ, "if !json_name(name) && len(name) > 0 && !bytes.equal(name, \".\")", "if false && len(name) > 0 && !bytes.equal(name, \".\")", ["G17"],
     "the directories under DIR are not checked"),
]


# Survivors that are not faults of a gate: the edit changes nothing the program can do.
EXPLAINED = {
    "a step with no condition counts as exclusive with one that has":
        "equivalent: `exclusive` returns false first when the first step has no condition (an empty `when` step), and when both have one the kinds are 1 or 2, so `kind1 != kind2` is `(1,2) or (2,1)`",
    "a plan record of a run that finished is accepted for a resume":
        "equivalent: a finished run's `stopped` is empty, and no step id is empty (an id is 1 to 64 characters), so the search for the step it stopped at fails and the record is refused anyway",
}


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
            if not killed and what in EXPLAINED:
                print("explained mutant %2d: %s   (%s)" % (n, what, EXPLAINED[what]))
                continue
            print("%s mutant %2d: %s%s" % ("killed  " if killed else "SURVIVED", n, what, "" if killed else "   (gates run: %s)" % " ".join(gates)))
            survivors += 0 if killed else 1
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
