# Pharma chain

Design: [`docs/use-cases.md`](../../docs/use-cases.md).

**Built so far (U1):** the twin of the shared entities, and the gate that judges it.

```sh
python3 twin.py generate --world world.json --seed 20261112 --size small --out out     # items.csv, pharmacies.csv, patients.csv, truth.json
python3 scripts/check_twin.py [--mutants]                                              # G1: determinism, shares, refusals; every mutant killed
CANCHO=<compiler> sh scripts/flow_twin.sh                                              # the twin as a recorded `flow` step: the same record twice
```

Python 3 and nothing to install. The twin's random numbers are SplitMix64 and integers only (`twinlib/prng.py`). Every parameter in
`world.json` says where it came from; today all are stylised choices, none fitted (design, section 3).

Next (section 8 of the design): U2 pharmacy replenishment and its coupling to adherence, U3 refill adherence, U4 cold-chain delivery with
electric trucks, U5 the closed loop, U6 a measured run. Each is its own pull request.
