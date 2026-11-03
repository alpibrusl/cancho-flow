#!/usr/bin/env python3
"""Build `flow` (and `flow-records`) for one deployment: the programs directory baked in.

    python3 scripts/flow_build.py --programs /opt/agent/programs --out build/flow-agent [--bin flow|flow-records]

`flow` starts only programs found in one directory, and that directory is the allow-list. `narrow` takes a literal (cancho
docs/processes.md section 7.1), so the directory is in the source: this script replaces it everywhere it appears (lib/flow/config.cho,
and `Exec(..)`, `exec(..)` and `narrow(..)` in tools/flow) in a scratch copy and builds that, as cancho-tools' scripts/run_build.py does for
`run`. The variant's authority is derived like any other: its row says `exec("<dir>")`, which is what a supervisor reads before granting it.
The committed source says DEFAULT, which is what `cancho build` builds and what the manifest records.

The compiler is $CANCHO, or `cancho` on PATH; `cancho install` must have run (build/deps).
"""

import argparse
import os
import pathlib
import posixpath
import subprocess
import sys
import tempfile
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT = "/opt/cancho-flow/programs"


def valid(directory):
    return (directory.startswith("/") and posixpath.normpath(directory) == directory and directory != "/"
            and '"' not in directory and "\\" not in directory and "\n" not in directory)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--programs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bin", default="flow", choices=["flow", "flow-records"])
    ap.add_argument("--tree", default=str(ROOT), help="build the sources of this tree (a mutant's scratch copy) instead of this repository's")
    a = ap.parse_args()
    tree = pathlib.Path(a.tree)
    if not valid(a.programs):
        sys.exit("--programs must be a normalised absolute path without quotes, backslashes or newlines")
    proj = tomllib.loads((ROOT / "cancho.toml").read_text())
    entry = [b for b in proj["bin"] if b["name"] == a.bin][0]
    deps = sorted(str(x) for x in (ROOT / "build" / "deps").glob("*.cho"))
    if not deps:
        sys.exit("build/deps is empty; run `cancho install` first")
    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        files = []
        for s in entry["sources"]:
            src = tree / s
            for f in (sorted(src.glob("*.cho")) if src.is_dir() else [src]):
                dst = scratch / f.relative_to(tree)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(f.read_text().replace(DEFAULT, a.programs))
                files.append(str(dst))
        out = pathlib.Path(a.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([os.environ.get("CANCHO", "cancho"), "build", *files, *deps, "--std", "-o", str(out)], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("build failed:\n" + r.stdout + r.stderr)
    print("built %s (programs: %s)" % (out, a.programs))


if __name__ == "__main__":
    main()
