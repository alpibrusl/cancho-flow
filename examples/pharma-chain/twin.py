#!/usr/bin/env python3
"""The digital twin of the pharma chain (docs/use-cases.md).

    python3 twin.py generate --world WORLD.json --seed N --size small|large --out DIR [--tables core,dispensing] [--overwrite]

Writes items.csv, pharmacies.csv, patients.csv and truth.json into DIR (a relative path beneath the working directory). The same world, seed
and size give the same bytes. On a refusal: one JSON line on standard error with a rule tag `twin.<name>` and a repair, exit status 2.
"""
import json
import os
import sys

sys.dont_write_bytecode = True  # a step that writes only what it declares: no __pycache__ beside the library
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from twinlib import core, world  # noqa: E402
from twinlib.world import TwinError  # noqa: E402


def refuse(e):
    sys.stderr.write(json.dumps({"ok": False, "error": {"rule": e.rule, "message": e.message, "repair": e.repair}}, sort_keys=True, separators=(",", ":")) + "\n")
    return 2


def parse_args(argv):
    if not argv or argv[0] != "generate":
        raise TwinError("twin.usage", "the command is `twin.py generate`", "python3 twin.py generate --world W --seed N --size small|large --out DIR")
    opts, i = {"overwrite": False}, 1
    while i < len(argv):
        a = argv[i]
        if a == "--overwrite":
            opts["overwrite"] = True
            i += 1
        elif a in ("--world", "--seed", "--size", "--out", "--tables") and i + 1 < len(argv):
            opts[a[2:]] = argv[i + 1]
            i += 2
        else:
            raise TwinError("twin.usage", "unknown or unfinished argument %r" % a, "python3 twin.py generate --world W --seed N --size small|large --out DIR")
    for k in ("world", "seed", "size", "out"):
        if k not in opts:
            raise TwinError("twin.usage", "missing --%s" % k, "python3 twin.py generate --world W --seed N --size small|large --out DIR")
    tabs = tuple(sorted(set(opts.get("tables", "core,dispensing").split(","))))
    if not tabs or any(t not in ("core", "dispensing") for t in tabs) or "core" not in tabs:
        raise TwinError("twin.bad-tables", "--tables is core or core,dispensing", "use --tables core,dispensing")
    opts["tables"] = tabs
    if opts["size"] not in world.SIZES:
        raise TwinError("twin.bad-size", "the size is small or large", "use --size small or --size large")
    s = opts["seed"]
    if not s.isascii() or not s.isdigit() or len(s) > 18:
        raise TwinError("twin.bad-seed", "the seed is a non-negative integer of at most 18 digits", "use --seed 20261112")
    opts["seed"] = int(s)
    out = opts["out"]
    if not out or os.path.isabs(out) or ".." in out.replace("\\", "/").split("/") or "\x00" in out:
        raise TwinError("twin.bad-path", "--out must be a relative path with no `..`", "use a directory beneath the working directory")
    return opts


def main(argv):
    try:
        o = parse_args(argv)
        try:
            with open(o["world"], "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            raise TwinError("twin.world-unreadable", "the world file cannot be read", "check the path of --world")
        w = world.parse(text)
        files, _ = core.generate(w, o["seed"], o["size"], o["tables"])
        if os.path.exists(o["out"]) and (not os.path.isdir(o["out"]) or os.listdir(o["out"])) and not o["overwrite"]:
            raise TwinError("twin.exists", "the output directory exists and is not empty", "use a new directory or add --overwrite")
        os.makedirs(o["out"], exist_ok=True)
        for name, data in files.items():
            os.makedirs(os.path.dirname(os.path.join(o["out"], name)), exist_ok=True)
            with open(os.path.join(o["out"], name), "w", encoding="utf-8", newline="\n") as f:
                f.write(data)
        return 0
    except TwinError as e:
        return refuse(e)
    except OSError:
        return refuse(TwinError("twin.io", "the output could not be written", "check that --out is a writable directory"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
