# cancho-flow

**A run is a claim you can check.** `flow` starts a program as a recorded step: what it was given, which program ran, what came out, as a canonical, content-addressed record that can be read back, checked against the files on disk, run again and compared. Later, a plan of steps whose conditions are data. It knows nothing of the programs it starts: a compiler, `ml`, `make`, a shell script. It is a command line an agent can read, built the way [cancho-ml](https://github.com/alpibrusl/cancho-ml), [cancho-table](https://github.com/alpibrusl/cancho-table) and [cancho-stats](https://github.com/alpibrusl/cancho-stats) are, on the `contract` of [cancho-tools](https://github.com/alpibrusl/cancho-tools).

> **Landing page:** [alpibrusl.github.io/cancho-flow](https://alpibrusl.github.io/cancho-flow/) (`docs/index.html`; GitHub Pages must be enabled for `main` and `/docs`). `python3 scripts/site.py` regenerates its program output and figures; `scripts/check_landing.py` checks it.

> **Kind:** cli · **Stage:** built (M1: `step`, `list`, `show`, `check`)

**Status: early.** `flow step` runs one program as a recorded step and `flow-records` reads the records back; replay, comparison, memoisation and plans are designed and not built ([`docs/design.md`](docs/design.md) section 11). The design says what it is and what it refuses to become (not a scheduler, not a shell, not a sandbox), and section 13 says what the gates measured: a record is the same bytes in any directory, **2,136 damaged copies of a record are all refused**, every refusal rule has a fixture, every bound is refused before the child starts, and **13 of 13 mutants are killed**.

```console
$ flow step --root . --record records --in in.txt --out out.txt --deterministic -- sh -c 'cat in.txt > out.txt'
{"ok":true,"command":"flow","schema":"flow.v1","data":{"record":{"id":"805f9bb8…","oid":"725baeee…","file":"805f9bb8….725baeee….json","written":true},"outcome":{"exit":0,…,"out":[{"path":"out.txt","bytes":6,"sha256":"5891b5b5…"}]},"milliseconds":2},"meta":{"version":"0.1.0"}}
$ echo changed > in.txt
$ flow-records check --root . records 805f9bb8…
{"ok":false,…,"error":{"rule":"flow.check.inputs-changed","detail":{"path":"in.txt","recorded":"5891b5b5…","found":"7f8b1dfc…"}}…}
```

(Digests shortened here; the output is that of the built programs.) The programs a step may start are the files of one directory **baked into the binary**, so a deployment builds its own `flow`:

```sh
git clone https://github.com/alpibrusl/cancho                     # the compiler, at the commit cancho.toml names
(cd ../cancho && git checkout de4e52fd81809e6400e2c8b2f485d0b75412449c && cargo build --release -p cancho)
export CANCHO=$PWD/../cancho/target/release/cancho PATH=$PWD/../cancho/target/release:$PATH
cancho install                                                    # fetches the pinned cancho-tools contract into build/deps
python3 scripts/flow_build.py --programs /opt/agent/programs --out build/flow-agent --bin flow
python3 scripts/flow_build.py --programs /opt/agent/programs --out build/flow-records-agent --bin flow-records
scripts/check.sh                                                  # authority, the gates, every mutant
```

Licence EUPL-1.2, copyright Alpibru S.L.
