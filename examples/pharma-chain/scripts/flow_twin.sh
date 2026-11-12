#!/bin/sh
# G1 through `flow`: the twin run as a recorded step twice, in two copies of the tree, gives the same record (docs/use-cases.md sections 2 and 6).
# usage: CANCHO=<compiler> sh examples/pharma-chain/scripts/flow_twin.sh      (builds a `flow` whose programs directory holds `python3`)
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
repo=$(cd "$here/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/programs"
ln -s "$(command -v python3)" "$tmp/programs/python3"
python3 "$repo/scripts/flow_build.py" --programs "$tmp/programs" --out "$tmp/flow" --bin flow >/dev/null
for n in 1 2; do
  mkdir -p "$tmp/r$n/rec"
  cp -r "$here/twin.py" "$here/twinlib" "$here/world.json" "$tmp/r$n/"
  rm -rf "$tmp/r$n/twinlib/__pycache__"
  (cd "$tmp/r$n" && "$tmp/flow" step --root . --record rec \
      --in twin.py,twinlib/__init__.py,twinlib/prng.py,twinlib/world.py,twinlib/core.py,world.json \
      --out out/items.csv,out/pharmacies.csv,out/patients.csv,out/truth.json \
      -- python3 twin.py generate --world world.json --seed 20261112 --size small --out out > "$tmp/step$n.json")
done
id1=$(ls "$tmp/r1/rec"); id2=$(ls "$tmp/r2/rec")
echo "record 1: $id1"
echo "record 2: $id2"
[ "$id1" = "$id2" ] || { echo "flow_twin: the two records differ" >&2; exit 1; }
cmp "$tmp/r1/rec/$id1" "$tmp/r2/rec/$id2" || { echo "flow_twin: same name, different bytes" >&2; exit 1; }
# a changed input must change the record: one more patient in the world
sed 's/"patients": 600/"patients": 601/' "$here/world.json" > "$tmp/r2/world.json"
rm -rf "$tmp/r2/out" "$tmp/r2/rec" && mkdir "$tmp/r2/rec"
(cd "$tmp/r2" && "$tmp/flow" step --root . --record rec \
    --in twin.py,twinlib/__init__.py,twinlib/prng.py,twinlib/world.py,twinlib/core.py,world.json \
    --out out/items.csv,out/pharmacies.csv,out/patients.csv,out/truth.json \
    -- python3 twin.py generate --world world.json --seed 20261112 --size small --out out >/dev/null)
id3=$(ls "$tmp/r2/rec")
[ "$id3" != "$id1" ] || { echo "flow_twin: a changed world gave the same record" >&2; exit 1; }
echo "flow_twin: ok (two runs, one record; a changed world, another)"
