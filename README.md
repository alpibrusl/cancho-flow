# cancho-flow

**A run is a claim you can check.** `flow` starts a program as a recorded step: what it was given, which program ran, what came out, as a canonical, content-addressed record that can be read back, checked against the files on disk, run again and compared. Later, a plan of steps whose conditions are data. It knows nothing of the programs it starts: a compiler, `ml`, `make`, a shell script. It is a command line an agent can read, built the way [cancho-ml](https://github.com/alpibrusl/cancho-ml), [cancho-table](https://github.com/alpibrusl/cancho-table) and [cancho-stats](https://github.com/alpibrusl/cancho-stats) are, on the `contract` of [cancho-tools](https://github.com/alpibrusl/cancho-tools).

> **Kind:** cli · **Stage:** design

**Status: a design, written before any code.** Nothing is built. [`docs/design.md`](docs/design.md) is the design: the position (what it is and what it refuses to become: not a scheduler, not a shell, not a sandbox), who asks (one counted user, cancho-consulting, so far), what the platform decides (probes run for it: a deadline ends a child 2 ms late, a spawn costs about 3 ms, pinned SHA-256 runs at about 150 MB/s), the decisions, the record, the verbs, plans as data, the authority of each of the two binaries, three unrelated uses, what it does not know, the gates written before the code, the milestones, and ten open questions for the maintainer.

```
flow step --record runs --in train.csv --out model.ml --deterministic -- ml fit --output model.ml train.csv
flow-records check runs <id>     # does the program, every input and every output still match the record?
```

(The lines above are what the design describes, not something that runs.)

Licence EUPL-1.2, copyright Alpibru S.L.
