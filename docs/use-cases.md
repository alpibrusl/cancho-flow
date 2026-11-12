# One pharma supply chain, three analytics and ML use cases, one digital twin

**Status: design, written before any code (version 2: the three systems are now one connected world).** Nothing here is a result.
Every claim is **[measured]** (with where), **[read]** (with the file or command it was read from), a **[choice]**, or **[open]**. A
claim found false is corrected here, in place. Nothing here is medical or regulatory advice, and no real patient data is used or needed.

## 1. What this is for

The tools (`table`, `stats`, `ml`, `solve`, `opt`, `flow`, and later `plot`) are each checked alone. No example uses them *together* on a
question whose answer someone would act on. This document designs one: a **pharmaceutical distribution chain**, seen from three places,
with a **digital twin** that generates realistic fake data for all three from one stated model, so the example runs anywhere, in CI,
with a known truth to check every analysis against.

```
 patients ──refill demand──▶ PHARMACIES ──orders──▶ DEPOT ──EV reefer trucks──▶ PHARMACIES
     ▲                           │  stockouts, expiry         │  late or warm deliveries
     └──────── lapse (stops refilling) ◀──────────────────────┴───────────────────────┘
```

| | use case | question the example answers | tools |
|---|---|---|---|
| **C** | pharmacy replenishment | how many units of each medicine will each pharmacy dispense next week, and what do we order given expiry dates, cold-chain items and a shelf-space cap | table, stats, ml, solve, opt, flow |
| **A** | cold-chain delivery with electric trucks | which truck serves which pharmacies, will its battery last given the refrigeration load, and how do we charge the fleet overnight under the depot's power cap | table, stats, ml, solve, opt, flow |
| **B** | refill adherence ("churn") | which chronic patients will stop refilling, is the model's probability honest, and which patients get a pharmacist call or a home delivery for a fixed budget | table, stats, ml, solve, flow |

**The three are coupled, and that is the point [choice].** A stockout at a pharmacy (C) raises a patient's chance of lapsing (B); a late
or warm delivery (A) causes the stockout and the discarded stock; the patients' refills are the demand that C forecasts and A
delivers. Each use case is non-trivial alone (time and group structure a random split would get wrong, a prediction that feeds a
decision, a decision that is an optimisation with a checkable answer); together, a number in one is an input to another, and the twin
knows by how much.

## 2. The twin

**A twin is a generative simulator of the whole chain, not a live mirror of a real one [choice].** It is a function
`(world, seed, size) -> files`. The `world` is a JSON file of named parameters; the twin writes the CSV files each use case reads, and
`truth.json`.

Properties, each a gate (section 7) before it is code:

* **T1 deterministic [choice].** The same world, seed and size give the same bytes, on every platform. The twin brings its own generator
  (a 64-bit splitmix, and `math` for the rest), not `random`, whose stream is a property of the Python version.
* **T2 the truth is a file [choice].** `truth.json` holds the parameters that generated the data and the quantities an analysis should
  recover (an effect, a noise floor, the best plan's cost). The analysis never reads it; the gates do.
* **T3 realistic where it matters [choice].** Each parameter in `world.json` says whether it is a **stylised fact (choice)**, **read** from
  a named public source, or **fitted** to a file. Today none is fitted (section 3).
* **T4 coupled, with the coupling switchable [choice].** Every cross-use-case effect (stockout to lapse, late delivery to stockout, forecast
  error to expiry write-off) has a coefficient that can be set to zero, so a gate can show the effect is found when present and not
  found when absent.
* **T5 sized by a flag [choice].** `--size small` runs in seconds for CI; `--size large` is for a measured run on one machine.
* **T6 stdlib only [choice].** Python 3 and nothing to install, like the repositories' scripts.
* **T7 synthetic people only [choice].** Patients are rows of generated numbers. The twin has no input that is a real person's data.

## 3. Realistic data: what is reachable

*Measured in the session that wrote this (2026-11-11, through the agent proxy):* the IBM sample file `Telco-Customer-Churn.csv` on
`raw.githubusercontent.com` answered HTTP 200; `archive.ics.uci.edu` and `ev.caltech.edu` were refused (403). No pharmacy, drug-sales,
adherence or cold-chain dataset was looked for yet. So:

* **All three twins start from stylised facts, marked as choices.** Examples of what they will be: refill intervals of 30 or 90 days with
  a spread; a share of items that need 2 to 8 degrees Celsius **[choice]** (the usual refrigerated range; **[open]** check against the
  distribution guidance a real operator follows before the README says anything about compliance); shelf lives of months to years; winter
  peaks for respiratory medicines.
* **[open]** a public dataset for each of: pharmacy sales by item and day, patient refill histories (claims-style), vehicle energy per
  kilometre with a refrigeration unit. Each is a file the maintainer can place in a directory; the calibration step (section 5, `opt`)
  runs on any file with the twin's columns, so a real file moves a parameter from *choice* to *fitted* without changing the code.
* **The Telco file** is a churn sample from another industry. It is **not** used to calibrate the pharma twin. **[open]** whether to use it
  once, to run the churn half of the pipeline on a real file as a smoke test; its licence is unread, so nothing derived from it is
  published until it is.

## 4. The three use cases

### 4.1 C: pharmacy replenishment under expiry and cold chain

*What makes it pharma.*
* **Expiry and FEFO.** Stock is in lots with an expiry date; the pharmacy dispenses first-expiry-first-out; stock that expires is a
  write-off. Over-ordering costs money that a retail example for biscuits would not lose so fast.
* **Cold-chain items** have a smaller shelf-space cap and a temperature constraint on delivery (A).
* **Two kinds of demand.** Chronic refills are predictable from patients' due dates (B); acute demand (a season's infections) is not.
* **Asymmetric stockout cost.** A missing critical medicine costs more than a missing vitamin; the cost enters the objective and a
  service-level target.
* **Substitution.** A stocked-out brand can be replaced by a generic; the twin has a substitution rate, so a stockout does not always
  lose the sale **[choice]**; the demand the data records is therefore censored in a more complicated way than in retail.
* **Controlled items** have a per-order cap **[choice]**.

*Twin files.* `pharmacies.csv`, `items.csv` (shelf life, cold chain, criticality, pack size), `dispensing.csv` (pharmacy, item, day,
units), `stock.csv` (pharmacy, item, day, lot, expiry, units), `orders.csv`.

*Pipeline.*
1. `table` selects, filters by week and joins items (`--join`) and writes the training and held-out files (`--out`). **Correction, read from
   `table skill --full` on 2026-11-12:** `table` has no computed columns and no window functions, so the lags (last week, the mean of the last four)
   are a small stdlib program, `features.py`, run as a `flow` step. This is a gap of `table` that the example shows, not hides.
2. `stats`: `describe` and `corr` (demand against temperature and season), `ks` / `mannwhitney` (a respiratory item in winter against
   summer), the share of cells censored by stockout per item.
3. `ml cv --split-by time:week`, then `ml fit --model boost` (baselines: `constant`, last week). The refill share of demand from B is a
   feature.
4. `solve`: a replenishment MIP per pharmacy: order quantity per item (integer packs), shelf-space and cold-space caps, expected write-off
   from the lots' expiry dates, a service-level constraint from the forecast's held-out error, the controlled-item cap.
5. `opt minimize`: calibrates the substitution and elasticity parameters of the twin to a file.
6. `flow`: every step recorded.

### 4.2 A: cold-chain delivery with electric reefer trucks

*What makes it pharma.*
* **A temperature band on the whole trip.** The refrigeration unit draws power from the traction battery, more when it is hot outside and
  while doors are open at a stop; so a route's energy is *driving + refrigeration*, and a cold item raises it **[choice]**.
* **Time windows** at pharmacies, and a deadline (a pharmacy opens at 08:00 and must have the delivery before it).
* **A warm delivery is a loss** (the batch is discarded) and shows in C's write-off; a **late** one shows in C's stockouts.
* **The depot has a power cap** shared by overnight charging and the refrigerated warehouse.

*Twin files.* `trucks.csv` (battery kWh, refrigeration kW, cold capacity), `routes.csv` (day, truck, ordered stops, distance, time
windows, outside temperature), `telemetry.csv` (route, stop, kWh used, cabin temperature, door-open minutes), `depot.csv` (hourly cap and
tariff).

*Pipeline.*
1. `table` builds one row per route and per stop, joined to weather and to the orders that C produced.
2. `stats`: the refrigeration effect on energy (`corr`, a `t2` of hot against mild days), door-open time against temperature excursions
   (`test chisq` or `prop` with `--correct holm`).
3. `ml cv --split-by time:day`, `ml fit --model boost|linear`: (i) a regression for a route's energy, with a baseline that is distance
   alone; (ii) a classification for the risk of a temperature excursion, with `ml calibrate`.
4. `solve`: (i) assign the day's deliveries to trucks so that each truck's predicted energy plus a reserve fits its battery and every time
   window holds, and (ii) the overnight charging plan under the depot cap at the tariff, so that each truck is full by its departure.
   Stop order within a truck is part of the model only up to a size `solve` is shown to handle (section 9, open 5); beyond it the twin
   gives the order as data and the example says so.
5. `opt minimize`: calibrates the twin's refrigeration and driving coefficients to a telemetry file.
6. `flow`.

### 4.3 B: refill adherence

*What makes it pharma.* "Churn" is **lapse**: a chronic patient who does not refill within a grace period after the due date. It matters
clinically and commercially, and the interventions are different from a telecom's discount: a pharmacist's call, a reminder, a switch
to a 90-day supply, a home delivery (which loads A).

*Twin.* Patients with an age band, a regimen (number of chronic items, refill interval), a co-payment, a home pharmacy, and a refill history
generated by a hazard model: a base lapse rate, an effect of regimen complexity and co-payment, an effect of **a stockout of the
patient's item at the pharmacy in the last 30 days** (from C) and of **a late delivery** (from A). Files: `patients.csv`, `refills.csv`
(patient, item, due, filled), `contacts.csv` (outreach already made).

*Pipeline.*
1. `table` builds one row per patient and due date: days since the last fill, gaps so far, stockouts seen, contacts made.
2. `stats`: `test prop` and `chisq` (lapse by regimen size, by co-payment band, by a stockout seen; `--correct holm`), `mannwhitney` (gap
   lengths of lapsers against others), each with an interval.
3. `ml cv --split-by time:due` (a patient's later due dates must not train a model that scores an earlier one), `ml fit --model
   logistic|forest|boost`, `ml eval`, `ml importance`; `ml calibrate` or `ml isotonic`, and a check that a predicted 30 percent is a lapse
   rate of about 30 percent in the held-out rows.
4. `solve`: choose patients and an intervention each (call, reminder, 90-day switch, home delivery) maximising expected adherent days (the
   calibrated probability times an uplift the twin knows) under the pharmacists' hours, a budget and the delivery slots A has left.
5. `flow`.

*Optional second kind of churn [open]:* an independent pharmacy leaving the wholesaler (a B2B account), from the same twin's
`pharmacies.csv` and its service history (fill rate, late deliveries). Same pipeline, a few hundred rows, a harder statistical problem
(small groups, exact tests: `fisher`). Left out unless the maintainer wants it.

## 5. Figures

`plot` is not in the pinned set of this repository's work yet and **its issues stay open for another session [decision of the
maintainer, 2026-11-12]**. Until then the figures are `--term dumb` text or tables printed by `table`. Nothing in the design depends on
`plot`; section 9 lists what it would add (calibration curve, forecast against actual, heat map of stockouts, load against the power
cap).

## 6. What `flow` does here, and what it does not

Each stage is one recorded `flow step` or a `flow run` plan, with its inputs and outputs declared and hashed, so `flow-records check`
can say that a number in the README is the output of these inputs [choice]. `flow` stays what its `CLAUDE.md` says it is: not a
scheduler, not a shell. If a stage needs more than a list of argument lists, it is a program called by `flow step`.

How a Python twin is started: `flow` starts only programs in its baked directory (`docs/design.md`), and that directory holds symlinks, as the
gates' own does for `sh` and `cat`. **Settled in U1 [measured]:** a `python3` symlink there starts the twin; the twin's files are declared `--in`
and its outputs `--out`, and the record names the SHA-256 of the `python3` file and of every declared input (section 10).

## 7. Gates, written before the code they judge

Each must be able to fail (a mutant of the twin or the pipeline that it catches):

| gate | what it holds | bound |
|---|---|---|
| **G1** twin determinism | two runs give the same bytes; two seeds give different bytes | exact |
| **G2** truth recovered | each effect the twin put in is found by `stats` (right sign, an interval that holds the truth) and is **not** found when its coefficient is set to zero | the intervals and the false-positive rate, fixed in U2 before measuring |
| **G3** coupling is real | with a coupling coefficient set to zero the downstream effect vanishes (a stockout no longer moves lapse; a late delivery no longer moves stockouts); at its value it is found | as G2 |
| **G4** the model earns its place | on a time split each model beats its baseline by a margin fixed in advance and is not better than the twin's noise floor | section 7a |
| **G5** the decision is checked | `solve verify` accepts every plan; on the small size each plan's cost equals an independent enumeration or HiGHS (scipy, optional in CI) | exact on small, a gap on large |
| **G6** constraints are physical | no plan puts a truck on a route its predicted energy plus reserve exceeds the battery for; no plan orders more than the shelf or cold cap; a plan that does is refused by `solve verify` | exact |
| **G7** the record is a proof | `flow-records check` passes; changing one byte of an input makes it fail | exact |
| **G8** calibration (B and the excursion classifier) | held-out predicted against observed in each decile within a bound fixed in advance | section 7a |
| **G9** no panics, every refusal tagged | a fuzz of the pipeline's arguments, as in each repository | the tools' own |

Mutants for the twin: a changed rate, a dropped effect, a changed seed mix, a coupling that is wired to the wrong sign, an off-by-one in
the days-to-expiry. All killed, or each survivor explained.

## 7a. Margins, fixed before the first measurement **[choice]**

* **G2 (C):** on respiratory items, weekly units in the winter weeks against the summer weeks: `stats test t2` gives a positive difference with
  p < 1e-6, and the ratio of the two means is within 25 percent of the ratio the twin's parameters give without stockouts (stockouts bias it
  down; the bound is wide on purpose). On chronic items (no seasonal effect in the twin) p >= 0.001; and with the twin's seasonal amplitude set
  to zero, respiratory items give p >= 0.001. Seeds are fixed, so the outcome is a function of the code, not of luck.
* **G4 (C):** on the last 12 weeks, held out in time, the model's mean absolute error is at most 0.90 times the smaller of the two baselines'
  (the training mean, and last week's units), and at least 0.90 times the noise floor (the mean absolute deviation of a Poisson variable at the
  twin's true mean; a model that beats the floor has seen something it should not).
* **G8 (B and the excursion classifier):** in each decile of predicted probability on at least 1,000 held-out rows, the observed rate is
  within 0.05 of the predicted one, or within 5 binomial standard deviations of it if that is larger.
* **G3 (the coupling from a stockout to a lapse, U2c), fixed 2026-11-12 before the coupling was built or measured.** The twin raises the probability that a patient
  fails to fill a refill by `lapse_stockout_ppm` (150,000, that is 0.15 in absolute terms) when the patient's home pharmacy was out of that item in the four weeks
  up to the due date, and the effect is additive, so the difference in the lapse proportion between refills that saw a stockout and refills that did not should be
  about 0.15. On the `large` size (20,000 patients, so the standard error is a few thousandths): with the effect at its value, `stats test prop` of the lapse
  against "saw a stockout" gives a difference within 0.02 of 0.15 and p < 1e-6; with the effect set to zero, the difference is within 0.02 of zero and p >= 1e-3.
  A difference that misses the 0.02 bound is **reported as failed**, and what is learned from it (selection of who is still being refilled, for one) is written
  down as a finding, not absorbed into a wider bound.
* A margin that a measurement then fails is **reported as failed**, with the number. It is not moved to fit the number.

## 8. Milestones, each its own pull request

| | what | done when |
|---|---|---|
| **U0** | this document, reviewed | the maintainer says go; the **[open]** items answered or accepted |
| **U1** | the twin library (generator, world file, `truth.json`), G1, and how `flow` starts it (section 6) | G1 passes and fails on its mutants |
| **U2a** | C's twin tables (weekly dispensing with stock, expiry write-off and stockout censoring) and the forecast: G1 for the new tables, G2, G4, G7 | the README output is printed by `flow` records |
| **U2b** | C's decision: the replenishment model in `solve`, with G5 and G6 for orders | `solve verify` accepts every plan |
| **U2c** | the coupling C to B (the lapse hazard sees stockouts), with G3 | the coupling is found at its value and not at zero |
| **U3** | B end to end, with G8 | same |
| **U4** | A end to end, with G5, G6 and the `opt` calibration; the coupling A to C | same |
| **U5** | the closed loop: a week of the whole chain, one command | the loop's numbers are reproducible bytes |
| **U6** | a measured run on one machine (machine, threads, load, minimum of N) and the claims the numbers support | numbers in section 10 |

The order is C, B, A because C produces what B and A consume; **[open]** whether A (the most solver-heavy) should come earlier.

## 9. Open

1. **Where it lives. [decided by the maintainer, 2026-11-12]** In cancho-flow: this document in `docs/`, the example in
   [`examples/pharma-chain/`](../examples/pharma-chain/). Reasons: the example uses the built binaries of cancho-table, -stats, -ml, -solve
   and -opt at commits it pins, and no sibling depends on flow, so the pins form no cycle (cancho's siblings all pin cancho); and what the
   example shows is `flow` recording each step. It was first put in cancho (cancho#768) and moved here. The example is content that `flow`
   records, not flow code: `flow` still knows nothing of the programs it starts. **[open]** a repository of its own would keep flow's
   gates out of it; the document moves unchanged.
2. A reachable public dataset for pharmacy sales, for refill histories and for refrigerated-vehicle energy (section 3).
3. The Telco file: whether to use it as a smoke test, and its licence (section 3).
4. ~~How the Python twin is started by `flow`~~ **Settled in U1** (section 10): `python3` is a symlink in the baked programs directory and the twin's files are `--in`.
5. **How large a routing model `solve` handles**, measured in U4 before the design depends on it (U2b measured a replenishment model, not a routing one; see section 10): a stop order within a truck is a small
   travelling-salesman problem; the example uses it only as far as the measurement allows.
6. ~~The margins of G4 and G8~~ **Fixed 2026-11-12, before any measurement of either (section 7a).**
7. Whether `ml` has a forecasting form beyond features and lags with a time split; this design assumes it does not, and says so in the README.
8. **`plot`** (cancho-plot) is a seventh repository and pins an older compiler (`cancho = "9934b11"`, in its `cancho.toml`, read 2026-11-12).
   The session that wrote this has read access only. *Measured 2026-11-12:* it builds with cancho `51524d2` and writes a text chart from
   CSV on a Linux x86-64 machine; nothing more was run. Its pin move and its figures are for another session, by the maintainer's decision.
9. **Domain review.** The pharma specifics (cold-chain band, controlled-item caps, shelf lives, adherence grace period) are choices; a
   person who works in this field should review them before the README presents the example as realistic.

## 10. Results

### U1: the twin library, G1, and how `flow` starts it (2026-11-12)

*Machine: the cloud container of the session that wrote this (Linux x86-64, Python 3, one run each; other platforms are not measured). Code:
`examples/pharma-chain/` (`twin.py`, `twinlib/`, `world.json`, `scripts/check_twin.py`, `scripts/flow_twin.sh`). The twin so far generates the shared
entities only (items, pharmacies, patients) and `truth.json`; the three use cases add their own tables in U2 to U4.*

* **G1 holds on the committed twin [measured]:** `python3 scripts/check_twin.py` passes in about 9 seconds: the SplitMix64 reference values for seed 0,
  the moments of `normal_micro` over 20,000 draws, two runs of the same world, seed and size with identical bytes in every file, another seed
  with different bytes, independence of the tables (one more item moves neither pharmacies nor patients), the row counts, the shares on the large
  size recounted from the CSV within 5 standard deviations, the 0 and 1,000,000 ppm extremes, no working directory or host name in any file, 15
  refusals each with its `twin.<name>` tag and nothing written, and 300 random argument lists with no traceback.
* **G1 can fail [measured]:** `python3 scripts/check_twin.py --mutants`: the control passes and **11 of 11 mutants are killed**, each by the check
  that targets it (a seed ignored, a path in `truth.json`, an extra row, a share ignored, weights ignored, eleven uniforms instead of twelve, `..`
  allowed in `--out`, shared streams, an unknown parameter allowed, Python's `random`, a wrong generator constant). About 23 seconds.
* **Through `flow` [measured]:** `scripts/flow_twin.sh` builds a `flow` whose programs directory holds a `python3` symlink, runs the twin as a
  recorded step in two copies of the tree and gets **the same record, byte for byte** (record id `d9d470c6...`); with the world changed by one
  patient the record differs. About 6 seconds including the `flow` build.
* **What this does not show:** other platforms, other Python versions (the twin uses no floating-point library function, which is why it should
  hold, but it is a reason, not a measurement), or any of the three use cases' own tables.

### U2a: C's twin tables and the forecast, G2, G4 and G7 (2026-11-12)

*Same machine and conditions as U1 (Linux x86-64, one run each, seed 20261112, the `small` size: 8 pharmacies, 60 items, 104 weeks, 49,920 rows of
`dispensing.csv`). Code: `twinlib/core.py` (the simulation), `features.py`, `scripts/pipeline_c.py`. The margins are those of section 7a, committed
(`e1b12b8`) before any of these numbers existed.*

**The twin.** Weekly demand is Poisson at a mean that is the item's base rate, the pharmacy's scale and a seasonal triangle by therapeutic group; the
pharmacy sells what it has (the demand cut at the stock on hand, FEFO, lots that expire), and orders up to 1.5 times the mean of its last four weeks of
*sales* (a policy that is biased by its own stockouts, on purpose). `dispensing.csv` is what a pharmacy sees; `truth/demand.csv` (true demand and true
mean) is what only the gates read. On this run 653 of 49,920 item-weeks were stockouts (1.3 percent) and 2,076 of about 290,000 units were written off.
Both rates are consequences of stylised parameters, not claims about real pharmacies.

**G1, extended [measured]:** the stock identities (`stock_end = stock_start - units`; this week's stock is last week's plus what arrived minus what
expired; what arrives is what was ordered a week before; orders are whole packs; a stockout is exactly demand above stock), the seasonal shape
(respiratory demand at its peak week against half a year away, within 20 percent of the parameters' ratio) and the Poisson moments. **17 of 17 twin
mutants are killed** (11 of U1 and six new: the Poisson mean ignored, the season ignored, no censoring, a wrong stockout flag, no pack rounding, expiry
lost); see the log of this run in the pull request.

**G2 [measured, passes]:**

| | difference, winter minus summer | p | ratio of means |
|---|---|---|---|
| respiratory items | +5.62 units a week | 4.2e-137 | 2.653 (the parameters give 2.688 without stockouts, 1.3 percent apart) |
| chronic items (no effect in the twin) | -0.02 | 0.856 | |
| respiratory items, seasonal amplitude set to zero | +0.02 | 0.901 | |

The bounds were p < 1e-6 when present, p >= 1e-3 when absent, and a ratio within 25 percent: all three hold.

**G4 [measured, passes]**, on the 12 held-out weeks (92 to 103, 5,760 rows), mean absolute error in units:

| | MAE | against the best baseline (last week, 2.323) | against the noise floor (1.678) |
|---|---|---|---|
| training mean | 5.163 | | |
| last week's units | 2.323 | | |
| `ml` boost (100 rounds, depth 4) | 1.829 | 0.787 (limit 0.90) | 1.090 (lower limit 0.90) |
| `ml` forest (100 trees, depth 8) | 1.826 | 0.786 | 1.088 |

Both models sit about 9 percent above the floor of a forecaster that knows the true mean (the floor is for the uncensored mean; sales are censored by
stock, so it is approximate), and not below it.

**G7 [measured, passes]:** 19 recorded `flow` steps (the twin, the features, the splits, the fits and evaluations, the statistical tests, and the
control world), `flow-records check --recursive` clean; changing one byte of a recorded output makes it fail.

**Mutants of the pipeline [measured]:** the control passes and **4 of 4 are killed**: the target leaked into a feature (boost MAE 0.134, below the
floor); the winter and summer labels swapped (G2); the held-out weeks left in the training file (G4's split-hygiene check); the lags and item columns
dropped from the model (MAE 5.167, not under 0.90 times 2.323).

**What the mutants taught, in order.**
* **A survivor, and a gate strengthened.** Training on the held-out weeks changed the error by almost nothing (1.804 against 1.829): this model cannot
  memorise 48,000 rows, so the noise-floor check does not see mild leakage. The gate now also checks the split directly (every training week before every
  held-out week, no shared row), and that mutant is killed by it. The margins were not touched.
* **A mutant dropped, for a reason.** Stale lags (eight to twelve weeks old) did not fail G4, and should not: they still carry each series' level, and
  the model beats the (equally stale) last-week baseline. That is not a faulty forecast, so the mutant is not in the list.
* **`ml` linear is refused** on this file as collinear (`ml.fit.collinear`: the one-hot columns of the groups and the intercept); it is not used here and
  is not a baseline. The baselines are the training mean and last week.
* **`table` could not build the lags** (section 4.1, corrected there): `features.py` does.

**What this does not show:** one seed, one size, one machine; real pharmacies; a model better than the two baselines at a horizon of more than one
week; anything about C's decision (U2b) or the coupling (U2c). That the forecast beats last week's units by 21 percent says what it does on a twin
whose seasonality is a clean triangle, not what it would do on real sales.

### U2b: C's decision, the replenishment model in `solve` (2026-11-12)

*Same machine and conditions as U1 and U2a. Code: `build_models.py` (the model), `costs.json` (the economics, every value a stylised choice), `verify_input.py`,
`scripts/oracle_highs.py`, `scripts/plan_c.py`. HiGHS is scipy 1.18.1 in a scratch environment (`SCIPY_PYTHON`); without scipy the oracle is reported not run and
the gate fails unless `SKIP_ORACLE=1` says it was left out.*

**The decision.** For each pharmacy and held-out week: how many packs of each of the 60 items to order, to minimise the penalty on units short of a service
target (the forecast plus 1.28 times its square root), a proxy cost for units held beyond what the shelf life can sell, and a small cost per unit ordered; with the
room left in the refrigerated and the ambient space as the capacities, and a lower cap for controlled items. Each decision is a mixed-integer program of 180
variables (60 integer) and 122 rows.

**What `solve` did [measured].** All 96 decisions (8 pharmacies by 12 weeks) were solved to optimality, **about 0.035 seconds each** (35 nodes on the first one),
and `solve verify` returned `verified` with the objective checked on every one. This answers part of open item 5: a model of this size is not a problem for
`solve`; a routing model is a different shape and is still to be measured in U4.

**G5 [measured, passes]:** HiGHS, given the *data* of each decision and not the model text, got the same optimum on all 96 (worst relative gap 9.1e-8); and on a
toy decision of four items (1,029 orders tried, the cost written out in the gate apart from the builder) the enumeration and `solve` both give 138.865010.

**G6 [measured, passes]:** recomputed from the raw stock and the capacities, no plan orders more than the room that is left, a fractional pack, or more packs than
allowed, and the objective of every plan is the formula's. A plan with an order past its bound is refused by `solve verify` with `solve.bound-violated`, and one
with an order into a full refrigerated space with `solve.row-violated`.

**G7 [measured, passes]:** 404 recorded `flow` steps (the forecast of U2a, then build, solve, join and verify for each of the 96 decisions) check clean, and a changed
byte is detected. `flow` allows 64 declared files in a step, which is why each decision is its own small step.

**Mutants [measured]:** the control passes and **6 of 6 are killed**: the cold-room constraint dropped (G6: 69 of 96 plans order into a full space), the room
computed without the stock (G6), the sign of the service margin flipped (G5, the toy), a wrong stock written into the model text only (G5, HiGHS, gap 0.36), the
waste cost zero in the model text only (G5, HiGHS), the controlled-item cap dropped (G5, the toy: 4.0 against 138.865).

**A finding about the twin.** The first model was infeasible, and the cause was physical: the pharmacy in the first decision already held 209 refrigerated units
against a cap of 100, because the twin's plain ordering policy never looks at the cap. The constraint is therefore on what can still be received (the room, never
below zero), and 69 of the 96 decisions have no refrigerated room at all. That is a property of the twin's naive policy, not of real pharmacies; it makes the
cap bind often, which is useful to the gate and unrealistic as a picture of a pharmacy.

**Exploratory, not a claim.** No margin was fixed for decision quality before this run, so none is judged. Over the 96 decisions, against the pharmacy's own order and
the true demand of each week: the plan ordered 29,140 units against 33,860; it left 758 units short against 147, of which 6 against 10 on critical items; and 102,351
units on hand beyond demand against 106,460. Under the costs of `costs.json` (a unit short costs 10, or 30 if critical, a unit held beyond cover 2, a unit ordered
0.05) the optimum accepts shortfall on ordinary items to order less, and protects the critical ones. Whether that is a better policy depends on those costs, which
are choices; this run does not show that it is.

**What this does not show:** one forecast, one seed, one size, one machine; a decision that looks more than one week ahead; the real economics of a pharmacy; a routing
or charging model (U4).

### U2c: the coupling from a stockout to a lapse, G3 (2026-11-12)

*Same machine and conditions as before. Code: the refill series in `twinlib/core.py` (`refill_series`), `scripts/coupling_c.py`. The G3 margins (section 7a) were committed
(`0428695`) before this code was written.*

**The twin.** Each patient takes `n_items` distinct chronic items from the home pharmacy. A refill is due every 4 or 12 weeks from a random first week. It is not filled
(a lapse, and the series ends) with a probability that adds a base (2 percent), 1 point per extra item, 0, 1.5 or 4 points by co-payment band, 0 to 3 points by age band, and
**15 points when the home pharmacy was out of that item in the four weeks up to the due date**. On the `large` size: 442,014 refill events, 17,114 of which saw a stockout
(3.9 percent) and 25,468 lapses.

**G1, extended [measured]:** the series of every patient-item is recounted from the CSVs (chronic items only, one home pharmacy, a fixed interval, a start below the interval,
no refill after a lapse, `stockout_seen` equal to what `dispensing.csv` says, counts equal to `truth.json`), and the coupling is found at its value and not found at zero, at
4 standard deviations. **21 of 21 twin mutants are killed** (the 17 of U2a and four new: the coupling ignored, the window off by one, refills after a lapse, the wrong home
pharmacy).

**G3 [measured, passes]**, `stats test prop` of the lapse against "saw a stockout", as recorded `flow` steps:

| | lapse proportion, saw a stockout minus did not | p | refills (saw / did not) |
|---|---|---|---|
| the coupling at 0.15 | +0.1443 | below the smallest double (reported as 0) | 17,114 / 424,900 |
| the coupling set to 0 | -0.0032 | 0.052 | 19,061 / 446,872 |

At its value the difference is 0.0057 below the parameter (bound 0.02, p < 1e-6); at zero it is -0.0032 (bound 0.02, p >= 1e-3). Both hold. The small shortfall from 0.15 is
real in the sense that it is far outside the standard error (a few thousandths) and is not explained here; a candidate is that a series ends at a lapse, so the refills that
are observed late in time come from patients who were less likely to lapse, but this was not tested. The zero-coupling p of 0.052 clears its bound of 1e-3 and is not
comfortably far from 0.05; that is what a null difference looks like at this sample size.

**G7 [measured, passes]:** four recorded steps (two twins, two tests) check clean, and a changed byte of `refills.csv` is detected.

**Mutants of the analysis [measured]:** the control passes and 2 of 2 are killed: the coupling ignored by the twin (the difference falls to -0.0032), and the test grouped by the
wrong column (+0.0025). **A third mutant, asking `stats` for the other success level, is not in the list because it is equivalent:** the fill proportion's difference is the
lapse proportion's with the opposite sign, and the gate puts both on the lapse's sign, so the verdict is rightly the same.

**A disclosure.** While checking the output format of `stats test prop` I ran it once on the twin's output and saw the estimate (-0.1443 for the other sign) before the gate
existed. The margins had been committed before the coupling code was written, and nothing was changed after that look; the gate uses the same seed.

**What this does not show:** that the 0.15 is realistic (it is a choice); that a model recovers the effect (that is U3); the reverse direction, patients' refills as the
demand that pharmacies see (U5); one seed and one machine.

