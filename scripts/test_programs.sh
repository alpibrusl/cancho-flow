#!/bin/sh
# The programs directory the gates run against, and the two programs built for it: build/test/{programs,flow,flow-records}.
# usage: scripts/test_programs.sh   (CANCHO and `cancho install` as for scripts/flow_build.py)
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
dir="$here/build/test/programs"
rm -rf "$dir"; mkdir -p "$dir"
for p in true false sleep cat sh printf yes touch; do
  ln -sf "$(which $p)" "$dir/$p"   # `command -v` names a shell builtin (true, printf) by its bare name, a link to itself
done
printf '#!/bin/sh\necho original\n' > "$dir/tool"; chmod 755 "$dir/tool"
printf 'not executable\n' > "$dir/noexec"; chmod 644 "$dir/noexec"
python3 "$here/scripts/flow_build.py" --programs "$dir" --out "$here/build/test/flow" --bin flow
python3 "$here/scripts/flow_build.py" --programs "$dir" --out "$here/build/test/flow-records" --bin flow-records
