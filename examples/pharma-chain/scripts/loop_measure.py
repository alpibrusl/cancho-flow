#!/usr/bin/env python3
"""U6: the measured run of the loop on this machine (docs/use-cases.md section 7a, M1 to M4, committed before this was written).

    CANCHO=<compiler> [SCIPY_PYTHON=...] python3 scripts/loop_measure.py [--runs 5]

N sequential runs of one loop each (`loop.py --once`, fresh directory, `ml --threads` at its default) started only when the load average is below 0.3, then one run with `--threads 4`.
Prints the machine, the load at each start, the wall time of the steps of each run (judging is not timed), the minimum, median and maximum, whether the digests agree and equal U5's, the stages and the shares by program of the fastest run.
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent.parent
U5_DIGEST = "a701f5de6ac65856"
LOAD_LIMIT = 0.3


def load1():
    return float(open("/proc/loadavg").read().split()[0])


def one(td, tag, env_extra=None):
    d = pathlib.Path(td) / tag
    while load1() >= LOAD_LIMIT:
        time.sleep(5)
    start_load = load1()
    env = dict(os.environ, **(env_extra or {}))
    t0 = time.time()
    r = subprocess.run([sys.executable, str(HERE / "scripts" / "loop.py"), "--once", str(d)], capture_output=True, text=True, env=env)
    total = time.time() - t0
    if r.returncode != 0:
        sys.exit("loop_measure: run %s stopped: %s" % (tag, (r.stdout + r.stderr)[-400:]))
    rep = json.loads((d / "report.json").read_text())
    tm = json.loads((d / "timing.json").read_text())
    digest = hashlib.sha256((d / "root" / "summary.json").read_bytes()).hexdigest()
    return {"tag": tag, "start_load": start_load, "wall_s": tm["wall_s"], "total_s": total, "digest": digest, "problems": rep["problems"], "stages_s": tm["stages_s"], "by_program_ms": tm["by_program_ms"], "steps": tm["steps"]}


def main(argv):
    n = int(argv[argv.index("--runs") + 1]) if "--runs" in argv else 5
    cpu = next((ln.split(":", 1)[1].strip() for ln in open("/proc/cpuinfo") if ln.startswith("model name")), "?")
    print("machine: %s, %d cores, %s; ml --threads default 1; SCIPY_PYTHON %s" % (cpu, os.cpu_count(), os.uname().release, "set" if os.environ.get("SCIPY_PYTHON") else "not set"))
    with tempfile.TemporaryDirectory() as td:
        runs = [one(td, "r%d" % i) for i in range(n)]
        t4 = one(td, "t4", {"LOOP_ML_THREADS": "4"})
    for r in runs + [t4]:
        print("run %-3s load at start %.2f: steps %.1f s (whole process %.1f s), summary sha256 %s, %d problems" % (r["tag"], r["start_load"], r["wall_s"], r["total_s"], r["digest"][:16], len(r["problems"])))
    ws = sorted(r["wall_s"] for r in runs)
    mn, md, mx = ws[0], ws[len(ws) // 2], ws[-1]
    print("M1 the steps of one loop: minimum %.1f s, median %.1f s, maximum %.1f s; maximum/minimum %.2f (%s, limit 1.25)" % (mn, md, mx, mx / mn, "not noisy" if mx / mn <= 1.25 else "NOISY"))
    same = len({r["digest"] for r in runs}) == 1
    print("M2 the digests of the %d runs: %s; equal to U5's (%s): %s" % (n, "all equal" if same else "DIFFER", U5_DIGEST, "yes" if runs[0]["digest"].startswith(U5_DIGEST) else "NO (%s)" % runs[0]["digest"][:16]))
    print("M3 --threads 4 on every ml fit: summary %s the runs at 1 thread" % ("byte for byte equal to" if t4["digest"] == runs[0]["digest"] else "DIFFERS from"))
    best = min(runs, key=lambda r: r["wall_s"])
    tot = sum(best["by_program_ms"].values())
    print("M4 the fastest run (%.1f s of steps): stages %s; by program %s" % (best["wall_s"], ", ".join("%s %.1f s" % (k, v) for k, v in best["stages_s"].items()),
          ", ".join("%s %.1f s (%.0f%%)" % (k, v / 1000.0, 100.0 * v / tot) for k, v in sorted(best["by_program_ms"].items(), key=lambda kv: -kv[1]))))
    bad = [r["tag"] for r in runs + [t4] if r["problems"]]
    if bad or not same or t4["digest"] != runs[0]["digest"]:
        print("loop_measure: a problem (runs with problems: %s)" % (bad or "none"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
