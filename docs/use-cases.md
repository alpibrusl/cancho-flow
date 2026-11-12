# Three analytics and ML use cases on the cancho tools, each with a digital twin

**Status: design, written before any code.** Nothing here is a result. Every claim is **[measured]** (with where), **[read]** (with
the file or command it was read from), a **[choice]**, or **[open]**. A claim found false is corrected here, in place.

## 1. What this is for

The tools (`table`, `stats`, `ml`, `solve`, `opt`, `flow` and `plot`) are each checked alone. No example uses them *together*, on a question whose
answer someone would act on. This document designs three, end to end, and for each a **twin**: a program that generates realistic
fake data from a stated model of the system, so that the example runs anywhere, in CI, with no data to download and with a known truth to
check the analysis against.

| | system | question the example answers | tools |
|---|---|---|---|
| **A** | an EV charging depot | how much energy will the depot be asked for tomorrow, hour by hour, and how do we charge the cars within the power cap | table, stats, ml, solve, opt, plot, flow |
| **B** | a subscription business | who is likely to leave, is the model's probability honest, and which retention offers do we make for a fixed budget | table, stats, ml, solve, plot, flow |
| **C** | a retail chain | how many units of each product will each store sell next week, and what do we order | table, stats, ml, solve, opt, plot, flow |

Each is non-trivial in the same way: a time or group structure that a random split would get wrong, a prediction that feeds a decision,
and a decision that is an optimisation with a checkable answer.

## 2. The twin

**A twin is a generative simulator of one system, not a live mirror of it [choice].** It is a function `(world, seed, size) -> files`. The
`world` is a JSON file of named parameters (rates, effects, noise levels); the twin writes CSV files that look like what the real system
would export.

Properties, each a gate (section 6) before it is code:

* **T1 deterministic [choice].** The same world, seed and size give the same bytes, on every platform. The twin brings its own
  generator (a 64-bit splitmix, and `math` for the rest) instead of `random`, whose stream is a property of the Python version, not of
  this repository.
* **T2 the truth is a file [choice].** The twin also writes `truth.json`: the parameters that generated the data and the quantities the
  analysis should recover (an effect size, a noise floor, the best plan's cost). The analysis never reads it; the gates do.
* **T3 realistic where it matters [choice].** The marginals and the dependence the analysis uses are set from real data where a real
  dataset is reachable (section 3), and from stated stylised facts where it is not. The twin says which, per parameter, in `world.json`.
* **T4 sized by a flag [choice].** `--size small` runs in seconds for CI; `--size large` is for a measured run on one machine.
* **T5 stdlib only [choice].** Python 3 and nothing to install, like the repositories' scripts.

## 3. Realistic data: what is reachable

*Measured in the session that wrote this (2026-11-11, through the agent proxy):*

| source | result |
|---|---|
| `raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv` | HTTP 200 |
| `archive.ics.uci.edu` (Online Retail) | proxy refused the tunnel, 403 |
| `ev.caltech.edu` (ACN-Data) | proxy refused the tunnel, 403 |

So only B has a real dataset in reach. Consequences:

* **B:** the twin is calibrated to the Telco file: marginals of tenure, contract, charges and services, and the churn rate by group,
  read by `table` and `stats` themselves (the first use of the tools on a real file). The file is **fetched by a script and checked
  against a pinned SHA-256, never committed** [choice]. **[open]** its licence; until read, nothing derived from it is published.
* **A and C:** the twin's parameters are **stylised facts, marked as choices**, not fitted. **[open]** a reachable public dataset for each;
  a candidate is a dataset the maintainer can place in a directory, and the calibration step (section 5, `opt`) is written so that it runs on
  any file with the twin's columns.

The IBM file is itself a published sample dataset, not a log of a real company. The example must say so.

## 4. The three systems

### 4.1 A: the EV charging depot

*Twin.* Vehicles arrive by a Poisson process whose rate has an hour-of-day and a day-of-week shape and a temperature effect; each session has
a dwell time and an energy need (state of charge on arrival, battery size, a maximum power per vehicle). Files: `sessions.csv`
(vehicle, arrive, depart, kwh_needed, max_kw), `weather.csv` (hour, temperature), `tariff.csv` (hour, price).

*Pipeline.*
1. `table` aggregates sessions to hourly demand, joins weather and builds lag features (`--query` SQL, one `flow step` each).
2. `stats describe`, `corr` and `test` check what the twin says is there: the temperature effect, the weekday effect.
3. `ml cv --split-by time:hour` then `ml fit --model boost` (and `linear`, `constant` as baselines) forecast the next day's demand.
4. `solve`: given the forecast sessions (or the day's real ones), a MIP chooses charging power per session and hour under a site
   power cap and each vehicle's deadline, minimising cost at the tariff.
5. `opt minimize`: calibrates the twin's parameters to a file by matching summary statistics (Nelder-Mead; BFGS where there is a gradient).
6. `flow`: every step above is a recorded step; the plan is a `flow run` plan.

### 4.2 B: churn and retention

*Twin.* Customers with tenure, contract type, monthly charges, services, support tickets; a churn hazard that is logistic in those, with
a contract effect and a charge effect set from the Telco file. Files: `customers.csv`, `tickets.csv`.

*Pipeline.*
1. `table` joins and aggregates (tickets per customer, tenure bands).
2. `stats test chisq` and `prop` (churn by contract, with `--correct holm`), `t2` / `mannwhitney` (tenure of churners), with intervals.
3. `ml cv --stratify`, `ml fit --model logistic|forest|boost`, `ml eval`, `ml importance`; `ml calibrate` / `ml isotonic` and a check that
   a predicted 30% is a churn rate of about 30% in the held-out rows.
4. `solve`: a knapsack MIP picks which customers get which offer, maximising expected retained value (calibrated probability times
   value times an uplift the twin knows) under a budget.
5. `flow`: as in A.

### 4.3 C: retail demand and replenishment

*Twin.* SKUs by stores by days: a base rate per SKU and store, weekly and yearly seasonality, a promotion effect, a price elasticity, and
**censoring** (a day with a stockout records the stock, not the demand). Files: `sales.csv`, `prices.csv`, `promos.csv`, `stock.csv`.

*Pipeline.*
1. `table` builds the weekly panel and the lag, price and promo features.
2. `stats corr` (price against units), `ks` / `mannwhitney` (promo against not), the censoring rate by SKU.
3. `ml cv --split-by time:week`, `ml fit --model boost` for the weekly forecast; the baseline is last week's value and `constant`.
4. `solve`: replenishment MIP (order quantity per SKU and store, integer pack sizes, a shelf-space cap, a service-level target
   from the forecast's held-out error).
5. `opt minimize`: calibrates the elasticity to a file.
6. `flow`.

## 4.4 Figures: `plot`

`plot` ([cancho-plot](https://github.com/alpibrusl/cancho-plot)) reads CSV on standard input and writes SVG or text (`--term svg`,
`--term dumb`); it can also read the JSON that `stats` and `ml` print (`--json PATH`). *Read from its README, 2026-11-12:* lines and points,
bands, a diagonal, bars, error bars, histograms, box plots, heatmaps, `--curve roc|ecdf|qq`, a log y axis, `--by`. *Measured 2026-11-12:* it
builds with the compiler at `51524d2` (cancho main) and writes a text chart from CSV on a Linux x86-64 machine; nothing more was run.

Each example ends in figures, each a `flow step` whose output is hashed like any other (`plot` has no clock and no random, by its `CLAUDE.md`):

| | figures |
|---|---|
| **A** | hourly demand, forecast against actual with a band (`--band`); the forecast error by hour (`--with bars`); the charging plan's load against the power cap (`--hline`) |
| **B** | the calibration curve with the diagonal (`--diag`); an ROC curve (`--curve roc`); the churn rate by contract with error bars (`--yerr`); the importance of each feature (`--with hbars`) |
| **C** | units against price per SKU (`--by`); the forecast error histogram (`--with hist`); a store-by-week heatmap of stockouts (`--with heat --z`) |

The text form (`--term dumb`) is what the README prints and what a gate can compare byte for byte; the SVG is what a person opens.
**[open]** whether the SVGs are committed or only generated; a committed SVG is a diff nobody reads, a generated one is a claim the gate checks.

## 5. What `flow` does here, and what it does not

Each stage is one recorded `flow step` or a `flow run` plan, with its inputs and outputs declared and hashed, so `flow-records check`
can say that a number in the README is the output of these inputs [choice]. `flow` stays what its `CLAUDE.md` says it is: not a
scheduler, not a shell. If a stage needs more than a list of argument lists, it is a program called by `flow step`.

**[open]** how a Python twin is started: `flow` starts only programs in its baked directory (docs/design.md), so either that directory holds
a `python3` entry or the twins are cancho programs. Section 7 settles it in milestone U1 before anything depends on it.

## 6. Gates, written before the code they judge

Each must be able to fail (a mutant of the twin or the pipeline that it catches):

| gate | what it holds | bound |
|---|---|---|
| **G1** twin determinism | two runs give the same bytes; two seeds give different bytes | exact |
| **G2** truth recovered | the effects the twin put in are found by `stats` (the right sign, an interval that holds the truth) and are not found when the twin is run with the effect set to zero | the intervals and the false-positive rate, fixed in U2 before measuring |
| **G3** the model earns its place | on a time split, the model beats the baseline by a margin fixed in advance, and is not better than the twin's noise floor | margin fixed before the first run **[open]** |
| **G4** the decision is checked | `solve verify` accepts every plan; on the small size the plan's cost equals an independent enumeration or HiGHS (scipy, optional in CI) | exact on small, a gap on large |
| **G5** the record is a proof | `flow-records check` passes; changing one byte of an input makes it fail | exact |
| **G6** calibration (B) | held-out predicted-against-observed in each decile within a bound fixed in advance | **[open]** |
| **G8** figures are stable | two runs give the same SVG bytes, and the text form of each figure equals a stored golden | exact |
| **G7** no panics, every refusal tagged | a fuzz of the pipeline's arguments, as in each repository | the tools' own |

Mutants for the twins: a changed rate, a dropped effect, a changed seed mix, an off-by-one in the dwell time. All killed, or each survivor explained.

## 7. Milestones, each its own pull request

| | what | done when |
|---|---|---|
| **U0** | this document, reviewed | the maintainer says go; the **[open]** items below answered or accepted |
| **U1** | the twin library (generator, world file, `truth.json`) and G1; how `flow` starts it (section 5) | G1 passes and fails on its mutants |
| **U2** | B end to end, on the Telco calibration, with G2, G3, G5, G6 | the README output is printed by `flow` records |
| **U3** | A end to end, with G4 and the `opt` calibration | same |
| **U4** | C end to end, with censoring | same |
| **U5** | a measured run on one machine (machine, threads, load, minimum of N), and the claims that the numbers support | numbers in section 8 |

## 8. Results

None yet.

## 9. Open

1. **Where it lives.** This document is in cancho-flow because `flow` records the steps **[choice]**. The examples need the built binaries of
   five repositories at pinned commits; a directory `examples/` here with a script that builds them is one answer, a repository of its own is
   another. The maintainer decides before U1.
2. The Telco file's licence (section 3).
3. A reachable public dataset for A and for C (section 3); the sandbox that wrote this could not reach the usual ones.
4. How the Python twin is started by `flow` (section 5).
5. The margins of G3 and G6, fixed before the first measurement and recorded here.
6. **`plot` is a seventh repository** and pins an older compiler (`cancho = "9934b11"`, 2026-11-06 in its `cancho.toml`); the session that wrote this has read access only, so its pin was not moved. Moving it is the same change as the six others and needs push access.
7. Whether `ml` has a forecasting form beyond features-and-lags with a time split; this design assumes it does not, and says so in the README.
