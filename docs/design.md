# cancho-flow: a run is a claim you can check

**Status: M1 is built (section 13); M2 and M3 are designs.** The design was written before any code and reviewed as PR 1; the probes of section 2 were run and are recorded; section 13 says what the build confirmed and what it corrected, in place. Tags, as in cancho-ml `docs/design.md`: **[read]** read from a document or a source file (named), **[measured]** printed by a probe run for this document (machine and conditions given), **[choice]** a decision the maintainer can overturn, **[open]** not decided or not checked. A claim found false is corrected in place, in this document, with the change that corrected it.

## 0. The position

Programs are small and checkable; pipelines are made of programs, and the pipeline is where the checking stops. A nightly job, a build, a model refit, a data extract: each is a sequence of runs, each run leaves an exit status and some files, and nothing says afterwards *what was given, what ran, what came out, and whether it would come out again*. `flow` makes **one run a claim**: a canonical, content-addressed record of what a step was given and what it did, which can be read back (`check`), run again (`replay`), compared (`compare`) and, later, strung into a plan whose conditions are data.

It is a general tool. It knows nothing of any program it starts (a compiler, `ml`, `make`, a shell script, a binary someone else wrote), only of files, hashes, argument lists, exit statuses and bounds. cancho-consulting is its first user, not its shape (section 8 has three unrelated ones).

**What it is not**, said first because each is a place the tool could quietly grow:

* **Not a scheduler.** cron, systemd or a CI service decide when. `flow` decides nothing about time except a deadline.
* **Not a shell or a language.** A step is a program name and an exact argument list. No expansion, no pipes, no variables, no loops, no expressions. A plan (section 6) is data and says less than a shell on purpose.
* **Not a sandbox.** It bounds the *invocation* (what starts, with which arguments and environment, for how long, with how much output) and records what the caller declared. It cannot see a file the child reads or writes without being told. Section 9 says what that does to every guarantee.
* **Not a cache that guesses.** A step is skipped only if the caller declared it deterministic, a record for its exact inputs exists, and its declared outputs still match (section 5.4).

**What cancho adds** (the question cancho `docs/agent-toolbox.md` section 0 asks of every tool in this ecosystem): the *contract* (JSON on standard output, errors with a stable rule tag and a repair, defined behaviour on hostile input) is language independent, and a thin envelope around `make` could have most of it. What only cancho gives is **an authority row the compiler computes**: `cancho authority` says that `flow` starts programs from one directory, holds a clock for the deadline and writes under one root, and a second binary (`flow-records`) that cannot start anything, read the clock or write at all. A supervisor reads that before granting either. That row, and bytes that are the same on every platform, are the claim; "agents do better with it" is **not** claimed (no agent-in-the-loop measurement has been run, as in cancho-tools).

## 1. Who asks

cancho's bar for a library is two askers, counted by reading programs (`CONTRIBUTING.md` of cancho, "How a slice is done", item 3). This is a new repository, not a library, but the bar is the honest test of whether it should exist.

| asker | what it does by hand today | status |
|---|---|---|
| cancho-consulting | `service/bidding/tools.py` starts `ml`, `table`, `stats`, `plan` and `sim` with Python's `subprocess`, **with no deadline**; it keeps its own run log (`joblog.py`) and its own gates | **[read]** this session's own code; counted |
| cancho-ml | its README says `scripts/check.sh` runs every gate, and `ml --track` records one kind of run | **[read]** the README and the file names of `scripts/`; the scripts were **not read**, so what they do by hand is unknown and this asker is **[open]** |
| cancho-tools `run` | starts one program, bounded, and records nothing; `docs/next-tools.md` section 10.4 holds a `plan` tool (a bounded workflow) back because no measurement says loops cost agents anything, and because it would reopen the exec class | **[read]**; the neighbour whose line `flow` must not cross, not an asker |
| cancho-opt | `opt` starts an objective program once per point | **[read]** its README; not a pipeline |

So there is one counted asker and one probable. The design below is written so that the first is an example and not a requirement; whether the repository earns a release is the maintainer's call once a second asker is counted (open question 1).

**Why not in cancho-tools:** `tools.toml` there fixes `max_tools = 12` and the toolbox is full (ten tools and `run`, **[read]**); and its rule that no tool holds `clock` has one exception, `run`'s deadline. `flow` needs the same exception and a second one for nothing else.

## 2. What the platform decides (measured and read)

Probes run on the cloud container of this session (Linux x86-64, 4 cores, one run each unless stated), with the cancho-tools sources at the commit `flow` would pin, built by the compiler `de4e52fd` its `cancho.toml` names.

| question | answer | how |
|---|---|---|
| how fast is the hashing a record needs | `toolbox.sha` hashes **200 MB in 1.33 s** (about 150 MB/s); `sha256sum` takes 0.19 s on the same file, so the pinned code is about seven times slower | **[measured]** `build/hash` of cancho-tools on a 200,000,000 byte random file |
| does a deadline end the child, and how late | `run --timeout-ms 500 -- sleep 5` answered `limit.timeout` after **502 ms** | **[measured]** |
| what does starting a program cost | **about 3 ms** per `run -- true` (100 in 0.296 s), against 0.03 ms for a shell builtin | **[measured]** |
| does the output cap end the child | `run --max-output 1000 -- yes` answered `truncated.stdout: true` in 4 ms | **[measured]** |
| can a megabyte pass through | 5 MB in on `--stdin` and 5 MB out of `cat`: 16 ms in the child, 80 ms wall, answer intact | **[measured]** |
| is the program allow-list a runtime choice | **no**: `narrow` takes a literal (`Exec("<dir>")` is in the source and in every signature), so a deployment rebuilds with its directory (`scripts/run_build.py` does that for `run`) | **[read]** `tools/run/run.cho` header and cancho `docs/processes.md` section 7.1 |
| what does a spawned child see | the environment `PATH=<programs directory>` and nothing else; it starts in `--root` | **[read]** `run.cho` header |
| does `run` read a file as standard input | **no**: the synopsis in `docs/next-tools.md` section 3.1 still lists `--stdin-file`, section 3.4 answer 4 says "not offered", and the binary has `--stdin` (its own standard input) and `--max-stdin` only | **[measured]** `--stdin-file` answered `args.unknown-flag`; **a small inconsistency in cancho-tools' document, reported here, not fixed** |
| is there a library for the contract | yes: `toolbox.cli` (a table drives the parser, `introspect` and `skill`), `toolbox.fail` (errors as data: rule, hint, repair, detail), `toolbox.out`, `toolbox.rules` (a catalogue and the exit code of each tag), `toolbox.describe`, `toolbox.sha`, `toolbox.atomic`, `toolbox.place`, `toolbox.lines`, `toolbox.limit`; cancho-ml and cancho-table pin it by commit and never copy it | **[read]** `contract/`, cancho-ml `cancho.toml` |
| is a durable log available | `cancho-log` is a segmented append-only log that cuts a torn tail after a crash; its API was **not read** | **[read]** its README; **[open]** whether it fits (question 7) |

None of this was measured for a step that reads or writes many files, or for a child that forks: those are not claimed.

## 3. Decisions

| # | question | decision | why |
|---|---|---|---|
| D1 | the unit | a **step**: one program, an exact argument list, no shell, an environment that is fixed and empty of caller data, a working directory (`--root`) | it is the most `run` already decided and the least that can be recorded exactly |
| D2 | which programs may start | a **name** (never a path) looked up in **one directory baked into the binary**; a deployment builds `flow` for its directory | the allow-list is then in the source and in the authority row, which a supervisor reads (section 2) |
| D3 | what a record is | canonical JSON, one line, fixed key order, no spaces, a final newline; **no timestamp, host name, process id, absolute path or payload** (section 4) | the same rule as `ml.run.v1`; a record that is a pure function of its inputs can be compared, hashed and checked |
| D4 | what identifies a run | `id` = SHA-256 of the `inputs` object's bytes; `oid` = SHA-256 of the `outcome` object's bytes; a record is the pair, and its file is `DIR/<id>.<oid>.json` | the same inputs and the same outcome are the same file (idempotent); the same inputs and another outcome are another file, so a program that is not deterministic is **recorded as such** and not refused (D8) |
| D5 | the identity of the program | `inputs.program` holds the program's name **and the SHA-256 and size of its file**, read by `flow` from the directory it starts it from | "what ran" is the first thing a record must say; a rebuilt `ml` is another run. `flow` reads the binary through the same `Fs("")` it opens the root with, so no narrowing is needed; the price is that the row says `fs_read("")` (the whole file system) and not the programs directory (section 13) |
| D6 | declared files | `--in` names the files a step reads and `--out` the files it writes; `flow` hashes the inputs before and the outputs after | only what is declared can be recorded or checked; undeclared reads and writes are invisible (section 9) |
| D7 | time | duration and clock time are **not in the record**; the answer prints `milliseconds`; a durable journal is a later, separate file (question 7) | a record must be byte-identical when the run repeats |
| D8 | determinism | **declared by the caller** (`--deterministic`) and part of `inputs`: a declared-deterministic step that yields a second `oid` for one `id` is refused (`flow.step.not-deterministic`, detail: both oids, nothing written); an undeclared step keeps every distinct outcome as a record | `flow` cannot know; a false claim must surface and an honest "not deterministic" must be allowed |
| D9 | a child that fails | the record is written **whatever the child did**; the answer is a refusal `flow.step.failed` (exit 8, `detail.exit`) unless `--allow-failure` | a pipeline runner that answers 0 for a failed step is the classic bug; a gate step's whole job is to exit non-zero, hence the flag |
| D10 | environment | the child gets `PATH=<programs directory>` and **no value from the caller**; a program reads its configuration from files named in `--in` | an environment value would be an input that can hold a secret, and records must never hold one |
| D11 | two programs | `flow` (starts programs, holds the clock, writes records and blobs) and `flow-records` (list, show, compare, check: reads only) | one program per authority (cancho-tools D17: a program's authority is the union of what its main reaches); an auditor can be granted the second without the first, as `ml-predict` is to `ml` |
| D12 | the contract | `contract` of cancho-tools, pinned by commit and never copied: schema `flow.v1`, one JSON line, `{ok, command, schema, data, error, errors, meta}`, stable `rule` tags, a `repair` that never widens authority, `introspect` and `skill` generated from one table | the same as ml, table and stats; an agent that knows one knows all |
| D13 | class | `flow` is `irreversible-consequential` and **opt-in**, like `run`; `flow-records` is read-only | cancho-tools D15; the MCP surface (if any) lists `flow-records` freely and `flow` by choice |
| D14 | captured output | the record keeps the **size and SHA-256** of each stream, not the bytes; `--keep-output` writes them as content-addressed blobs `DIR/blobs/<sha256>`, bounded | no payload in a record by default (a stream can hold anything); a caller that wants the text asks |
| D15 | parallelism | none in v0: steps run one at a time, in plan order | a result that depends on thread count is a result `flow` could not record; **[open]** whether independent steps may overlap (question 6) |

## 4. The record (`flow.step.v1`)

```
{"schema":"flow.step.v1","id":"<64 hex>","oid":"<64 hex>",
 "inputs":{"program":{"name":"ml","bytes":N,"sha256":".."},
           "args":["fit","--model","boost","--target","booked"],
           "stdin":null | {"path":"train.csv","bytes":N,"sha256":".."} | {"from":"stdin","bytes":N,"sha256":".."},
           "in":[{"path":"train.csv","bytes":N,"sha256":".."}],
           "out":["model.ml"],
           "deterministic":true,
           "limits":{"timeout_ms":30000,"max_output":1048576},
           "env":"fixed"},
 "outcome":{"exit":0|null,"signal":null|N,"timed_out":false,
            "truncated":{"stdout":false,"stderr":false},
            "stdout":{"bytes":N,"sha256":".."},"stderr":{"bytes":N,"sha256":".."},
            "out":[{"path":"model.ml","bytes":N,"sha256":".."} | {"path":"model.ml","missing":true}]},
 "flow":"0.1.0",
 "check":"<64 hex>"}
```

* **`id`** is the SHA-256 of the exact bytes of `inputs` as written (the same writer produces both, as in `ml.run.v1`). `inputs` holds what determines the outcome and nothing else. **Limits are inputs** (a different deadline can turn an outcome into `timed_out`); `ml` leaves its caps out because they can refuse a fit but never change its bytes, which is not true of a deadline **[choice]**.
* **`oid`** is the SHA-256 of the exact bytes of `outcome`. `check` is the SHA-256 of every byte of the record before `,"check":"`, so a record edited by one byte is `flow.record.damaged`.
* Paths are relative to `--root`, never absolute, and `..` is refused (`toolbox.path`, **[read]**). Argument strings are recorded as given: **a caller must not put a secret in an argument** (the record is the argument list), and `flow` refuses nothing it cannot recognise as one (section 9).
* `flow` (the version) sits outside `inputs`, as `threads` does in `ml.run.v1`: a new `flow` that writes the same inputs and outcome writes the same `id` and `oid`.
* Bounds **[choice]**: at most **1000 records** in `DIR` (`flow.record.too-many`, counted before anything is written), a record of at most **262144 bytes**, at most **64** declared files and **4096** arguments per step, a declared file of at most **2^30 bytes** unless `--max-bytes` raises it to a ceiling. Each is refused before the child starts. *(M1 enforces the record count, the 64 files and the 4096 arguments, each checked by a child that would leave a marker file (G4); the record's size is enforced when a record is read (`flow.record.too-large`) and not when it is written, which `flow` cannot make too large; the per-file byte cap and `--max-bytes` are **not built**.)*

## 5. The verbs

All go through the flag table, `introspect`, `skill` and the schemas of `contract`. A flag not in the table is `args.unknown-flag`, never ignored (cancho `docs/flags.md`).

### 5.1 `flow step [--root DIR] --record DIR [--in P,P] [--out P,P] [--stdin] [--max-stdin N] [--deterministic] [--allow-failure] [--answer-output] [--timeout-ms N] [--max-output N] -- PROGRAM [ARG...]`

*(Changed by the build: `--keep-output` (blobs) is M2 and is not built; `--answer-output` was added, because a caller that needs a program's output, not only its hash, has no other way to get it. It puts the streams in the **answer** as text and never in the record, so D14 holds. `--max-stdin` is `run`'s.)*

In order, every check before the child starts: the program name (`flow.program-name`, `flow.program-not-found`), the bounds, every `--in` file exists, is a regular file and is hashed (`flow.input.missing`, `flow.input.too-large`), the record directory exists and is not full. Then the child runs under the deadline and the cap (`limit.timeout`, `limit.output-too-large`, both recorded as outcomes). Then every `--out` file is hashed (a declared file the child did not leave is `{"missing":true}` and, when the child exited 0, the step is `flow.step.output-missing`: it did not do what was declared). Then the record is written atomically (`toolbox.atomic`), **after** the child, **before** the answer. The answer is `{record:{id,oid,file,written}, outcome:{...}, milliseconds}`; `written:false` when the identical record was already there.

### 5.2 `flow-records list|show|compare|check DIR [ID[.OID]]`

* `list`: one row per **record** (the order the directory lists them): `{id, oid, program, args (the count), exit, deterministic}`; a record that does not validate is `flow.record.damaged`, not skipped. *(Corrected by the build: the design said one row per `id` with an `attempts` count and bytewise order; M1 lists each record, and the grouping and the sort are not built.)*
* `show ID[.OID]`: the record, validated (id and oid recomputed, check verified). An `ID` with several outcomes is `flow.record.ambiguous` with a `choose` repair listing the `oid`s.
* `compare A B`: the `inputs` members that differ (a dotted key for the nested ones) and the outcome members side by side, as `ml runs compare` does.
* `check ID[.OID]`: recomputes `id`, `oid` and `check`, then hashes **now** the program's file, every declared input and every declared output, and says which no longer match (`flow.check.program-changed`, `flow.check.inputs-changed`, `flow.check.outputs-changed`, each with the recorded and the found digest). It starts nothing and writes nothing.

### 5.3 `flow replay [--root DIR] --record DIR [--rewrite] ID[.OID]`

`check` first (a replay of changed inputs proves nothing: `flow.replay.inputs-changed`), then runs the step again with the recorded program, arguments, limits and declared files, and compares the new outcome with the recorded one. **A replay of a step with declared outputs rewrites them** (the child writes where it writes), so it is refused without `--rewrite` (`flow.replay.rewrites-outputs`, repair: the same command with the flag). The answer is `{reproduced:true}`, or the refusal `flow.replay.differs` with the members that differ (`stdout`, `stderr`, `exit`, `out[i]`). **A step not declared deterministic can differ and that is not a fault**: its refusal is a finding, and the answer says whether the step was declared.

### 5.4 Memoisation (used by `run`, section 6, and by `flow step --reuse`)

A step is **not executed** when (a) it is declared deterministic, (b) a record exists with its `id`, (c) the program's file and every declared input still hash as recorded and (d) every declared output still hashes as recorded. The answer says `cached:true` and names the record. Anything else executes. `flow` never reuses a step it was not told is deterministic, and never reuses one whose outputs were touched since.

## 6. Plans (a later milestone; sketched here so the atom is shaped for it)

`flow run [--root DIR] --record DIR PLAN` runs steps in order. A plan is JSON lines, one step per line, **data and nothing else**:

```
{"id":"fit","program":"ml","args":["fit","--model","boost","--output","m.ml","train.csv"],"in":["train.csv"],"out":["m.ml"],"deterministic":true}
{"id":"gate","program":"calib","args":["m.ml","valid.csv"],"in":["m.ml","valid.csv"],"after":"fit","allow_failure":true}
{"id":"serve","program":"plan","args":["--model","m.ml"],"after":"gate","when":{"step":"gate","exit":0}}
{"id":"fallback","program":"baseline","args":[],"after":"gate","when":{"step":"gate","exit_not":0}}
```

* **Order** is file order; `after` names a step that must have run (checked: no cycle, no unknown id). There is no topological scheduler: the file order is the order, and a plan whose `after` points forward is refused (`flow.plan.order`).
* **A condition is an exit status**: `when:{step,exit}` or `{step,exit_not}`, and nothing else. No expressions, no JSON-pointer tests in v0 (cancho-tools' held design allows a pointer test; this does not need it yet). A step whose `when` is false is `skipped`, not failed.
* **No loops, no variables.** `${item}` and `foreach` are the held tool's, and the held tool's own admission test applies here: if a request needs more than a list of argument lists, the answer is "write a program and call `flow step`" (cancho-tools `docs/next-tools.md` section 10.4).
* **Bounded and checked whole before anything runs**: `--max-steps` (default 64, ceiling 1024), every program name in the directory, every declared path inside the root; `--dry-run` prints the argument list of every step.
* **The first failing step stops the plan.** The answer is that step's refusal and `resume:{from_step:"k"}`; `flow run --from k` continues, and steps before it are reused only under 5.4.
* **The plan is recorded**: `flow.plan.v1` holds the SHA-256 of the plan text and the `id.oid` of each step it ran in order, so a run of a plan is itself a claim `flow-records check` can verify.

This is what cancho-tools held back as `plan`. It is here because the repository exists for it, with one more boundary than the held design had: **a step is a program, a plan is not a program.**

## 7. Authority

| binary | row (derived by `cancho authority`, ceiling in `tools.toml`) | what it cannot do |
|---|---|---|
| `flow` | `args`, `heap`, `io_read` (`--stdin`), `io_write`, `err_write`, `clock` (the deadline, and nothing else), `poll`, `child_signal`, `pipe_read`, `pipe_write`, `exec("<programs directory>")`, `fs_read` and `file_write`/`dir_write` for the root and the record directory | no network, no `ffi`, no signals of its own, no environment, no write outside the record directory except through the child |
| `flow-records` | `args`, `heap`, `io_write`, `err_write`, `fs_read` | no `exec`, no `clock`, no write |

`flow` reopens, deliberately, the clause cancho-tools' D15 keeps shut ("`find -exec` and `xargs` are not a thing the toolbox can be tempted into"): it is `run`'s class and is built and shipped opt-in. **The authority row says what `flow` can start, never what a started program then does**; the child has its user's whole authority, as `run`'s own documentation says.

The programs directory is a literal in the source (section 2); `scripts/flow_build.py` bakes a deployment's directory the way `run_build.py` does, and the derived row names it. The committed source says a default.

## 8. Three unrelated uses (the test that the design is not one user's)

1. **A build and test pipeline.** `cancho check`, `cancho build` and the test run as three steps; the first two are declared deterministic with their sources as `--in` and the binary as `--out`; an unchanged tree is `cached:true` for both, and a changed source reruns from there. `flow-records check` says, a month later, whether the binary on disk is the one the record names.
2. **A data refit** (cancho-consulting's weekly refit). `ml fit` as a deterministic step with the training file as `--in` and the model as `--out`; a calibration check as a gate step with `allow_failure`; the service step `when` the gate exited 0, the baseline step when it did not. The record directory is what `ml runs` and a dashboard read.
3. **A document pipeline.** `table` selects, `stats` tests, a renderer writes a page: three steps, each declared deterministic, so an unchanged extract produces no work and a changed one reruns exactly the steps that read it.

What these share is not a domain: it is a list of programs, the files they read and write, and a question about whether a result still holds.

## 9. What `flow` does not know, and what that costs each claim

* **Undeclared files.** A child can read a file that is not in `--in` and write one that is not in `--out`. The record then omits an input that changed the outcome, and a **cached step can be wrong**. `flow` cannot prevent it (no sandbox, section 0). Mitigations that are the caller's: declare completely, run under a deployment's own containment, use `replay` on a sample to find a step whose declaration was incomplete (a deterministic step that does not reproduce is the symptom).
* **A secret in an argument** is recorded. `flow` refuses what it recognises (none in v0: it recognises nothing) and documents the rule; the caller keeps secrets in files and declares them with `--in`, where only a hash is recorded.
* **A process the child leaves running** (a daemon, a grandchild) is outside the record; `run` has the same limit (cancho `processes.md` section 9 lists `PR_SET_PDEATHSIG` as open **[read]**).
* **Time and ordering of the child's own output.** Streams are separate; their interleaving is not kept.
* **The clock.** The deadline depends on it, so a step near its limit may time out on one run and not another; that is why limits are inputs (section 4).
* **"Same bytes on every platform"** holds for the record `flow` writes given the same inputs and outcome, **[open]** until a committed fingerprint is checked on more than one platform (cancho-stats does this, `docs/xplat_fp.txt`). A child's own output is the child's.

## 10. Gates (written before the code they judge; each must be able to fail)

| gate | checks | killed by |
|---|---|---|
| G1 canonical | the same step twice writes the same bytes; the record has no timestamp, path or payload (a scan of the bytes for the working directory and the host name) | a mutant that adds a duration or the root to the record |
| G2 damage | every truncation and every flipped byte of a small record is `flow.record.damaged` (exhaustive, as `ml`'s model file is) | a mutant that skips the `check` comparison |
| G3 refusals | every rule tag in `flow --introspect` has a fixture that raises it, and no fixture raises an unregistered tag (as `ml`'s `refusals` test) | deleting a fixture |
| G4 bounds | a deadline of 200 ms ends `sleep 5` within 200 ms plus a stated slack; the cap ends `yes`; the 1001st record, a 65th declared file, an over-long argument list are refused **before** the child starts (checked by a child that would leave a marker file) | a mutant that checks after |
| G5 determinism claims | a declared-deterministic step that changes its output on the second run is `flow.step.not-deterministic` and writes nothing; an undeclared one writes two records | a mutant that treats both alike |
| G6 memoisation | a cached step does not start (the marker file is absent); touching a declared output, a declared input or the program's file makes it run | a mutant that omits one of the three comparisons |
| G7 check | `flow-records check` names the right member for each of: changed program, input, output, record bytes | one mutant per member |
| G8 authority | `scripts/manifest.py --check`: the derived row of each binary equals the committed row and is inside the ceiling; `flow-records` has no `exec`, `clock` or write | adding a call to either |
| G9 plans (M3) | cycle, unknown step, forward `after`, over-long plan, a `when` on a skipped step, resume after a failure | one mutant per rule |
| G10 files | no source file over 2,000 lines (`tests/files.sh`) | — |

Mutants: **all killed, or each survivor explained** (cancho-ml's rule). No gate is a claim until it has run.

## 11. Milestones

| | what | done when |
|---|---|---|
| M0 | this document, reviewed | the maintainer's answers to section 12 are in it |
| M1 | `flow step` and `flow-records list|show|check`; the record, the contract, the authority rows, gates G1 to G4, G7, G8, G10 | the gate passes and the mutants are killed |
| M2 | `replay`, `compare`, memoisation, `--keep-output`; G5, G6 | same |
| M3 | `flow run` and plans; G9; the cancho-consulting runner switched to it, and the Python `tools.run` retired | same, plus cancho-consulting's own gate green on `flow` |
| M4 | a second pipeline moved onto it (cancho-ml's gates, if counted as an asker) | a release is warranted |

## 12. Open questions for the maintainer

1. **Does the repository earn a release** with one counted asker? (Section 1: the second is probable, not counted.)
2. **D5: may `flow` read the program's file?** *Answered by the build:* yes, through the `Fs("")` it already holds (the way every cancho-tools program reads under `--root`); no narrowing was needed, and `--program-sha256` is not needed. What it costs is in section 13: the read row is the whole file system, as in every sibling.
3. **D4 and D8: one record per distinct outcome** (the proposal) or one record per `id` with a conflict (as `ml`)? The first lets a non-deterministic step be honest; the second treats any difference as a fault.
4. **D9: a failed child is a refusal by default.** Or exit 0 and let the caller read `outcome.exit` (as `run` does)?
5. **D10: no environment at all.** A program that needs `HOME` or a locale gets none. Is that too strict for the first users?
6. **D15: no parallelism.** Whether independent steps may overlap, and how a record stays byte-identical if they do.
7. **D7: a durable journal.** Whether `cancho-log` (append-only, crash-safe) is the backing for a run's ordered events, or a plain NDJSON file with `--log` like `ml`.
8. **The name.** `cancho-flow` was proposed with `cancho-runbook` and `cancho-ledger` as alternatives (cancho-tools already has `run`).
9. **Pinning.** *Settled by the build:* cancho-tools at `3399bd7a` and compiler `de4e52fd`, the pair `run` builds with. cancho-ml's pair (`8dab9176`, `0207556b`) was not tried.
10. **MCP.** Whether `flow-records` is listed on cancho-tools' MCP server, and whether `flow` is ever.

## 13. Results

### 13.1 What M1 builds

`flow step` and `flow-records list|show|check`, the record, the contract, the two authority rows, and the gates below. Run `CANCHO=<de4e52fd> scripts/check.sh` after `cancho install`: **[measured]** on this session's container (Linux x86-64, 4 cores), one run, the whole gate (builds, authority, every gate, every mutant) takes **97 s**.

| gate | result **[measured]** |
|---|---|
| G1 canonical | the same step twice writes one record (`written:false` the second time); the same step in another directory writes the same name and **the same bytes**; the record holds neither the directory, `/tmp` nor the host name |
| G2 damage | **2,136 cases, all refused as `flow.record.damaged`**: every byte flipped (one bit), every truncation, and two kinds of extra byte; a byte of `inputs` is refused by the layout or the id (never only by the check), a byte of `outcome` by the layout or the oid |
| G3 refusals | **28 fixtures**, one per registered `flow.*` and `limit.*` rule and a selection of the contract's; no fixture raises an unregistered tag |
| G4 bounds | a 300 ms deadline ends `sleep 5` in under 1.5 s and is recorded as a timeout; the output cap ends `yes`; a full record directory, 65 declared files, 4,100 arguments, a missing input, a `..` path and a bad flag value are each refused **before the child starts** (a child that would touch a marker file never ran) |
| G5 determinism | a falsified `--deterministic` claim is refused and writes nothing; an undeclared step keeps both outcomes |
| G7 check | an untouched step checks clean; a changed output is named with its path and both digests |
| G8 authority | `scripts/manifest.py --check`: both derived rows equal the committed ones and the embedded `introspect` rows, and sit inside `tools.toml` |
| G10 files | no source file over 2,000 lines |
| G11 answer output | `--answer-output` puts the streams in the answer and never in the record |
| mutants | **13 of 13 killed**: no check comparison, no id comparison, no oid comparison, bytes after the end accepted, a false determinism claim accepted, no record bound, a failed child not refused, a missing declared output not refused, a timeout not recorded, declared inputs left out of the record, `..` accepted, `check` blind to a changed program, `check` blind to a changed file |

Not built: G6 (memoisation) and G9 (plans), because `--reuse`, `replay`, `compare`, `--keep-output` and `flow run` are M2 and M3.

### 13.2 The authority, derived

`flow`: `args`, `child_signal`, `clock`, `dir_read`, `dir_write`, `err_write`, `exec("/opt/cancho-flow/programs")`, `file_read`, `file_write`, `fs_read("")`, `heap`, `io_read`, `io_write`, `pipe_read`, `pipe_write`, `poll`. `flow-records`: `args`, `dir_read`, `err_write`, `file_read`, `fs_read("")`, `heap`, `io_write`: **no `exec`, no `clock`, no write**, which `scripts/manifest.py` enforces whatever `tools.toml` says. Two things to know. The read row of both is `fs_read("")`: the whole file system, as in every cancho-tools program (extent comes from `--root` confinement, not from the row). And `flow introspect` prints `reads_clock: false` although the row holds `clock`: that flag is not derived from the row (a field of `describe`'s Tool that this program left at its default); not corrected in M1, **[open]**.

### 13.3 What the build corrected in this document

* `list` is one row per record, not per id (5.2).
* `--answer-output` exists, `--keep-output` does not yet (5.1).
* D5 needed no `Fs` narrowing; question 2 and question 9 are answered (section 12).
* Not every bound is enforced yet (section 4, the note on bounds).
* **A bug the gates found in `flow`'s first version**: a program file that could not be read to be hashed (a link that loops) was reported as `path.symlink`, "the tool does not follow links", which is false of the programs directory. It is `flow.spawn-failed` with the errno now. It was found because the test's own setup made a link to a shell builtin (`command -v true` prints the bare name `true`), which is the kind of mistake a deployer makes.
* **A defect in cancho-tools' documents, reported and not changed**: `docs/next-tools.md` section 3.1 still lists `run --stdin-file` (section 2 above).

### 13.4 Decisions the build took by default (no answer had been given)

D4 and D8 as proposed (one record per distinct outcome), D9 as proposed (a failed child is a refusal, `--allow-failure` to turn it off), D10 as proposed (no environment at all), D15 as proposed (no parallelism). They are implemented and tested, so overturning one is a change with a gate behind it, not an edit to a sentence.
