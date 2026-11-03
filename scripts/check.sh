#!/bin/sh
# The gate: CANCHO=<pinned cancho> scripts/check.sh   (the compiler is the commit in cancho.toml; `cancho install` first)
# Authority (G8), the gates G1 to G7 and G10, and every mutant killed.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
: "${CANCHO:=cancho}"
export CANCHO
cd "$here"
"$CANCHO" install >/dev/null
"$CANCHO" build --bin flow >/dev/null
"$CANCHO" build --bin flow-records >/dev/null
python3 scripts/manifest.py --check                    # G8: the derived rows equal the committed ones and sit inside the ceiling
scripts/test_programs.sh >/dev/null
export FLOW="$here/build/test/flow" FLOW_RECORDS="$here/build/test/flow-records" PROGRAMS="$here/build/test/programs"
python3 tests/gates.py
python3 scripts/mutants.py
echo "gate: ok"
