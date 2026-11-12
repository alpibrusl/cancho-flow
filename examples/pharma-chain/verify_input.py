#!/usr/bin/env python3
"""The standard input of `solve verify`: the model, a line holding exactly ---, then the claimed solution (docs/use-cases.md section 4.1).

    python3 verify_input.py MODEL.sol PLAN.json OUT
"""
import sys

sys.dont_write_bytecode = True


def main(argv):
    if len(argv) != 3:
        sys.stderr.write('{"ok":false,"error":{"rule":"plan.usage","message":"verify_input.py MODEL.sol PLAN.json OUT","repair":"give the three operands"}}\n')
        return 2
    model, plan, out = argv
    with open(out, "w", newline="\n") as f:
        f.write(open(model).read().rstrip("\n") + "\n---\n" + open(plan).read().rstrip("\n") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
