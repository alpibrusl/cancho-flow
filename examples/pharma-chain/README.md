# Pharma chain

Design: [`docs/use-cases.md`](../../docs/use-cases.md).

**Built so far:** the twin (shared entities and C's weekly dispensing with stock, expiry and stockout censoring), the gates that judge it, C's forecast pipeline
C's replenishment decision (a model for `solve`), the refill series with the stockout-to-lapse coupling, and the calibrated model of the lapse, run as recorded `flow` steps.

```sh
python3 twin.py generate --world world.json --seed 20261112 --size small --out out     # items, pharmacies, patients, dispensing, truth.json, truth/demand.csv
python3 scripts/check_twin.py [--mutants]                                              # G1: determinism, stock identities, shares, refusals; every mutant killed
CANCHO=<compiler> sh scripts/flow_twin.sh                                              # the twin as a recorded `flow` step: the same record twice
CANCHO=<compiler> python3 scripts/pipeline_c.py [--mutants]                            # table, features, ml, stats as 19 flow steps; G2, G4, G7; every mutant killed
```

```sh
CANCHO=<compiler> python3 scripts/pipeline_b.py [--mutants]                                  # the lapse model on a time split, calibrated; chisq, ml, isotonic; G2, G4, G8, G7; 5 mutants
CANCHO=<compiler> python3 scripts/coupling_c.py [--mutants]                                  # the stockout-to-lapse coupling: two large twins, stats test prop; G3, G7; 2 mutants
CANCHO=<compiler> SCIPY_PYTHON=<python with scipy> python3 scripts/plan_c.py [--mutants]       # the forecast, then 96 replenishment decisions in solve; G2, G4, G5, G6, G7; 6 mutants
```

`pipeline_c.py` and `plan_c.py` need the built siblings (also `../cancho-solve/build/solve`, or `SOLVE`) (`../cancho-table/build/table`, `../cancho-stats/build/stats`, `../cancho-ml/build/ml`, or `TABLE`, `STATS`, `ML`). The HiGHS oracle needs scipy (`SCIPY_PYTHON`); `SKIP_ORACLE=1` leaves it out knowingly.
Python 3 and nothing to install. The twin's random numbers are SplitMix64 and integers only (`twinlib/prng.py`). Every parameter in `world.json` says where
it came from; today all are stylised choices, none fitted (design, section 3). Results: design, section 10.

Next (section 8 of the design): U3b the outreach decision in `solve`, U4 cold-chain delivery with electric
trucks, U5 the closed loop, U6 a measured run. Each is its own pull request.
