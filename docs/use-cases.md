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
* **G2, G4 and G8 for B (U3a), fixed 2026-11-12 before the model of the lapse was built or measured.** On the `large` size, the unit being a refill event, the lapse the
  label, and a time split: fit on due weeks before 60, calibrate on 60 to 77, test on 78 to 103.
  * **G2:** `stats test chisq` of the lapse against each of the number of items, the co-payment band, the age band and "saw a stockout" gives p < 1e-6 for each in the twin as it
    is; in a control twin whose four lapse effects are set to zero (the base stays) each gives p >= 1e-3.
  * **G4:** on the test weeks the log loss of the calibrated boost is at most 0.98 times that of the constant model (the training lapse rate), and at least 0.99 times the log
    loss of the true probabilities, which the twin writes to `truth/` and the analysis never reads (a model that beats the truth has seen something it should not).
  * **G8:** in each decile of the calibrated probability on the test weeks (at least 1,000 rows each), the observed lapse rate is within 0.05 of the predicted one, or within
    5 binomial standard deviations of it if that is larger. The uncalibrated probabilities are reported against the same bound and are not judged by it.
* **G5, G6, G9 for the outreach decision (U3b), fixed 2026-11-13 before the decision was built or measured.** The unit is a pharmacy and a test week (78 to 103): the refill events
  due that week at that pharmacy (between 82 and 176 in the twin, **[corrected 2026-11-13: this said about 300; the large size has 20 pharmacies, so 26 test weeks give 520 decisions, not the 208 written here and below]**), each given at most one of four outreaches (call, reminder, 90-day switch, home delivery) or none. An outreach lowers the lapse
  probability of that event by a fraction `u` (`outreach.json`: every number a **choice**, and the twin's own effect is the same number: the planner is *given* the uplift, which is a
  stated limitation, not a finding). The value of an event is its avoided lapse times the days its refill covers; the decision maximises the sum under the pharmacists' minutes, a
  money budget and the home-delivery slots of that pharmacy and week. It uses only the calibrated probability of U3a, never `truth/`.
  * **G5:** `solve` returns an optimal and `verified` plan on every one of the 520 decisions; HiGHS, given the data and not the model text, gets the same optimum on every one (relative
    gap at most 1e-6); on a toy of five events an enumeration of all 5^5 assignments (written in the gate apart from the builder) gives the same optimum.
  * **G6:** recomputed from the raw files, no plan exceeds the minutes, the money or the slots, none gives an event two outreaches, and each plan's objective is the formula's; a plan
    with an event given two outreaches is refused by `solve verify` with a rule tag, and so is one over the minutes **[corrected 2026-11-13: this said "with another" tag; both are `solve.row-violated`, which names the row, so the tag does not tell the two apart]**.
  * **G9 (what the decision is worth, judged on the twin's true probabilities, which the twin writes to `truth/` and the planner never reads):** the true value of the plan made from
    the calibrated probabilities is at least 0.90 times the true value of the plan made from the true probabilities (the best that can be done with these constraints), and at
    most 1.0 times it (more would mean the evaluation or the planner has seen the truth); at least 1.25 times the true value of a baseline that gives the
    outreach in the order the events are listed (patient order) until the minutes run out, cheapest outreach first; and the value the plan *expects* (calibrated probability)
    is within 0.10 of its true value, as a fraction of the true value. In at least half of the 520 decisions at least one of the three limits binds (otherwise the decision is
    trivial and says nothing). A margin that fails is reported as failed.
* **G10, the size `solve` can take for A's route selection (U4, open item 5), fixed 2026-11-13 before any routing model was built.** *Choice of model:* the day's deliveries are covered by
  routes picked from a pool that a program generates (every subset of up to 3 deliveries, in the order of their window ends, that meets every time window), each route to be driven by
  one of K = 8 trucks (**[corrected 2026-11-13, before any timing was taken: this said K = 4, which with at most 3 stops a route covers at most 12 deliveries, so D = 14 and 18 were infeasible by arithmetic; one test run of D = 10 on one seed, which answered `infeasible` in 0.04 s, is how this was seen; nothing else was run]**) whose battery must hold the route's energy plus a reserve, each truck at most one route a day, each delivery exactly once, cost = energy price times energy plus a fixed
  cost per route (stop order is data, as section 4.2 says; `solve` lists "vehicle routing as a dedicated API" as not in scope, cancho-solve `docs/design.md`, the "Not in scope" paragraph at the top). The measurement is on random seeded
  instances from `scripts/route_pool_size.py`, not on the twin: `solve run` with its defaults, wall time (the process, `solve check` included), minimum of 3 runs, the load on the machine written beside the number.
  **Claims, each of which the measurement can refute:** (a) D = 10 deliveries on three seeds: `optimal` in at most 5 s each; (b) D = 14 on three seeds: `optimal` in at most 60 s each; (c) every
  `optimal` objective equals HiGHS's on the same data to 1e-6 relative. **Rule fixed now for what follows:** U4's decision uses the largest D (10, 14 or 18) for which all three seeds pass its bound
  (a at most 5 s; b at most 60 s; for 18 no bound is claimed: it is run with the node limit and reported); if (b) fails, U4 uses D = 10 and says why, and the failure goes into section 10 and to
  cancho-solve as a model of that shape.
* **G10b, the same route selection with the trucks aggregated into classes (U4), fixed 2026-11-14 after G10 failed (section 10) and before the aggregated model was built or run.** The symmetry
  explanation of G10 is a hypothesis, not a finding; this tests it. The model: 4 classes (the batteries 60, 80, 100 and 120 kWh), each taken by at most 2 routes (the 8 trucks of G10 were these four batteries twice),
  integer variables `y[r,c]` in 0..1 with the same cover rows, the same cost and the same battery rule. Same instances, seeds, pool rule, constants and machine description as G10; the load on the machine written beside the numbers
  (the mutant runs of U3b may be running: if so the load shows it and the times are upper bounds on an idle machine, **a choice** stated now so that a miss is not blamed on it afterwards).
  **Claims, each of which can be refuted:** (a') D = 10 on three seeds: `optimal` in at most 5 s; (b') D = 14 on three seeds: `optimal` in at most 60 s; (c') every `optimal` objective equals HiGHS's on the aggregated model to 1e-6 relative;
  (d) on D = 18, which both models solve, the two optimal objectives equal each other to 1e-6 relative (the reformulation does not change the optimum). **Rule, fixed now:** if (a') and (b') hold, U4's decision uses the
  aggregated model at the largest D that passes, and trucks are assigned within a class afterwards by a program (an arbitrary choice among equals, stated); if either fails, the symmetry explanation is **not** supported and is reported as such;
  U4's decision then keeps stop order and route selection out of `solve` (the twin gives the routes as data and `solve` does the charging plan only), and says so.
* **G1 and G2 for A's twin (U4a), fixed 2026-11-14 before the delivery tables were written.** *The twin (stated now so that the margins mean something):* days are weeks times 7; a day's outside temperature in whole
  degrees is a mean plus a seasonal triangle plus noise; each pharmacy has a delivery on a day with a probability; the day's deliveries are sorted by the end of their two-hour window and cut into routes of at most 3 stops, the
  routes taking the trucks in order (so no truck has two routes in a day and routes per day never exceed the trucks); a stop's energy in watt-hours is driving (distance times a rate) plus refrigeration (a power times the minutes, raised by a fraction
  per 10 degrees above 20) plus the doors (a power times the minutes open), with a noise of a few percent; a stop's temperature excursion has a probability that is a base plus a term per minute of the doors open plus a term per 10 degrees above 20. The
  analysis side sees the energy of each stop (not its parts), the minutes, the door minutes and the temperature; the parts and the probability go to `truth/`. Every coefficient is a **choice** in the world file.
  * **G1 (for the new tables):** the same world, seed and size give the same bytes, and another seed another file; the energy of a route is the sum of its stops' energy exactly; each delivery appears in exactly one route; no truck has two routes
    on a day; every route's energy fits its truck's battery with the reserve of the model of section 4.2 (a violation count of zero, the twin being built to keep it); the tables can be asked for with and without the delivery group and the
    older tables are byte for byte what they were (the digests of U3a are unchanged).
  * **G2:** on the `large` size, `stats test t2` of the energy per minute on days at or above 25 degrees against days at or below 15 gives a positive difference with p < 1e-6, and in a control whose refrigeration-temperature fraction is zero p >= 1e-3
    (the driving share makes the energy per minute depend on speed and not on the temperature, so the control is clean by construction; if it is not, that is a finding); `stats test chisq` of the excursion against the door-open band (0 to 2, 3 to 5, 6 or more
    minutes) gives p < 1e-6, and in a control whose door term is zero p >= 1e-3; the same for the excursion against the temperature band (cool below 15, mild 15 to 24, hot 25 or more) with the temperature term zero in its control.
* **G2c, the heat effect on excursions with a larger stated effect (U4a), fixed 2026-11-14 after G2 for heat failed (section 10, "U4a") and before the world file was changed or anything was run.** *Disclosure: this margin and its coefficient were made after
  seeing that failure, on the maintainer's choice (option 2 of that section).* The twin's `excursion_per_10c_ppm` goes from 40,000 to **150,000** (0.15 of probability per 10 degrees above 20, about 11 points on the hot days of the failed run, a **choice**, not read from any fleet). The power was
  computed first, from the distribution of the outside temperature and of the door minutes over the 7,295 stops of the failed run (the same seed: unavoidable) and the true probability formula, for the chi-square of the excursion against the 3 temperature bands on 2 degrees of freedom: non-centrality
  **10.6** at 40,000 (the probability of a statistic above the 27.6 that p < 1e-6 needs: 0.03, which is why it failed), **65.5** at 100,000 (0.998), **138.1** at 150,000 (1.0 to the precision of the calculation). The claim, unchanged in its bound: on the `large` size,
  `stats test chisq` of the excursion against the temperature band gives **p < 1e-6**, and in the control with the term zero **p >= 1e-3**. The other two claims of G2 (refrigeration, doors) keep their margins above and are judged again in the same run, because the change moves the excursion
  rates and nothing else; G1 is unchanged (it recomputes the probabilities from the world file) and is run again. The mutants of `pipeline_a.py` run once this passes. If it fails, it is reported as failed with the number.
* **G4 and G8 for A's models (U4b), fixed 2026-11-14 before the models were built, with the sizing computed first.** *Sizing (from the twin's true probabilities and the stops' features, and the training days only for the energy; no model was fitted):* the large size has 7,295 stops
  (5,468 before day 546, 1,827 from it with 210 excursions) and 2,663 routes. Two models, both on a time split by day, the analysis seeing only what is known at the time of the decision:
  * **Route energy** (a regression, known at planning: stops, distance in km, the day's outside temperature, and the span from 07:00 to the end of the last window). Fit on days before 546, tested from day 546. The baseline is a linear fit on the distance alone. *Sizing on the training days:* mean absolute error of the
    distance-only line 1.564 kWh, of a line on the four features 1.031 kWh, of a model that knew the parts of every stop (the noise floor) 0.668 kWh, mean route energy 36.7 kWh. **G4 for energy:** the boost's MAE on the test routes is at most **0.80** times the distance-only baseline's on the same routes, and at least
    **0.95** times the noise floor of those routes (a model that beats the floor has seen something it should not).
  * **Excursion** (a classification of a stop, known when the doors close: the minutes the doors were open, the outside temperature, the minutes since the last stop and the position in the route). Fit on days before 364, calibrated (isotonic) on days 364 to 545, tested from day 546. *Sizing:* a model that knew the true
    probabilities has a log loss of **0.9445** of the constant model's on the test stops (the 1st to 99th percentile over 2,000 redrawn outcomes: 0.917 to 0.973), so a fitted model cannot be asked for much. **G4 for the excursion:** the calibrated log loss is at most **0.985** times the constant model's (the training rate) and at least
    **0.97** times the log loss of the true probabilities on the test stops (a lower bound that allows for the sampling of 210 positives; a model below it has seen something it should not). **G8 for the excursion:** the deciles of G8 need 1,000 rows each, which 1,827 stops do not have, so **five groups of equal size by rank** (about 365 rows each): the
    observed rate within 0.05 of the predicted one, or within 5 binomial standard deviations if that is larger; the uncalibrated probabilities reported against the same bound and not judged.
  * **Split hygiene** as in U3a: every fit day before every calibration day before every test day, no row in two files. **G7** as before (the recorded steps check clean and a changed byte is detected). The mutants of `pipeline_a2.py` run once the control passes.
* **G4b, the excursion model as a logistic model (U4b), fixed 2026-11-14 after the boost failed G4 (section 10, "U4b") and before the logistic model was run through the pipeline.** *Disclosure: the model family was chosen on the maintainer's decision (option 2 of that section), after I had seen, on the test stops, that a logistic
  model reaches 0.9619 of the constant model's log loss and the boost 1.0167. The choice is therefore not clean: it was not made on the calibration days.* What changes: the excursion step fits `ml --model logistic` instead of `--model boost`, on the same four features (the door minutes, the temperature, the minutes since the last stop and the position
  in the route: the declared set, not the two-feature variant that did marginally better), the same split, the same isotonic calibration on days 364 to 545. **What does not change:** every bound of G4 and G8 for the excursion (calibrated log loss at most 0.985 of the constant model's and at least 0.97 of the true probabilities'; five groups, within 0.05 or 5 binomial standard deviations),
  the route-energy boost and its margins, split hygiene, G7. The energy model is not rerun in any other way. The mutants of `pipeline_a2.py` run once this control passes. If it fails, it is reported as failed with the number.
* **G5, G6, G11 and G12 for A's decision (U4c), fixed 2026-11-14 before the charging model or the calibration was built, with the sizing computed first.** *Choices of the model (stated now):* a night is the nights of days 546 to 727 (182 of them, the test days of U4b); the trucks that ran a route that day each need
  the *predicted* energy of that route plus a safety of 3.0 kWh by 07:00 the next day; a truck can draw from the hour after its route ends (the hour of its last arrival, rounded up) to the hour before 07:00, at most 11 kW, and at most 4 trucks charge in an hour (`charging.json`, all choices); the grid connection of the depot file (`cap_kw`, what the warehouse leaves)
  bounds the sum of the hour; the price is the depot file's tariff; the aim is the cost. It is the model of `docs/examples/ev_depot.sol` of cancho-solve, built per night from the data. Route selection and stop order are not in `solve` (G10, G10b).
  *Sizing (the twin's own nights on a sample of 31 of the 182 test days, an exact formulation in scipy's `milp`, no model of ours):* 2 to 5 trucks a night, routes ending between 10:00 and 14:00, so about 20 hourly slots; the cost of the optimal plan against a plan that plugs every truck in on arrival and charges at once (as far as 4 chargers allow) is **0.451 to 0.458**; the model's
  residual standard deviation is about 1.4 kWh (1.25 times the MAE of U4b), so a safety of 3.0 kWh is about 2.1 standard deviations; the distance-only baseline's about 2.0 kWh (1.5 standard deviations).
  * **G5:** `solve` returns an optimal and `verified` plan on every one of the 182 nights; HiGHS, given the data and not the model text, gets the same optimum on every one (relative gap at most 1e-6); on a toy night of two trucks and four slots, an enumeration of every pattern of plugged slots, with the best charge for each pattern found by filling the cheapest slots (written in the gate apart from the builder), gives the same optimum.
  * **G6:** recomputed from the raw files, no truck is charged less than its need, before its arrival, beyond 11 kW in an hour, or with more than 4 trucks in an hour; no hour is over the grid connection; each plan's cost is the formula's; a plan that undercharges a truck and a plan over the connection are each refused by `solve verify` with a rule tag.
  * **G11 (judged on the energy the routes actually used, which the twin writes and the plan never sees):** the share of route-nights on which the plan charged less than was used is at most **0.05** for the plan from the boost's predictions, and the same share for a plan from the distance-only baseline's predictions (the same safety) is at least **2 times** it (sizing: 1.4 percent and 6.7 percent from the normal approximation, a ratio of about 5); the cost of the optimal plan is at most **0.60** times that of the plug-in-and-charge-now plan on the same needs (sizing 0.458).
  * **G12, `opt` calibrates the twin's coefficients to the telemetry:** `opt minimize` (Nelder-Mead) over the four coefficients of the per-leg energy (watt-hours per km, refrigeration watts, the heat fraction, door watts), from a stated first guess (350, 1,200, 150,000 and 1,500, which is not the twin's values), on the 9,958 legs of the large size, minimising the sum of squared errors. *Sizing:* the same four coefficients solve a linear least squares exactly (the model is linear in them after a change of variables), whose standard errors are 0.08, 0.3, 1.8 and 3.6 percent. The claims: the sum of squares `opt` reaches is within **1.001** of the exact minimum (computed in scipy, apart from `opt`); each coefficient is within **2, 3, 10 and 15 percent** of the twin's value (about 25, 10, 5 and 4 standard errors); and in the control with the heat fraction zero, the calibrated heat fraction is below **25,000** (4.5 standard errors) where the twin's value is 300,000.
  * **Split and records:** G7 as before. The mutants of `pipeline_a3.py` run once the control passes. A margin that fails is reported as failed with the number.
* **G1 for the coupling and G3d, the coupling from a late or a warm delivery to the pharmacy's stockouts and write-offs (U4d), fixed 2026-11-14 before the pipeline that judges them or the checks of the coupled tables were written.** *The mechanism (stated now, a choice, already in the twin as the table `coupled`, which needs
  `dispensing` and `delivery`):* a pharmacy-week is **late** when any stop of that pharmacy in that week arrived after its window closed, and **warm** when any stop had an excursion (the cabin above 8.0 degrees). In a late week what was due to arrive is held to the next week (so two orders can arrive together); in a warm week the cold-chain items that arrive are thrown away on arrival (they are received and written off the same week).
  Nothing else changes, no parameter is added, and without the table `coupled` every older table is what it was. *Sizing, on seed 7 and not the gate's seed 20261112, after the mechanism was written (so the numbers were seen and the mechanism was not tuned to them):* 186 of 2,080 pharmacy-weeks are late and **643 (31 percent) are warm**, which is a harsh coupling and a stated choice of this example, not a property of any fleet; stockouts of items in late weeks 0.178 against 0.037 elsewhere (difference **+0.141**), and in
  the uncoupled twin (the same delivery data, no effect) 0.011 against 0.012 (**-0.001**, standard error 0.0006); cold-chain items that received stock are written off in 100 percent of warm weeks against 0.01 percent elsewhere, and in 0.00 against 0.00 in the uncoupled twin.
  * **G1 for the coupled tables:** the same world, seed and size give the same bytes; each pharmacy-week's `late` and `warm` in `truth/coupling.csv` are recomputed from the delivery files (a stop after its window; a cabin above 80 tenths of a degree); the stock ledger holds with the arrival rule recomputed from them (a late week receives nothing and holds what was due; the next week receives that and what was ordered; a warm week writes off what a cold-chain item received, the same week;
    the stock chain of every item identity as before); with no delivery at all (`delivery_prob_ppm` 0) the coupled dispensing file is byte for byte the uncoupled one; the coupled table without `dispensing` and `delivery` is refused with a rule tag; and no older table moves when `coupled` is not asked for.
  * **G3d, the coupling found at its value and not at zero** (the large size; the analysis side flags a pharmacy-week from the delivery files it sees, not from `truth/`): `stats test prop` of the stockout against *late week* gives a difference (late minus others) of at least **0.05** with p < 1e-6, and in the control (the uncoupled twin) a difference within **0.01** of zero with p >= 1e-3. `stats test prop` of the write-off (among cold-chain items that received stock that week) against *warm week* gives a difference of at least **0.5** with p < 1e-6; in the control both groups' write-off shares are at most **0.01** (read from the file, since a test of two proportions that are both near zero may be refused by `stats`; if it is, that refusal is reported).
  A difference below the bound is reported as failed with the number. The mutants of the coupled twin run in `check_twin.py`, those of the pipeline in `scripts/pipeline_ad.py`, once their controls pass.
* **G13 to G17 for the loop (U5), fixed 2026-11-14 before `scripts/loop.py` was written.** *What the loop is, and is not (stated now):* one command, `scripts/loop.py`, runs **a week of the whole chain** on the large, coupled twin (`--tables core,dispensing,refills,delivery,coupled`, seed 20261112) for week **100** (days 700 to 706), every step a recorded `flow` step:
  **C**, the weekly forecast (a boost fitted on weeks 48 to 99, the lag features of U2a) and the 20 replenishment decisions of week 100 in `solve`; **B**, the lapse model (a boost fitted on events due before week 74, isotonic calibration on weeks 74 to 99), the refill events due in week 100, and the 20 outreach decisions in `solve`; **A**, the route-energy model (a boost fitted on days before 700, as U4b's) and
  the overnight charging plan of each night of days 700 to 706 that has routes, in `solve`; then a summary. The loop is **closed in the data** (a late or warm delivery of A changes C's stockouts and write-offs, which change B's lapses, through the coupled twin) and **open in the decisions**: the plans (orders, outreaches, charging) are computed and checked but do **not** feed back into the twin's world, which
  is generated whole beforehand. A loop whose decisions change the next week's world would need the twin to run week by week with the tools as its agents; that is not built and is not claimed. The scale choices (52 weeks of fit, 26 of calibration) are choices, not tuned.
  * **G13, the numbers are reproducible bytes:** two independent runs of the command (fresh working directories, no shared state) give a byte-identical `summary.json` and byte-identical `flow` records (every file of `rec/`, by name and content). The command prints the digest of `summary.json`; this is on one machine (the other platforms are U6).
  * **G14, every plan is checked by something that shares no code with the search:** each plan of the loop is `verified` by `solve verify` with its objective checked, and the optimum equals HiGHS's on the same data (relative gap at most 1e-6) on all of them, **or**, for a plan that stopped at the node limit as `feasible`, HiGHS's optimum lies inside the plan's proven interval (the rule of U3b); the number of plans of each kind, and how many stopped at a limit, are printed.
  * **G15, the summary is what the plans say:** `summary.json` (per pharmacy: units ordered and the objective of its replenishment plan; per pharmacy: events, outreaches by kind and the expected value of its outreach plan; per night: trucks, planned kWh and the cost of its charging plan; and, from the delivery and dispensing files, the late and warm pharmacies of week 100 and their stockout items in weeks 100 and 101) is recomputed by the gate from the raw plan and data files, not from `summary.json`'s own sources, and must equal it exactly.
  * **G16, the stages are the ones that were gated:** the loop's number of decisions is 20 (replenishment), 20 (outreach) and one per night with routes (at most 7); the week of every decision is 100 (the days 700 to 706 for charging); no plan reads a row of a later week (checked on the files' week and day columns); the coupling is visible in the loop's week (the late and warm pharmacies listed come from the delivery files and the stockouts from the dispensing file; no statistical claim is made on one week).
  * **G17, as in every pipeline:** `flow-records check` is clean on every step and detects a changed byte of a recorded output. The mutants run once the control passes: a stage reading the wrong week, a plan taken from another pharmacy's model, a stage missing from the summary, a nondeterministic value (a clock) in the summary, the summary not equal to the plans, a decision of a later week in a stage.
* **The measured run (U6): what is measured, and what may be claimed, fixed 2026-11-14 before `scripts/loop_measure.py` existed.** One machine: the Linux x86-64 virtual machine this work ran on (its model, cores, kernel and the load average at the start of each run are written beside the numbers); no other platform is measured, so nothing is claimed about macOS or aarch64.
  * **M1, the time of one loop:** five sequential runs of one loop (`loop.py --once`, the whole command's work for one run, fresh directory each, `ml --threads` at its default of 1), started when the load average is below 0.3 and nothing else of ours is running; the figure that may be stated is the **minimum** of the five, with the median and the maximum beside it. **If the maximum is more than 1.25 times the minimum the figure is called noisy** and the median and the spread are what is stated.
  * **M2, the bytes over the runs:** the five runs give the same `summary.json` and it equals the digest U5 recorded (`a701f5de6ac65856`, sha256 prefix); a different digest is reported as drift, with what changed in the repository since, and is not explained away.
  * **M3, the thread count:** one more run with `--threads 4` on every `ml fit` gives a `summary.json` byte for byte equal to the runs at 1 (the documented claim of `ml`: no thread count changes a byte of a model file or of an answer), here tested through the whole chain.
  * **M4, where the time goes:** the wall time of each program (`ml`, `solve`, `table`, `python3`) summed from the `flow` answers of one run, and its share of the sum of the steps; the stages (twin, C, B, A, summary) are timed around their steps. Shares of the loop may be stated for this machine only.
  * **Not claimed, whatever the numbers are:** any speed against another tool or library (none was measured here); any scaling beyond this size and week; any statement about another machine or another number of cores; any statement that the loop's numbers are good (U2 to U4 judged the stages). The timing is outside the records: the records hold no time.
* **G18 to G20 for the stepping twin (U7a), fixed 2026-11-14 before the twin was changed.** *What U7 is for (stated now):* U5's loop is closed in the data and open in the decisions: the plans are checked but do not change the world, so nothing says whether a plan is better than what the pharmacy would have done. U7 closes it: the twin runs a week at a time, the decisions of week w (made at the end of week w, from what is known through week w) are inputs to the world after it, and the
  same world and seed can be run with the twin's own policies and with the tools' plans. **[corrected 2026-11-14, while building: this said the decisions of week w are made at the end of week w-1 and are inputs to week w; the built interface is a file `week-<W>.json` made at the end of week W, whose orders are those placed at the end of W (arriving in W+1), whose outreach acts on the refill events due in W+1, and whose charges are for the days of W+1]** *The interface, a choice:* a decisions file for a week holds `orders` (pharmacy, item, units: the order the pharmacy places at the end of the week, instead of its order-up-to rule), `outreach` (patient, item, action among the four of `outreach.json`: the lapse chance of that refill event is multiplied by one minus the action's uplift) and `charge` (truck, kWh, for the night after the week's days: a route
  whose truck holds less than the energy the route actually uses ends short, its remaining stops are not delivered that day, and the pharmacy-week counts as late for the coupling of U4d). No decisions file, or an empty one, means the twin's own policies. Everything not named is the twin as it is. This design makes U7b and U7c possible and claims nothing about them.
  * **G18, the stepping twin is the batch twin:** for the seeds 20261112 and 1 and the sizes `small` and `large`, with `--tables core,dispensing,refills,delivery,coupled` and no decisions, the stepped twin writes every file of the batch twin byte for byte (the delivery tables, `truth/` and `truth.json` included), and the older table groups (`core`; `core,dispensing`; `core,dispensing,refills`) too. Seven or more mutants of the stepping (state not carried from a week to the next, a stream drawn in another order, orders applied a week late, a pending order lost at the week boundary, the held order of a late week lost, the refill series restarted, the coupling flags read from the wrong week) are each killed by G18. **[corrected 2026-11-14: this said every one is killed by G18. Without decisions G18 cannot see a mutant that is about decisions (orders a week late, outreach without effect, charges ignored): of the 13 mutants written, 7 are killed by G18, 5 by G19 and 1 by G20, and the results say which.]**
  * **G19, decisions are checked and have only the effects they name:** a decisions file with an unknown pharmacy, item, patient, truck or action, a negative or fractional number, an order above the pharmacy's capacity, a week other than the one asked, or more than 1,048,576 bytes is refused with a rule tag `twin.decision-*` and a repair, exit 2, nothing written, and no input of a fuzz of 300 reaches a traceback. A decisions file that orders nothing for week w changes `dispensing.csv` from week w on (the `ordered` column of week w and the stock after it) and **no row before it** (the prefix is byte for byte the batch twin's) **[corrected 2026-11-14: this said from week w+1 on; the order placed at the end of week w is a column of week w's own row]**; one that gives every event of week w the action `call` lowers the lapses of week w and leaves the demand (`truth/demand.csv`) as it was (demand does not depend on the pharmacy's stock or on a lapse in this twin); a `charge` of zero for a truck makes its routes of the next day end short.
  * **G20, determinism:** the same decisions give the same bytes in two runs, and the order in which the files of a week's decisions are listed does not matter (they are read by name and applied in a fixed order).
* **G21 to G23 and the claims of the experiment (U7b and U7c), fixed 2026-11-14 after U7a and before the loop was written or run, with the sizing taken from U5's kept week (week 100, large).** *What is built and what is left out (stated now):* the tools decide **replenishment orders (C)** and **outreach (B)** inside the stepping twin, week by week; the **charging** decisions (A) are supported by the twin (U7a, G19) and are **not exercised** here: the default policy has trucks always fully loaded, so a plan can only add shortfalls to it, and the planner would need next week's routes, which the twin does not publish. The loop: seed 20261112 and then seed 1, size large, decisions at the ends of weeks **90 to 101**, outcomes over weeks **91 to 103**. The models are **fitted once** on what is
  known through week 89 (C: a boost on weeks 38 to 89; B: a boost on events due before week 64, isotonic calibration on weeks 64 to 89) and never refitted; each week the twin runs from week 0 through the week with the decisions made so far (`--through`), the tools read its files, and their plans become `week-<W>.json`. Every step is a `flow` step. **Four arms** on the same seed: **D**, the twin's own policies (the batch twin); **C**, the orders of the replenishment plans only; **B**, the outreach of the outreach plans only; **T**, both. Demand does not depend on any decision and a refill event keeps its random number (U7a), so
  the arms differ only through the decisions: there is no sampling noise between arms on one seed, and the two seeds are the replication.
  *Sizing (U5's week 100, large, the plans as they were made):* the outreach plan expected **25.2 of 111.1 lapses avoided (22.7 percent)** (the true lapses of that week were 119 of 1,843 events); the replenishment plan ordered **14,310 units for week 100 against the 28,530 that the pharmacies' own rule had ordered for it (minus 49.8 percent)**; from U2b (small) the replenishment plan accepted more shortage to hold less: 758 units short against 147, and it never saw the lapses that a stockout causes (the coupling of U4d is not in its objective).
  * **G21, the loop is the tools' and nothing else:** in each arm every plan is `verified` by `solve verify` and HiGHS equals `solve` on all of them (relative gap at most 1e-6, or inside the proven interval for a plan that stopped at the node limit); each `week-<W>.json` equals what the plans of that week say, recomputed by the gate from the plan files; the twin accepts every decisions file; the files a week's tools read hold no row after that week; the models' fit files hold no week after 89 and no model is refitted after the first decision.
  * **G22, determinism:** arm T of seed 20261112, run twice in independent directories, gives byte-identical final `dispensing.csv`, `refills.csv` and decisions files and identical `flow` records; `flow-records check` is clean on every step of every arm and detects a changed byte.
  * **G23, the arms are what they claim:** arm B's `dispensing.csv` and `truth/demand.csv` are byte for byte D's (outreach does not touch the stock); arm C's `truth/demand.csv` is D's; every table of every arm equals D's for the weeks before 91 except the `ordered` and decision effects that U7a names; the number of decisions is 20 pharmacies times 12 weeks for C and for B.
  * **The claims, each judged on both seeds (a seed that does not meet one is reported as failing it), with their directions fixed now:** **(1) C orders at least 5 percent fewer units than D over weeks 91 to 103** (sizing: minus 49.8 percent). **(2) C has at least 1.5 times D's stockout cells over weeks 91 to 103** (the plan accepts shortage; direction and a low bound, because the size is not sized). **(3) C has more lapses than D over the events due in weeks 91 to 103, by at least 5 percent**: the coupling turns the plan's shortage into lapses that its objective does not count; this is the claim the closed loop exists to test and it may well fail. **(4) B has at most 0.90 of D's lapses over the events due in weeks 91 to 103** (sizing: 0.77 expected). **(5)** the outcome of T is **reported, not claimed**: the sign of the sum of (3) and (4) is the finding.
  * **Reported without margin, because they depend on stylised costs:** units short, units written off and units on hand beyond demand in each arm; the cost of the orders under `costs.json`; the plans' own objective values; the actions chosen. **Not claimed whatever the numbers are:** that the tools beat the pharmacy's policy; that these effects hold at another size, seed count or world; that the example's economics are real.
  * **Mutants of the loop** (run once its control passes): the decisions of the wrong week, a pharmacy's plan written under another's orders, a model refitted with a week after 89, the outreach actions' names swapped, orders not multiplied by the pack size, the outreach part left out of the merge (arm B would equal D), a clock in a decisions file (G22).
* **U8, the lapse cost in the replenishment objective: design, G24 to G26 and the claims, fixed 2026-11-15 after U7c and before any code of it was written or run.** *Disclosure, first:* I have seen the whole of U7c (arms D, C, B, T on two seeds) and I made a hand estimate of the effect below before fixing the margins; nothing of the new arms has been run. *Why this and why it may not work:* the replenishment plan of U2b minimises `pen_i * s_i + waste * over_i + holding * pack_i * q_i` with `s_i` the shortfall against `target_i = forecast_i + z * sqrt(forecast_i)` (`z` = 1.28 for every item). Because the penalty is on the shortfall against a target and the target is the same whatever the penalty, the plan orders up to the target whenever the room allows, so **a larger shortage penalty alone changes almost nothing**: the lever is the target. U7c measured that this plan orders a third to two fifths less than the pharmacies' rule and has 4.1 and 5.8 times its stockout cells, and 1.37 and 1.55 times its lapses.
  *The change (a **choice**, one model, the structure of the model for `solve` unchanged):* the target moves with the cost of the lapses a stockout causes, the way the newsvendor quantile moves with the cost of a shortage. For the plan of week W, pharmacy p and item i, from what is known at the end of week W-1 (the refill events of `refills.csv` due in weeks W-8 to W-1, which the loop's guard keeps to rows due up to the decision week):
  `ev_i` = (events of p and i due in weeks W-8 to W-1) / 8 (events a week); `E_i = ev_i * window * (ppm / 10^6) * L` (the expected lapse cost of one stockout week, with `window` = 4 weeks and `ppm` = 150,000 the world's `stockout_window_weeks` and `lapse_stockout_ppm`, GIVEN to the planner as the outreach uplifts were: a stated limitation); `l_i = E_i / max(f_i, 1)` (per unit short, taking a stockout week to be about one week of forecast units: a **choice**); `b = waste + holding`; `r(x) = x / (x + b)`; `z_i = min(z0 + (Phi^-1(r(pen_i + l_i)) - Phi^-1(r(pen_i))), 3.5)` with `z0` = 1.28 (so that **no lapse cost gives exactly the plan of U7c**), and the target uses `z_i`. **L = 100**, a choice with its reason: a lapse ends a patient's series (the twin has no return), which on average is 10.7 refills, and a refill is taken as one unit at the shortage penalty of 10 (the twin has no revenue, so any value is stylised). **L is fixed here and run once.** Other values of L are *exploratory*, reported as such after, never as the claim, and the result is said to depend on L.
  *Sizing, by hand and not measured:* an item with 6 units of forecast and 0.5 events a week has `E_i` about 29 and `l_i` about 4.8, `r` goes from 0.83 to 0.88 and `z_i` from 1.28 to about 1.5, so the target rises by about half a unit of nine: I expect the stockout cells to fall by 5 to 15 percent, the lapses by a smaller share (only the excess caused by stockouts can go: 549 and 762 lapses over D in C), and the combined arm to stay worse than D. **Arms:** CL (the replenishment plans with the lapse cost) and TL (CL and the outreach plans), on the seeds 20261112 and 1, the same weeks as U7c; D, C and T are those of U7c (the second run of U7c equalled the first byte for byte, so they are not rerun).
  * **G24, the term is what it says:** for every plan of the CL and TL arms the judge recomputes `ev_i`, `l_i`, `z_i` and `target_i` from the final tables (`refills.csv`, `dispensing.csv`) with its own code (the inverse of the normal distribution by bisection on `erf`, not the builder's) and the targets agree to 1e-6 in relative terms; for an item with no event in the window the target is the old formula's exactly; the case where the cap of 3.5 binds is checked with a large L on a fixture.
  * **G25, no lapse cost is the plan of U7c:** with L = 0 the builder with the lapse flag writes the same `.sol` byte for byte, and the same `.json` once its `lapse` member is removed, as without the flag, for the 20 pharmacies of week 95 of the large twin.
  * **G26, the arms are what they claim:** G21 to G23 as in U7c for CL and TL (plans verified, HiGHS agrees, decisions equal plans, models fitted once, records clean in the week of each step, the demand and the weeks before 90 equal D's, the parts of the decisions files right), and every model of the two arms has a `lapse` member (so the flag cannot be dropped unseen).
  * **The claims, on both seeds (a seed that fails one fails it), weeks 91 to 103 as in U7c:** **(L1) CL has at most 0.95 of C's stockout cells. (L2) CL has at most 0.97 of C's lapses. (L3) TL has at most 1.00 of D's lapses** (the combined plan stops being worse than the twin's own policy): **I expect (L3) to fail**, by the gap of 8.9 and 26.1 percent and the sizing above. Reported without margin: units ordered, short and written off in CL and TL, the plans stopped at the node limit.
  * **Mutants (run once the gates pass; the builder ones by `scripts/check_lapse.py`, one by `mutants_loop.py`):** the sign of the quantile shift flipped; the window 4 weeks taken as 1; the events counted over weeks W-8 to W (a week not known yet) instead of W-8 to W-1; the events divided by 4 and not by 8; `l_i` not divided by the forecast; the shift taken from `Phi^-1(r)` alone and not as an increment on `z0`; the cap of 3.5 removed; and the lapse flag dropped in the TL arm (the loop's mutant).
* A margin that a measurement then fails is **reported as failed**, with the number. It is not moved to fit the number.

## 8. Milestones, each its own pull request

| | what | done when |
|---|---|---|
| **U0** | this document, reviewed | the maintainer says go; the **[open]** items answered or accepted |
| **U1** | the twin library (generator, world file, `truth.json`), G1, and how `flow` starts it (section 6) | G1 passes and fails on its mutants |
| **U2a** | C's twin tables (weekly dispensing with stock, expiry write-off and stockout censoring) and the forecast: G1 for the new tables, G2, G4, G7 | the README output is printed by `flow` records |
| **U2b** | C's decision: the replenishment model in `solve`, with G5 and G6 for orders | `solve verify` accepts every plan |
| **U2c** | the coupling C to B (the lapse hazard sees stockouts), with G3 | the coupling is found at its value and not at zero |
| **U3a** | B's model: the lapse predicted from what is known at each due date, on a time split, calibrated; the effects recovered by `stats`: G1 for the true hazards, G2, G4 and G8 for B | the README output is printed by `flow` records |
| **U3b** | B's decision: who gets which outreach under a budget, in `solve`, and the twin's own effect of an outreach (it does not have one yet) | `solve verify` accepts every plan |
| **U4a** | A's twin: trucks, locations, daily deliveries grouped into routes, per-stop telemetry (energy, cabin temperature, door-open minutes), the depot's hourly cap and tariff; G1 for the new tables and G2 (the refrigeration and the door effects found by `stats`, absent in a control) | the README output is printed by `flow` records |
| **U4b** | A's models: a route's energy and the risk of a temperature excursion, on a time split, calibrated: G4 and G8 for A | same |
| **U4c** | A's decision: the overnight charging plan under the depot cap in `solve` (route selection stays out of `solve`: G10 and G10b, section 10), and the `opt` calibration of the twin's coefficients to a telemetry file: G5 and G6 for charging | `solve verify` accepts every plan |
| **U4d** | the coupling A to C (a late or warm delivery shows in C's stockouts and write-off) | the coupling is found at its value and not at zero |
| **U5** | the closed loop: a week of the whole chain, one command | the loop's numbers are reproducible bytes |
| **U6** | a measured run on one machine (machine, threads, load, minimum of N) and the claims the numbers support | numbers in section 10 |
| **U7a** | the twin as a stepping environment: one week at a time, with the decisions of the week as an input; with the policies the twin already has it writes every table byte for byte as the batch twin does | G18 to G20 (section 7a) |
| **U7b** | the decisions enter the world: the replenishment orders, the outreach and the charging of the tools' plans, week by week, each week a `flow` plan | the loop runs for the weeks decided and the records check clean |
| **U7c** | the experiment: the same world and seed with the twin's own policies and with the tools' plans; stockouts, write-offs, lapses and energy shortfalls compared on the weeks decided, margins fixed after U7a and before the run | numbers in section 10, or a failed margin reported |
| **U8** | the lapse cost in the replenishment objective: the target moves with the cost of the lapses a stockout causes; arms CL and TL against the arms of U7c | G24 to G26 and claims L1 to L3 (section 7a); L3 expected to fail |

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

### U3a: the lapse model, calibrated, and the effects recovered; G2, G4, G8 for B (2026-11-12)

*Same machine and conditions as before (Linux x86-64, seed 20261112, the `large` size: 20,000 patients, 442,014 refill events). Code: `features_b.py`, `pred_join.py`,
`apply_isotonic.py`, `scripts/pipeline_b.py`; the twin now also writes the true lapse probability of every refill to `truth/refill_hazard.csv`. The margins (section 7a) were
committed (`d33b6cb`) before any of this was built.*

**Setup.** A refill event is the unit; the label is a lapse; the model sees the number of chronic items, the co-payment and age band as integers, the interval and whether the
home pharmacy was out of the item. Time split: fit on due weeks before 60 (320,834 events), calibrate on 60 to 77 (57,091), test from 78 (64,089). `ml fit --model boost`, `ml
predict --proba`, `ml isotonic` on the calibration part, applied to the test part by `apply_isotonic.py` (a step function), `ml calibrate` and `stats test chisq` looking on. 25
recorded `flow` steps.

**G2 [measured, passes]**, `stats test chisq` of the lapse against each factor, in the twin as it is and in a control whose four lapse effects are zero:

| factor | p in the twin | p in the control |
|---|---|---|
| number of items | 4.4e-236 | 0.120 |
| co-payment band | 0 (underflow) | 0.074 |
| age band | 7.9e-108 | 0.270 |
| saw a stockout | 0 (underflow) | 0.392 |

**G4 [measured, passes]**, log loss on the test weeks: constant 0.21003, boost uncalibrated 0.20194, **boost calibrated 0.20192**, the true probabilities 0.20182. The calibrated boost is
0.9614 of the constant model's (limit 0.98) and **1.0005 of the true probabilities'** (lower limit 0.99): it recovers the twin's hazard to within five hundredths of a percent of
log loss, and does not beat it.

**G8 [measured, passes]**, deciles of the calibrated probability (predicted/observed): 0.021/0.020, 0.030/0.033, 0.031/0.034, 0.039/0.042, 0.043/0.042, 0.049/0.048, 0.055/0.057,
0.061/0.061, 0.070/0.075, 0.128/0.127, at least 6,408 rows each. The largest deviation is 0.10 of its bound. `ml calibrate` with its own defaults says `ok` for both.

**A finding that the numbers make plain.** The uncalibrated probabilities were already calibrated (largest deviation 0.09 of the bound, against 0.10 after the isotonic step; the
overall ratio 1.008 before and 1.023 after). A boost trained on log loss over 320,000 rows has little left for a calibration step to fix, and the step did not help here. It stays in the
pipeline because G8 judges the calibrated probability, and because on a model that is not trained on log loss it would matter; this run does not show that.

**G7 [measured, passes]:** the 25 recorded steps check clean, and a changed byte of `events_main.csv` is detected.

**Mutants [measured]:** the twin's gate now has **22 mutants, all killed** (the 21 before and the true-hazard file with the copay term omitted). The pipeline has **5 of 5 killed**: the
label put into a feature (G4: log loss 0, below the floor); the fit including later weeks (G4's split check: 89,026 rows shared); the stockout tested against the wrong column (G2);
the coupling ignored by the twin (G2: p = 0.052 for the stockout); and the isotonic fit in the wrong direction. Two notes on that run:
* The first run reported two survivors that were faults of the harness, not of the gates: a mutation of mine that left a syntax error (so the pipeline stopped before G4), and one aimed
  at G8. The second is instructive: **G8 cannot see a forecast that says nothing**, because a flat forecast at the base rate is perfectly calibrated in every decile. The inverted fit is
  flat, G8 passes it, and G4 refuses it (log loss 0.20978, not at most 0.98 times 0.21003). The mutant is now aimed at G4, with that reason in the code.
* The two corrected mutants were rerun on their own, not as part of a second full run of the five.

**Disclosures.** (1) While exploring `ml`'s output I saw test-set metrics (a boost log loss of 0.2020 and an AUC of 0.645 on the test weeks) for a model that still used `fills_before`. `ml`
itself reported that feature out of the training range on 75 percent of the test rows (it grows with time), and I dropped it for that reason, which is a judgement made after seeing
test metrics and not before; the margins had been committed first and were not touched, and the final numbers are of the model without it. (2) `ml fit --model constant` takes no
`--positive`, and its summary gives a probability (the training rate) only because the label is 0 or 1, which is what the baseline uses here.

**What this does not show:** that a model can find effects it was not built to find (the twin's hazard is additive and every driver is in the model's inputs, so recovering it is the easy
case); other platforms or seeds; the outreach decision (U3b); real adherence data.


### U3b: the outreach decision in `solve`; G5 fails on 8 decisions, G6 and G9 hold (2026-11-13)

*Same machine and conditions as before (4 cores, one run at a time for the control). Code: `build_outreach.py` (the model), `outreach.json` (the economics: every value a choice), `scripts/oracle_highs_b.py`,
`scripts/plan_b.py`. HiGHS is scipy in a scratch environment (`SCIPY_PYTHON`). The control run is 3,145 recorded `flow` steps and takes about 50 minutes; the margins are those of section 7a, committed
(`19abceb`) before any of this was built.*

**The decision.** Per pharmacy and test week, the refills due that week (82 to 176 events) each get one of call, reminder, 90-day switch, home delivery, or nothing, to maximise the avoided
lapse probability times the days the refill covers, under the pharmacist minutes (150), the money (300) and the delivery slots (10). It is a 0-1 program of 4 binaries per event (328 to 704) and
three knapsack-type rows. It reads only the calibrated probability of U3a and `patients.csv`.

**G5 [measured, FAILS as written].** 520 decisions (64,089 events). `solve verify` accepts every plan; HiGHS, given the data and not the model text, agrees on all 520 (worst relative gap 2.13e-10);
the toy of five events (3,125 assignments) agrees (14.580000 both). **But 8 of the 520 plans are not proven optimal**: they stop at the 20,000-node limit as `feasible`, with a proven gap of at most
4.75e-4 of the objective, and HiGHS's optimum lies inside each `[incumbent, bound]`. The margin said "optimal on every one" and it is **reported as failed**, not widened. What is learned: a
multi-knapsack 0-1 program of this size is not always proved by `solve` in reasonable time (measured on the 1,040 models, the plan ones and the oracle ones, before the limit was set: 2 took longer than 20 s, the
next 13 s, and `flow` ends a step at its deadline, which is why a node limit is how the search ends). The 8 are plans whose objective is within 0.05 percent of the bound; one oracle-plan decision (measured separately at the same limit, W97_P007) also stops at the limit; the run accepts a stopped oracle plan, so the yardstick of G9 is
the oracle's incumbent there, a little below the best possible, which flatters the 0.9991 by at most that decision's gap. A feasible exit status of 1 is by design in `solve` (cancho-solve `docs/design.md` section 5); `flow` records it with `--allow-failure`.

**G6 [measured, passes].** Recomputed from the raw files (`test_cal.csv`, `patients.csv`, `outreach.json`): no plan exceeds the minutes, the money or the slots, no event has two outreaches, and every objective
is the formula's. A plan with an event given two outreaches and a plan with a call for every event are both refused by `solve verify` (exit 2, `solve.row-violated`).

**G9 [measured, passes].** Judged on the twin's true probabilities, over the 520 decisions, in expected adherent days gained: the plan 35,075, the plan made from the true probabilities 35,107 (**0.9991** of it: limits
0.90 to 1.00), the baseline (reminders in patient order while the minutes last) 12,710 (the plan is **2.76** times it: at least 1.25); the value the plan expects is 34,577, **1.4 percent below** its true value (limit 10).
All 520 decisions bind at least one limit. **A finding about the margin:** the plan is within 0.1 percent of the best that could be done with these constraints, which says the calibrated probabilities lose almost nothing
here; it is a statement about this twin, one seed and a choice of uplifts that the planner is **given** (an assumed-known uplift is the limitation of this milestone: a wrong uplift is not tested).

**Added after seeing the run (not margins).** One more G9 check, "the plan differs from the oracle plan in at least one decision" (a planner that read the truth would equal it, and the 1.0 upper limit cannot tell).

**What this does not show:** an uplift that is estimated and not given; interactions between weeks (a patient contacted this week and next); one seed and one size; the real cost of a pharmacist's minute.

### U3b, mutants of the outreach decision (2026-11-14) **[measured; 6 of 6 killed, one by a gate other than the one aimed at]**

*Run on every 9th decision (58 of the 520: `PLAN_B_STRIDE=9`), because a full run takes about 50 minutes and the container that ran them was restarted several times and killed the full runs; the control with the same stride passes G6 and G9 (plan/oracle 0.9990, plan/baseline 2.78,
all 58 decisions bind a limit) and fails G5 on 4 plans that stopped at the node limit, as the full run does on 8.*

| mutant | killed by |
|---|---|
| the one-outreach row dropped from the model | G6: 1,648 events given two outreaches |
| the minutes row dropped | G6: minutes 378 against 150 |
| the delivery-slots row dropped | G6: 49 slots against 10 |
| a wrong uplift in the model text only | G6: the objective is not the formula's (32.88 against 61.73) |
| the planner reads the true probabilities | G9: the plan equals the oracle plan in every decision (the check added after the full run) |
| the planner uses the uncalibrated probability | **G6 (objective), not G9, which I aimed at** |

**The last one is a finding about G9.** With the raw probability from the boost instead of the calibrated one, the true value of the plan is 0.9995 of the oracle plan's (0.9990 with the calibrated one): calibration did not change the decisions, because isotonic calibration is monotone, the boost was already
calibrated, and a constrained decision uses the ranking. G9 cannot tell calibrated from uncalibrated here; what catches the mutant is G6, which recomputes each plan's objective from the calibrated file. That is stated, not hidden: the decision's value is insensitive to calibration at this size; the
calibration matters for the *expected* value (the planner's own estimate: 1.4 to 1.9 percent below the true value in both runs), not for the choice.

### U4, G10: how large a route-selection model `solve` takes (2026-11-13) **[measured; claims (a) and (b) FAIL]**

*Code: `scripts/route_pool_size.py`; margins G10 of section 7a, committed (`0315c0c`) before any routing model was built. Machine: 4 cores, nothing else running except the measurement itself (load average
0.23 at the start, about 1.0 during: one `solve` at a time); `solve` as built in cancho-solve at the pin of this repository; minimum of 3 runs; wall time of the process including `solve check`; HiGHS is scipy's `milp`
and is used here only for the optimum, not for a time.*

**Disclosures.** Two things were seen before the table below, and both are written here and in section 7a. (1) The margin said K = 4 trucks; with at most 3 stops a route that covers at most 12 deliveries, so D = 14 and 18 were
infeasible by arithmetic; one test run of D = 10 on one seed (`infeasible`, 0.04 s) showed it, and K was corrected to 8 before any timing. (2) With K = 8 my first constants (0.9 kWh/km, 4 kW of refrigeration) left most routes
fitting no battery, so 8 of 9 instances were `infeasible` (one instance, D = 14 seed 2, was solved: `optimal` in 7.83 s, 8,224 nodes, HiGHS gap 3.7e-9, which I saw); I lowered the constants (0.45 kWh/km, 2 kW),
which the margins do not mention, and ran the table below once. The instances differ from that first run, so that one timing says nothing about this table.

| D | routes (binaries) | seed 1 | seed 2 | seed 3 |
|---|---|---|---|---|
| 10 | 174-175 (1,392-1,400) | feasible, 200,000 nodes, 87.4 s | feasible, 200,000 nodes, 81.1 s | feasible, 200,000 nodes, 93.8 s |
| 14 | 460-468 (3,680-3,744) | feasible, 200,000 nodes, 165.3 s | feasible, 200,000 nodes, 176.7 s | feasible, 200,000 nodes, 173.8 s |
| 18 (node limit 20,000) | 976-981 (7,808-7,848) | optimal, 1 node, 0.10 s | optimal, 29 nodes, 0.52 s | optimal, 1 node, 0.10 s |

* **(a) FAILS:** D = 10 is not `optimal` on any seed; each stops at `solve`'s default node limit (200,000 nodes) after 81 to 94 s, against the bound of 5 s.
* **(b) FAILS:** D = 14 is not `optimal` on any seed either (165 to 177 s at the node limit), against the bound of 60 s.
* **(c) holds on what was compared:** the three `optimal` objectives (D = 18) equal HiGHS's to at most 3.8e-9 relative. Nothing was compared for the six `feasible` ones.

**What is learned.** The size is not monotone: the models at D = 18 are easy (the pool is large and the 8 trucks of 3 stops leave little slack, so the relaxation is nearly integral), and the ones in the middle are the hard ones. The
rule fixed in advance ("use the largest D for which every seed passes its bound; if (b) fails, D = 10") **has no answer**: (a) fails as well, and D = 18 had no bound claimed. That is a gap in the rule, not
a result, and it is not patched here. A likely cause is symmetry: the 8 trucks are 4 batteries twice, so every plan has equal twins; a model over 4 classes of 2 trucks instead of 8 trucks would remove it. That is a different model,
so it gets its own margins written before it is run (next). Reported to cancho-solve with the earlier model (issue 3, comment).

**What this does not show.** Random instances, not the twin; one pool rule and one set of constants; no time stated against any other solver.

### U4, G10b: the same selection with the trucks aggregated into classes (2026-11-14) **[measured; claims (a') and (b') FAIL]**

*Same code (`scripts/route_pool_size.py --classes`), instances, constants and machine as G10; the machine was idle apart from the one `solve` (load average 0.00 at the start, about 1.0 during), so the times are not
upper bounds on anything. The margins G10b of section 7a were committed (`9addfe9`) before the aggregated model was written or run.*

| D | seed 1 | seed 2 | seed 3 |
|---|---|---|---|
| 10 | optimal, 139,901 nodes, 27.1 s | optimal, 104,284 nodes, 21.6 s | optimal, 97,579 nodes, 19.1 s |
| 14 | feasible, 200,000 nodes, 92.2 s | feasible, 200,000 nodes, 77.5 s | feasible, 200,000 nodes, 90.9 s |
| 18 (node limit 20,000) | optimal, 1 node, 0.08 s | optimal, 13 nodes, 0.20 s | optimal, 1 node, 0.07 s |

* **(a') FAILS:** D = 10 is `optimal` on all three seeds, in 19 to 27 s, against the bound of 5 s.
* **(b') FAILS:** D = 14 is not `optimal` on any seed (the 200,000-node limit, 78 to 92 s), against the bound of 60 s.
* **(c') holds:** the six `optimal` objectives equal HiGHS's on the same model to at most 3.8e-9 relative.
* **(d) holds on what was printed:** the three D = 18 objectives (235.9249, 237.8226, 237.0281) are the ones of the 8-truck model to the four decimals printed (a difference below 2e-7 relative; I did not print more digits).

**What the rule says, and what the numbers say.** By the rule fixed in advance, a miss on (a') or (b') means the symmetry explanation is **not supported** at the bounds, and U4's decision keeps route selection and stop order out of
`solve`: the twin gives the routes as data and `solve` does the charging plan under the depot cap only. That is what U4 will do. The numbers carry a nuance that the rule did not ask for: aggregation turned the three unproved D = 10
runs into proved optima, and cut the time at D = 14 from 165 to 177 s to 78 to 92 s at the same node limit, so the twin trucks were part of the difficulty; the remainder is not explained, and no further model was tried.

**What this does not show.** Random instances, one pool rule, one set of constants, one machine; no time against any other solver; and that a model with another structure (a flow formulation, a column-generation loop in a program with
`solve` as the master) would not do better. Reported in cancho-solve issue 3 (comment).

### U4a: A's twin; G1 holds, G2 holds on two of three effects and FAILS on the temperature effect on excursions (2026-11-14)

*Code: `twinlib/delivery.py`, `features_a.py`, `scripts/pipeline_a.py`, the delivery checks of `scripts/check_twin.py`, and 22 new parameters in `world.json` (all `choice`). The margins G1 and G2 for A are those of section 7a, committed
(`fba93b0`) before the delivery tables were written. Same machine as before; the twin builds the large size's delivery tables (7,295 deliveries in 2,663 routes, 9,959 telemetry rows) in 0.5 s.*

**The twin.** Trucks (10 at the large size, 4 batteries drawn from 80, 100 and 120 kWh), pharmacies placed on a 20 km square with the depot at the corner, a daily outside temperature (a seasonal triangle plus noise), up to one delivery a day per pharmacy
(probability 0.5) with a two-hour window, routes of at most 3 stops in the order of their window ends, the biggest battery to the costliest route, and per-stop energy (driving + refrigeration raised per degree above 20 + doors) with a 4 percent noise. The
analysis side sees the energy, the minutes, the door minutes, the cabin temperature and the day's temperature; the parts and the excursion probability are written to `truth/`. Asking for the delivery tables moves no older table (checked byte for byte), and
the delivery parameters are a group that is all or none.

**G1 [measured, passes].** `scripts/check_twin.py`: determinism, another seed, the energy of a route equal to the sum of its stops' (exactly), each delivery in exactly one route, no truck twice on a day, every route within its truck's battery less the
reserve (0 violations), arrival no earlier than the window opens, the parts of every stop recomputed from the parameters, the true excursion probability of every stop recomputed, the realised excursions within 5 standard deviations of the sum of those probabilities, the
depot file equal to the world file, the extremes (delivery probability 0 and 1,000,000), three refusals with their rule tags. **33 of 33 mutants killed** (22 old and 11 new). Two survivors came up on the first run and were both faults of the harness, not of the twin: one mutant
could no longer be applied because I had changed the text it targets in `world.json`'s parser (updated), and `biggest-battery-last` survived because at these parameters every route fits every truck (the largest route needs 68.4 kWh, the smallest battery leaves 65 for it), so
the battery check could not fail. A second world with batteries of 70 and 120 kWh was added to the check (101 routes would exceed their truck under the mutant); the check also fails if no route needs the big battery.

**G2 [measured, once, on the large size].**

| effect | in the twin | in the control (the term set to zero) | margin | |
|---|---|---|---|---|
| refrigeration: energy per minute, hot (at or above 25) against cool (at or below 15) days | p = 5.6e-7; hot minus cool = 8.88 Wh per minute (153.92 against 145.04) | p = 0.210 | p < 1e-6 and positive; control p >= 1e-3 | holds, **by a factor of 1.8** |
| doors: excursion against the door-open band | p = 2.0e-21 | p = 0.952 | p < 1e-6; control p >= 1e-3 | holds |
| heat: excursion against the temperature band | **p = 0.18** | p = 0.148 | p < 1e-6; control p >= 1e-3 | **FAILS** (the effect was not found) |

**The failure, and what it is.** The twin does what it says: in the same run, the excursion rates by band are 0.0766 (cool), 0.0705 (mild) and 0.0865 (hot) observed, against 0.0722, 0.0764 and 0.0994 expected from the true probabilities, within 1.7 standard deviations each. The
temperature term adds only 2.5 points of probability on hot days (0.04 per 10 degrees, with a base of 7 percent from the doors), and a chi-square over 7,295 stops with 3 bands cannot see that: from the true probabilities the non-centrality is about 10.6, and p < 1e-6 on 2 degrees of freedom
needs a statistic of 27.6, so **the margin could not have been met even on typical data** (the expected statistic is about 12.6, a p of about 0.002). That is a mistake in the margin, made without a power calculation, not a property of the twin or of `stats`. It is reported as failed, **the
margin is not moved, and no stronger coefficient has been tried**. The refrigeration margin passing by a factor of 1.8 is also a thin pass of the same kind.

**Options, for the maintainer to choose (none taken):** (1) leave G2 for heat as failed and say that this effect is below what the size can show; (2) make the effect a stated, larger choice (for example 0.15 per 10 degrees, about 9 points on hot days) and write a new margin for it before running, saying that it was made after this failure; (3) more days or more
pharmacies (a size change), with a power calculation in the margin this time.

**Not run.** The mutants of `pipeline_a.py` (5 are written) were not run: they need a control whose G2 passes, and this one fails on the heat effect, so their "killed by a G2 line" would mean nothing. They run once G2 is settled.

### U4a, G2c: the heat effect at 0.15 per 10 degrees (2026-11-14) **[measured; holds]**

*The margin G2c of section 7a (and its power calculation: non-centrality 138 against 10.6) was committed (`75de184`) before the world file was changed or anything was run; the change was the maintainer's choice (option 2 above). `excursion_per_10c_ppm`
went from 40,000 to 150,000 in `world.json`; nothing else changed. One run of `scripts/pipeline_a.py` on the large size, the earlier G2 claims judged again in it.*

| effect | in the twin | in the control | |
|---|---|---|---|
| heat: excursion against the temperature band | **p = 9.3e-23** | p = 0.148 | holds (margin p < 1e-6; control p >= 1e-3) |
| doors: excursion against the door-open band | p = 2.4e-13 | p = 0.331 | holds (it was 2e-21 before: the larger heat term adds noise to the door comparison, 713 excursions instead of 557) |
| refrigeration: energy per minute, hot against cool days | p = 5.6e-7; hot minus cool 8.88 Wh per minute | p = 0.210 | holds, **still by a factor of 1.8 only** (this effect was not changed) |

G7 on the 20 recorded steps is clean and detects a changed byte; the twin has 713 excursions in 7,295 stops, 186 late stops and no route beyond its battery. G1 passes again on the changed world file (it recomputes every probability from it).

**Mutants of `pipeline_a.py`: 5 of 5 killed**, each by a G2 line: the twin ignoring the temperature in the refrigeration (p = 0.21, hot minus cool 2.2), ignoring the doors in the excursion (p = 0.33), ignoring the heat in the excursion (p = 0.148), a control that does not zero its term
(an effect found in it, p = 3.2e-7), and the temperature test pointed at the door band (killed by the control line: the door effect is in the temperature control, p = 3e-21; the main run passes it by testing the wrong column, which is why a control matters). Two of the five failed to run as written on the first try, both faults of the harness (the text of one
no longer matched the file after an edit; the replacement of another broke the syntax) and were corrected and rerun alone.

**What this does not show.** The 0.15 is a stated choice, 3.75 times the first one, chosen so that the test could see it; the excursion rate on hot days it implies (about 18 percent) is not read from any fleet. The refrigeration margin is still thin.

### U4b: A's models; route energy passes G4, the excursion model FAILS G4, G8 passes (2026-11-14) **[measured, once]**

*Code: `scripts/pipeline_a2.py`, `features_a2.py`, `pred_join_g.py`, `apply_isotonic_g.py`. The margins (and their sizing) were committed (`8ad8564`) before any model was built. The control is 22 recorded `flow` steps on the large size.*

| claim | measured | margin | |
|---|---|---|---|
| G4 energy: boost MAE against the distance-only baseline, 669 test routes | 1,094 Wh against 1,610 Wh: **0.680** | at most 0.80 | holds |
| G4 energy: boost MAE against the noise floor (a model that knew the parts) | 1,094 Wh against 638 Wh: 1.715 | at least 0.95 | holds |
| G4 excursion: calibrated log loss against the constant model's, 1,827 test stops | 0.35676 against 0.35808: **0.9963** | at most 0.985 | **FAILS** |
| G4 excursion: against the true probabilities' (0.33958) | 1.0506 | at least 0.97 | holds |
| G8: five groups of the calibrated probability, 365 rows each | predicted/observed 0.053/0.079, 0.059/0.077, 0.088/0.148, 0.106/0.121, 0.126/0.150; largest deviation 0.81 of its bound | within the bound | holds |
| split hygiene, G7 | no shared row, every fit day before every test day; 22 steps check clean, a changed byte is detected | | holds |

**The failure.** The calibrated boost is barely better than the constant model on the test stops (0.9963), and the uncalibrated one is worse (0.36408, 1.0168 of the constant's): a boost fitted on 3,650 stops with about 365 excursions overfits, and isotonic calibration on 1,820 more stops brings it back to about the constant. The
calibrated probabilities are also too low in every group (predicted 0.053 to 0.126, observed 0.077 to 0.150): G8 passes only because its bound at 365 rows per group is wide (0.8 of it used). A margin that could not be met by the true probabilities' own sampling was avoided (a perfect model would have been at 0.944); this one was missed by the model.

**Exploratory, not a claim, and seen on the test stops (so it is not a clean selection):** the uncalibrated log loss against the constant model's on the same test stops, for the same fit stops: boost with the four features 1.0167; boost with the door minutes and the temperature only 0.9839; **logistic with the four features 0.9619; logistic with the door minutes and the temperature only 0.9609.** The family matters at this
size, and a linear-logistic model, which is nearly the form of the twin's probability, clears the margin that the boost misses. Nothing was changed because of it.

**Not run.** The mutants of `pipeline_a2.py` (6 are written): they need a control that passes G4.

**Options for the maintainer (none taken):** (1) leave the excursion model as a failed claim: a boost does not learn it from one year of stops; (2) switch the excursion model to logistic and write a new margin first (the unchanged 0.985 and 0.97 would do, and the model would be chosen from the *calibration* days, not the test days, but I have already seen the test numbers above and the
margin would say so); (3) more stops (more days or pharmacies) for the boost, with a sizing in the margin.

### U4b, G4b: the excursion model as logistic (2026-11-14) **[measured, once; holds]**

*The margin G4b of section 7a was committed (`52c87ea`) before the logistic model was run through the pipeline; the family was chosen after the exploratory comparison above, on the test stops, and the document says so there and in G4b. One run of `scripts/pipeline_a2.py`, 22 recorded steps.*

| claim | measured | margin | |
|---|---|---|---|
| G4 excursion: calibrated log loss against the constant model's (1,827 test stops) | 0.34545 against 0.35808: **0.9647** (uncalibrated 0.34445) | at most 0.985 | holds |
| G4 excursion: against the true probabilities' (0.33958) | 1.0173 | at least 0.97 | holds |
| G8: five groups, 365 rows each | predicted/observed 0.057/0.052, 0.067/0.071, 0.089/0.112, 0.107/0.151, 0.187/0.189; largest deviation **0.54** of its bound (0.48 uncalibrated) | within the bound | holds |
| G4 energy (unchanged, not refitted) | 0.680 of the baseline, 1.715 of the floor | 0.80 and 0.95 | holds |
| split hygiene, G7 | no shared row; 22 steps check clean, a changed byte is detected | | holds |

The third and fourth groups are still under-predicted (0.089 against 0.112, 0.107 against 0.151); the bound at 365 rows allows it, and it is not a claim that the probabilities are calibrated beyond that bound.

**Mutants of `pipeline_a2.py`: 4 killed, 2 not, both explained.**

| mutant | result |
|---|---|
| a later day in the energy fit (fit to day 727) | killed by the split-hygiene check of G4 |
| a later day in the excursion fit (2,993 shared rows) | killed by the split-hygiene check |
| the distance dropped from the energy model | killed by G4 (MAE 7,353 Wh against a baseline of 1,610) |
| the calibration inverted (`--decreasing`) | killed by G4 (log loss 0.43277 against 0.35808) |
| the cabin temperature, which defines the excursion, leaked in as a feature | **stopped by `ml`, not by a gate:** the logistic fit is refused with `ml.fit.separable` (exit 8, "a hyperplane separates the classes"), so no G4 line is printed and the harness counts it as not killed by the gate aimed at. The refusal's own repair suggests `--l2 10`, which would take the leak past the tool; the floor check of G4 (a model below 0.97 of the true probabilities' log loss has seen something it should not) would be the gate then, and that run was not made |
| the door information dropped from the excursion model (`door_min` and `minutes` both: the first version of this mutant dropped `door_min` alone and survived because `minutes` carries the door time through the service time) | **survived G4, and it should be said plainly:** the model on the temperature and the position alone has a calibrated log loss of 0.9676 of the constant model's (0.9647 with all four), inside the margin of 0.985. G4 does not test that the door minutes are used; that the doors matter is G2's claim (p = 2.4e-13), not this gate's |

Two further faults of the harness were corrected on the way: the first version of the leak mutant changed nothing (its old and new text were the same) and the harness now takes a list of edits for a two-edit mutant.

### U4c: the charging plan in `solve` and the `opt` calibration (2026-11-14) **[measured, once; every claim holds]**

*Code: `build_charging.py` (the model, from `charging.json`), `scripts/oracle_highs_c.py`, `scripts/oracle_lstsq_a.py`, `features_a3.py`, `objective_a.py`, `scripts/pipeline_a3.py`. The margins and their sizing were committed (`ea68bd4`) before the charging model or the calibration was built. The control run is 758 recorded `flow`
steps on the large size; `solve` and HiGHS as before, scipy for the two oracles.*

**G5 [holds].** `solve` returned an `optimal` and `verified` plan on all 182 nights (each of 2 to 5 trucks and about 20 hourly slots); HiGHS, given the data and not the model text, agrees on all 182 (worst relative gap **1.1e-11**); on a toy night of two trucks and four slots
(every pattern of plugged slots tried, the best charge for a pattern found by filling the cheapest slots, written apart from the builder) the enumeration and `solve` both give 2.900000. None of the 182 stopped at a limit: this model is small, unlike the outreach decision of U3b.

**G6 [holds].** Recomputed from the raw files: no truck charged less than its need, none beyond 11 kW in an hour or before it arrived, no hour with more than 4 trucks or over the depot's connection, every plan's cost the formula's, and no truck charged more than its need (the optimum charges exactly what is needed). Two tampers were refused by `solve verify`: a truck given no
charge (`solve.row-violated`) and a draw of 12 kW (`solve.bound-violated`). **A third tamper, a truck plugged before it arrived, was written and not made:** on the first night all its trucks arrived within the first hour of the window, so there was no unavailable slot to plug into; the gate skips it by construction there and says nothing about it.

**G11 [holds], judged on the energy the routes actually used (669 route-nights):**

| claim | measured | margin |
|---|---|---|
| route-nights charged less than was used, plan from the boost's prediction plus 3.0 kWh | 13 of 669: **0.0194** | at most 0.05 (sizing 0.014) |
| the same share from the distance-only baseline's prediction plus 3.0 kWh | 61 of 669: **0.0912**, 4.7 times the boost plan's | at least 2 times (sizing about 5) |
| cost of the optimal plan against the plug-in-and-charge-now plan on the same needs | **0.4571** (no night where that plan could not deliver) | at most 0.60 (sizing 0.451 to 0.458) |

**G12 [holds].** `opt minimize` (Nelder-Mead, 413 evaluations, converged) from the first guess 350, 1,200, 150,000 and 1,500, on the 9,958 legs: the sum of squares it reaches is **1,860.882, the exact least-squares minimum to the printed digits** (ratio 1.00000; limit 1.001). Coefficients against the twin's: driving 449.76 against 450 (0.05 percent
off; limit 2), refrigeration 1,813 W against 1,800 (0.74; limit 3), heat fraction 292,520 ppm against 300,000 (2.49; limit 10), doors 2,940 W against 3,000 (1.99; limit 15). In the control with the heat fraction zero, the calibrated heat fraction is **-5,509 ppm** (limit 25,000). Against the standard errors of the sizing (0.08, 0.3, about 1.85 and 3.6 percent) the errors are 0.65, 2.5, 1.35 and 0.55 standard errors: the refrigeration power is the one that sits furthest out, at 2.5, which a single draw can do and which the margin of 3 percent (10 standard errors) allows; `opt` reaches the same coefficients as the exact least squares, so the distance from the twin's values is the data's, not the optimiser's. **[corrected 2026-11-14: this sentence first said 0.7 to 0.5, which I wrote before computing the ratios]**

**Mutants of `pipeline_a3.py`: 9 of 9 killed.**

| mutant | killed by |
|---|---|
| the need row dropped from the model | G6: nothing charged (needs 59.5 kWh, charged 0.0) |
| the tariff hour off by one | G6: every plan's cost differs from the formula's (21.15 against 17.19 on the first night) |
| the safety of 3.0 kWh set to zero | G11: 0.4649 of the route-nights short |
| the need taken from the baseline's prediction | G11: 0.0912 short, no better than the baseline |
| the need wrong by 1 kWh in the model text only | G5: HiGHS (on the data) differs from `solve` (on the text), gap 0.041 |
| the chargers row dropped | G6: 72 hours with 5 trucks charging on 4 chargers: the charger limit does bind |
| the door term dropped from the objective of the calibration | G12: sum of squares 1,996 against 1,861 |
| `opt` stopped at 40 evaluations | G12: 3,951 against 1,861 |
| the control not zeroed | G12: the control's heat fraction is 299,904 ppm |

Two faults of the harness came up on the first run and were corrected: a mutant of the need row made a plan that charges nothing, which crashed the gate's own tamper step (`StopIteration`, no G6 line was printed; the step now falls back to slot 0), and the text of one mutant did not match the file. **No mutant of the grid-connection row was written:** it cannot bind in this twin (4 chargers of 11 kW is 44 kW, the lowest connection is 60 kW), so such a mutant would be equivalent, and the gate recomputes
the connection anyway.

**Notes on the tools.** `opt` starts its objective by path, not by searching `PATH` (`python3 script.py` after `--` is `opt.objective-failed`, "could not be started"); the objective is an executable script with an `env python3` shebang, started as `./objective_a.py`, which keeps every absolute path out of the `flow` records. The least-squares oracle is exact because the model is linear in the coefficients after a change of
variables, so `opt` is held against a closed form here.

**What this does not show.** One seed and one size, the nights of the last 182 days; the needs are the predicted energy plus a safety, with no battery-state model and no look at the next day's route; an uplift or a tariff that are choices; the safety of 3.0 kWh was fixed from the residual sizing of the energy model, and a different value changes the shortfall share; and the cost comparison is with one simple alternative.

### U4d: the coupling from a late or a warm delivery to the pharmacy (2026-11-14) **[measured, once; G1 and G3d hold]**

*Code: the table `coupled` of `twinlib/core.py` and `twinlib/delivery.py`, the coupled checks of `scripts/check_twin.py`, `features_ad.py`, `scripts/pipeline_ad.py`. The margins (G1 for the coupled tables, G3d) were committed (`7a9a32d`) **together with** the twin mechanism they judge, not before it: the mechanism was written, sized on seed 7, and the margins then written from that sizing, before any
check of the coupled tables or the pipeline existed. That is stated in the margin. The gate seed is 20261112. The control run is 10 recorded `flow` steps on the large size.*

**G1 for the coupled tables [holds].** Two runs give the same bytes; `truth/coupling.csv` equals the late and warm pharmacy-weeks recomputed from the delivery files; the stock ledger holds under the arrival rule recomputed from them (a late week receives nothing and holds what was due; the next week receives that and what it ordered; a warm week writes off the cold-chain arrival the same week; the chain of every item as before);
with no delivery at all the coupled dispensing file is byte for byte the uncoupled one; the coupled table without `dispensing` and `delivery` is refused with `twin.bad-tables`; no older table moves when `coupled` is not asked for. **7 new mutants, 7 killed** (the late rule off, the warm rule off, the discard applied to every item, the held order lost, `>=` instead of `>` for late, the warm flag in the wrong week, the two columns of the coupling file swapped), 40 mutants defined in all.

**G3d [holds].**

| claim | in the twin | control (the same delivery data, no effect) | margin | |
|---|---|---|---|---|
| stockout proportion, late weeks (34,800 pharmacy-item-weeks) minus others (381,200) | **+0.1595** (0.1883 against 0.0288), p below the smallest double | **-0.0015** (0.0124 against 0.0139), p = 0.021 | at least 0.05 with p < 1e-6; control within 0.01 of zero and p >= 1e-3 | holds |
| write-off proportion among cold-chain items that received stock, warm weeks (5,045) minus others (12,493) | **+0.9998** (1.0000 against 0.0002), p below the smallest double | shares 0.0000 and 0.0001; `stats` gives p = 0.520 | at least 0.5 with p < 1e-6; control shares at most 0.01 | holds |

The sizing on seed 7 had given +0.141 and -0.001 for the stockout; the gate seed gives a larger +0.1595 (174 late pharmacy-weeks against 186, other data). G7: the 10 steps check clean and a changed byte is detected.

**Mutants of `pipeline_ad.py`: 4 killed by a G3d line, 1 stopped by the tool.** The twin ignoring late weeks (difference +0.0014) and ignoring warm weeks (-0.0002), the control made coupled (+0.1595 in it), and the late flag taken from the wrong column (+0.0324, under the bound) are killed by G3d. `warm-test-grouped-by-late` is **stopped by `stats.group-levels`**: in the coupled twin every cold-chain arrival is in a week that is not late
(a late week receives nothing), so `late` has one level there and `stats` refuses; no G3d line is printed, and this is reported as stopped by the tool, not as killed by the gate.

**What this does not show.** The mechanism is a stated choice and deterministic (a warm week discards every cold-chain arrival, a late week holds the order a week): warm weeks are **31 percent** of pharmacy-weeks on seed 7 and about 29 percent of the cold-chain arrivals at the gate seed (5,045 of 17,538), a harsh and unrealistic coupling, and the 0.9998 is the mechanism, not a finding. The effect on stockouts is the mechanism's too, plus a bullwhip (a held order and the next order arrive together). No look at B's lapses through the new stockouts has been made here; that is the
closed loop, U5. One seed and size, one machine.

### U5: the loop, a week of the whole chain in one command (2026-11-14) **[measured; G13 to G17 hold]**

*Code: `scripts/loop.py` and `loop_summary.py`. The design and the margins (G13 to G17) were committed (`be7f67e`) before the loop was written. The command is `CANCHO=<compiler> SCIPY_PYTHON=<a python with scipy> python3 scripts/loop.py`; it runs the whole chain twice at once in fresh directories and judges the first run. Same machine as before (4 cores). The first full run passed; nothing was tuned.*

**What one run is.** 218 recorded `flow` steps: the large, coupled twin (week 100, days 700 to 706); C: the lag features, a boost fitted on weeks 48 to 99, the forecast of week 100 and 20 replenishment decisions in `solve`; B: the refill events, a boost fitted before week 74, isotonic calibration on weeks 74 to 99, the 1,843 events due in week 100 and 20 outreach decisions in `solve`; A: a boost for
route energy fitted before day 700, and the charging plan of each of the 7 nights of days 700 to 706 in `solve` (23 truck-nights); then four summaries and their merge. **Two independent runs took 141 seconds in all** (both running at once on 4 cores); that is a wall-clock figure of this machine under that load, not the measured run of U6.

**G13 [holds].** Two independent runs give a byte-identical `summary.json` (sha256 starting `a701f5de6ac65856`) and byte-identical records (the 218 files of `rec/`, by name and content); an earlier single run of the same command gave the same digest, so three runs agree.

**G14 [holds].** Every plan is `verified` by `solve verify` with its objective checked, none stopped at the node limit, and HiGHS (from the data, not the model text) agrees on all of them: replenishment 20 plans (worst relative gap 4.1e-8), outreach 20 (7.1e-11), charging 7 (4.2e-12).

**G15 [holds].** The summary equals a recomputation from the raw plan and data files, on all four parts (replenishment, outreach, charging, coupling). For the record, the week's numbers: 14,310 units ordered over 20 pharmacies; the 1,843 events get 542 reminders, 843 switches to 90-day supply and 200 home deliveries and **no pharmacist call** (the minutes are better spent on the others under these costs), with an expected gain of
1,417.7 adherent days; 7 nights charge 862.4 kWh for a cost of 94.86. These are outputs of the stages, not claims about their quality (that is what the earlier gates judge).

**G16 [holds].** 20, 20 and 7 decisions; the weeks of the decisions are week 100 (C, B) and days 700 to 706 (A); no fit file reaches the week (C's fit ends at week 99, B's at 99, A's at day 699). **The coupling is visible in the week:** the late pharmacy of week 100 is P019 and the warm ones are P013, P016 and P020 (from the delivery files); the pharmacies with a late or warm
delivery have 65 stockout items in week 100 and 137 in week 101, the other 16 pharmacies 113 and 217. No statistical claim is made on one week and four pharmacies.

**G17 [holds].** `flow-records check` is clean on the 218 steps and detects a changed byte of `c_test.csv`. **Mutants: 5 of 5 killed:** the fit of C including week 100 (G16: "C's fit reaches week 100"), B deciding on weeks 100 to 103 (G16), the summary's ordered units off by one (G15), a stage missing from the summary (G15), a clock in the summary (G13: the two runs differ).
Two faults of the harness came up on the first run of the mutants and were corrected: the outreach mutant crashed the gate's own recomputation (`KeyError`, it counted the events of later weeks) before G16 printed anything, and the clock mutant's run stopped because a `flow` step hit its deadline when six processes shared 4 cores; each was rerun alone.

**What this does not show.** The loop is closed in the data and **open in the decisions**: the plans do not change the twin's world (the twin is generated whole beforehand), so a replenishment order that is better than the pharmacy's own does not reduce next week's stockouts here. One week, one seed, one machine; reproducible bytes on this machine are not reproducible bytes on another platform (U6); and nothing about the loop's numbers is a claim of quality.

### U6: the measured run (2026-11-14) **[measured on one machine; M1 to M4 as fixed]**

*Code: `scripts/loop_measure.py`; the timing is taken outside the records (`Flow.ms`, wall time around each `flow step`, which includes flow's own hashing of the declared files). The margins M1 to M4 (and the list of what may not be claimed) were committed (`251c321`) before the script existed. One run of the script, the machine idle: the Linux x86-64 virtual machine of this work, **Intel Xeon Processor @ 2.10 GHz, 4 cores, kernel 6.18.44, a cloud VM so the host is shared and not controlled**;
`ml --threads` at its default of 1; the load average at the start of the five runs was 0.00, 0.28, 0.28, 0.29 and 0.29 (the script waits for it to fall under 0.3; one run starts at 0.00 and the rest at the limit, so they are not at zero).*

| run | load at start | steps (wall) | summary sha256 (prefix) |
|---|---|---|---|
| 1 | 0.00 | 85.9 s | a701f5de6ac65856 |
| 2 | 0.28 | 83.0 s | a701f5de6ac65856 |
| 3 | 0.28 | 85.5 s | a701f5de6ac65856 |
| 4 | 0.29 | 81.3 s | a701f5de6ac65856 |
| 5 | 0.29 | 80.5 s | a701f5de6ac65856 |
| 6, `--threads 4` on every `ml fit` | 0.29 | 79.2 s | a701f5de6ac65856 |

* **M1 [holds as a figure, not noisy]:** the 218 steps of one loop take **80.5 s at the minimum of five runs** (median 83.0 s, maximum 85.9 s; maximum over minimum 1.07, under the 1.25 at which the figure would have been called noisy). The whole process takes 137 to 146 s because it also judges (HiGHS, the recomputations); the judging is not part of the figure.
* **M2 [holds]:** the five digests are equal and equal to U5's `a701f5de6ac65856`: the loop has not drifted since U5 (five more runs, all equal to it).
* **M3 [holds]:** with `--threads 4` on every `ml fit` the summary is byte for byte the same as at 1 thread, here through the whole chain; the documented claim of `ml` held on this loop. The run's 79.2 s is **not a speed claim**: it is one run, 1.3 s under the minimum of five, inside the noise.
* **M4 [stated for this machine only], the fastest run, 80.5 s:** by stage, the twin 16.1 s, C 38.1 s, B 20.8 s, A 4.5 s, the summary 1.0 s; by program, **`python3` 63.1 s (79 percent), `ml` 11.0 s (14 percent), `solve` 4.8 s (6 percent), `table` 1.5 s (2 percent)** of the sum of the steps.

**What the shares say, and do not.** Four fifths of the loop's time is the example's own Python programs (the twin 16 s, the feature builders, the 47 model builders and the verification joins, each a process that starts a Python interpreter), not the tools under test: the fits are 14 percent and all 47 `solve` runs together 6 percent (4.8 s). That is a statement about this loop's composition on this machine; it is not a statement about the speed of `ml`,
`solve` or Python, and no other tool or library was measured here. The 38 s of stage C is mostly the 20 replenishment decisions' four processes each plus the forecast's features.

**Not claimed, as fixed in advance:** any speed against another tool or library; any scaling beyond this size and week; any statement about another machine, another operating system or another number of cores (**macOS and aarch64 were not run**: the digest on those platforms is unknown, and equality there needs a machine or a CI job that this repository does not have); that the loop's numbers are good (U2 to U4 judged the stages); and that two machines would give 80.5 s.

### U7a: the stepping twin (2026-11-14) **[measured; G18 to G20 hold]**

*Code: `twinlib/step.py`, `twinlib/decisions.py`, `twin.py --engine step --decisions DIR --through W`, the classes `core.StockSim` and `delivery.DeliveryWorld` (the batch twin is now a loop over them), `scripts/check_step.py`. The margins (and the design) were committed (`4368b4f`) before the twin was changed; three of their sentences are corrected in place above, where the building showed them imprecise.*

**The one design problem, and its answer.** The batch twin draws a patient's refill series from one stream, item after item, so an outreach that changes one item's outcome would move every draw of that patient's next item: the world would not be causal week by week. The stepped twin runs the batch refill series once without decisions and keeps, for every refill event, the uniform number it drew
(read back from a logging stream); an event beyond what the batch twin had (an outreach kept a patient on) takes its number from a stream of its own. With no decisions it is the batch twin; with decisions each effect starts in its week and nothing before it moves.

**Refactor safety.** Before any new code, the batch twin's output was recorded in nine configurations (seeds 20261112 and 1, sizes small and large, every table group). After each refactor (the stock simulation and the delivery simulation as classes; the new world parameter `outreach_uplift_ppm`) all nine were compared again: **byte for byte identical each time**, so no earlier result moved. `check_twin.py` passes and its 40 mutants are all killed
(two no longer applied because the text they target changed, and were updated).

**G18 [holds].** The stepped twin writes every file of the batch twin byte for byte in all nine configurations (two seeds, two sizes, and the groups `core`; `core,dispensing`; `core,dispensing,refills`; `core,delivery`; `core,dispensing,delivery,coupled`; the full set), `truth/` and `truth.json` included.

**G19 [holds].** 17 bad decision files (an unknown pharmacy, item, patient, truck or action; a negative or a fractional number; an order that is not a whole pack or is above the pharmacy's space; a duplicate; a week that does not match the file or is out of range; a day outside the week of the charge; an event that is not due; a file above 1,048,576 bytes; not JSON; a file with another name) and orders with no dispensing table are each refused with their rule tag
(`twin.decision-*`), exit 2, nothing written. **A fuzz of 300 found a crash on its first draw**: a list given as a patient id made the membership test raise `TypeError`. The loader now checks that those members are strings (`twin.decision-type`) and the fuzz passes. The fuzz generator itself had two faults of its own (it indexed into a document it had already replaced, and it shared objects between draws so a document could refer to itself); both were fixed.
*The effects, on the small world (measured):* **zero orders at week 50** change 112 of the 480 rows of week 50 (their `ordered` column only) and 2,228 of the 25,440 rows after it (the stockout cells after week 50 go from 848 to 902), and no row before week 50; the demand file is unchanged. **A call on each of the 4,390 refill events of weeks 21 to 51** (decisions at the ends of weeks 20 to 50) lowers the lapses over the horizon from 778 to 754
(the events go from 12,885 to 13,328, because patients who did not lapse stay on) and changes no row due before week 21; the demand file is unchanged. **A charge of zero kWh for every truck on days 147 to 153** leaves 25 stops short, the late pharmacy-weeks go from 45 to 52 and the stockout cells from week 21 on from 1,240 to 1,274; the routes and the demand are unchanged. These are the effects of the decisions as named, small as the world makes them at this size; nothing here says that a tool's plan is better than the pharmacy's own: that is U7c.

**G20 [holds].** The same decisions give the same bytes in two runs, and reversing the order of the entries of a file changes nothing.

**Mutants of the stepping: 13 of 13 killed.** By G18 (7): the refill uniform's index not advanced, the numbers misaligned by one, the refills written in another order, the batch numbers ignored, a week of six days, the coupling not passed to the stock, the stockout window off by one. By G19 (5): orders applied a week late, orders ignored, outreach without effect, charges ignored, the outreach read from the wrong week's file. By G20 (1): an entry's order changing the result. The first version of the G20 mutant did nothing (its added term was nonzero only for a duplicate, which is refused first) and survived; it was rewritten and killed.

**What this does not show.** The stepped twin is built and equal to the batch twin; decisions have their named effects. The planners do not yet decide inside it (U7b), and no plan has been compared with the pharmacy's own policy (U7c). The whole check takes about 9 minutes (the equality in nine configurations and 300 fuzzed runs). Replaying from week 0 to the week asked is how a loop would use it (`--through`); there is no saved state.

### U7b and U7c: the loop with decisions, and the experiment (2026-11-15) **[measured; G21 to G23 and claims (1) to (4) hold; 7 of 7 mutants of the loop killed]**

*Code: `scripts/closed_loop.py` (one arm), `features_next.py`, `events_next.py`, `plan_decisions.py`, `scripts/experiment.py` (the four arms, the judge); the output of the judge is kept in `docs/experiment-u7c.log`. The margins (G21 to G23, claims (1) to (5)) were committed before any of this was written (`b139834`).* Seeds 20261112 and 1, size large, decisions at the ends of weeks 90 to 101, outcomes over weeks 91 to 103, arms D (the batch twin), C, B and T; arm T of seed 20261112 ran twice. 4-core machine, nine processes at once, **about 28 minutes** from start to the last line of the judge.

**G21 [holds].** In all seven arm runs every plan is `verified` by `solve verify`: 240 plans for C and for B (20 pharmacies times 12 weeks), 480 for T; HiGHS (`oracle_highs.py`, `oracle_highs_b.py`) reported no disagreement with `solve`; each `week-<W>.json` equals what the plans of its week say (recomputed from the plan files and the model data by the judge); the models' fit files hold no week after 89 and each model on disk is the file its fit printed (sha256), so none was refitted. **Plans that stopped at the node limit (still verified, a feasible plan and a bound, not a proof of optimum): B 4 and 3, T 15 and 5 of 480** (seed 1 and 20261112; C none). The loop's own guard stops a run if the twin's files hold a stock row or a refill due after the decision week (this guard covers the stock and the refills; the other tables are not read by C or B). The twin accepted every decisions file.

**G22 [first run FAILED the clause on records; fixed in the harness and re-run; holds].** In the first full run `flow-records check --recursive` was **not clean at the end of any of the seven arms**. The tool was right: the loop rewrites `data/` and the plans' inputs (`c_next.csv`, `c_pred.json`, ...) every week, so an earlier week's record names files that are no longer what they were. The margin was not moved: the loop now checks the records of each stage **in its own week** (`check_records`, a separate record directory per week) and stops at the first that is not clean. In the second full run **every record of every arm was clean when checked (1,025 for C, 1,053 for B, 2,052 for T, as many as steps)**, the last step's records are clean at the end, and a changed byte of `dispensing.csv` is detected (exit 5) in every arm. A record can only vouch for the files as they were in its week: a loop that overwrites its files cannot be re-verified from the end state, which is a property of the records that the margin did not foresee. **Determinism:** the two runs of arm T (seed 20261112) have equal final tables, equal decisions and equal records (tree digests). The second full run's outcome numbers equal the first's in every line (the diff of the `seed` and `CLAIM` lines is empty), which is a second determinism check across a restart of the machine.

**G23 [holds, as checked].** Arm B's `dispensing.csv` and `truth/demand.csv` are D's byte for byte on both seeds; the demand of C and T is D's; no arm's `dispensing.csv` row differs from D's before week 90, and no refill due up to week 90 differs; the decisions files have the right parts (orders in C and T, outreach in B and T). *What was not checked as written:* "every table" before week 91 was checked for `dispensing.csv` and `refills.csv` only (the tables the tools read), with the boundary at week 90, the first decision week, not 91; the entries per week were not counted against 20 pharmacies, but the plan counts above (240) and 4,000 order entries per week (20 pharmacies times 200 items) were seen.

**Outcomes** (units, cells and lapses; orders over the weeks decided, 90 to 101; stockouts, units short, write-offs over weeks 91 to 103; lapses over the events due in weeks 91 to 103):

| seed | arm | units ordered | stockout cells | units short | written off | events | lapses |
|---|---|---:|---:|---:|---:|---:|---:|
| 20261112 | D | 306,630 | 2,763 | 19,488 | 13,723 | 24,909 | 1,500 |
| 20261112 | C | 204,500 | 11,369 | 93,639 | 4,563 | 24,546 | 2,049 |
| 20261112 | B | 306,630 | 2,763 | 19,488 | 13,723 | 25,147 | 1,180 |
| 20261112 | T | 204,500 | 11,369 | 93,639 | 4,563 | 24,873 | 1,634 |
| 1 | D | 327,850 | 2,226 | 15,519 | 12,340 | 26,311 | 1,380 |
| 1 | C | 197,840 | 12,836 | 115,901 | 4,120 | 25,708 | 2,142 |
| 1 | B | 327,850 | 2,226 | 15,519 | 12,340 | 26,543 | 1,135 |
| 1 | T | 197,840 | 12,836 | 115,901 | 4,120 | 26,024 | 1,740 |

**The claims.** **(1) [holds]** C orders 0.667 and 0.603 of D's units (the margin was 0.95; the sizing from week 100 had said 0.50, so the direction holds and the size is smaller than sized). *Reading, disclosed:* the judge sums the `ordered` of the weeks decided, 90 to 101, where the claim says weeks 91 to 103; over weeks 91 to 103 the ratios are **0.725 and 0.673**, which also meet the margin (computed afterwards from the kept files, not by the gate). **(2) [holds]** C has 4.1 and 5.8 times D's stockout cells (margin 1.5). **(3) [holds]** C has 1.37 and 1.55 times D's lapses (margin 1.05); the claim was marked as one that may well fail, and it did not. **(4) [holds]** B has 0.787 and 0.822 of D's lapses (margin at most 0.90; sized 0.77 expected; the lapses avoided are 320 of 1,500 and 245 of 1,380). **(5), reported, not claimed:** T has **more lapses than D, by 8.9 percent and 26.1 percent** (1,634 against 1,500; 1,740 against 1,380), and 4.1 and 5.8 times its stockout cells: the loss of the replenishment plan is larger than the gain of the outreach plan, on both seeds.

**What this shows and does not show.** In the world of the twin, with the plans as built (stylised costs, a replenishment plan that accepts shortage and does not see the lapses a stockout causes), the loop closes: decisions enter the world, have the effects U7a named, and the outcomes differ as the claims said. The replenishment plan **orders a third to two fifths less than the pharmacies' rule and pays for it in stockouts and, through the coupling, in lapses**; the outreach plan avoids 18 to 21 percent of D's lapses. The two plans are not combined well: T is worse than the twin's own policy on lapses. That is a finding about these plans and these costs, not about replenishment or outreach in general; the lapse term is not in the replenishment objective; putting it there was tried in U8 and was not the cause (the room constraints cap the plan, see U8). The numbers are those of two seeds of one synthetic world; the effect sizes are not estimates of anything real, and no claim is made that the tools beat the pharmacy's policy. The charging decisions (A) were not exercised in the loop, as stated in section 7a.

**Mutants of the loop: 7 of 7 killed** (`scripts/mutants_loop.py`, the seven of section 7a). Each is a one-line change to a copy of the example, run as a short arm (decisions at the ends of weeks 90 and 91, outcomes through week 93, seed 20261112) and judged by G21 to G23 without the claims, which need the whole horizon; D's tables are those of the experiment. *The first run of the mutants was void and is not counted:* its controls (the unmutated arms C and B) were reported not clean, because the judge compared a run that ends at week 93 with D's 104 weeks; the judge now compares the weeks the arm covers (the full experiment's verdicts and numbers are unchanged by that), and the controls are clean. In the second run both controls are clean and:

| mutant | killed by |
|---|---|
| the decisions of a week written under the next week's number | the twin: `twin.decision-week`, the run stops |
| P001's orders written under P002 and the reverse | G21: two weeks of decisions differ from their plans (the twin accepted the files) |
| a model fitted with week 90 in its data | G21: `c_train.csv` holds a week after 89 |
| the names of the actions `call` and `reminder` swapped | G21: two weeks of decisions differ from their plans |
| orders not multiplied by the pack size | the twin: `twin.decision-pack`, the run stops |
| the outreach part left out of the merge (arm B would equal D) | G21 (decisions differ from plans) and G23 (the decisions file has the wrong parts) |
| a clock in a decisions file | the twin: `twin.decision-week` (a member the file may not have), the run stops |

*What the last row does not show:* G22's own clause about a clock (equal bytes in two runs) is not what killed it; the twin refuses the foreign member first, so that clause has not been shown able to fail by this mutant (the second run of arm T being equal is the evidence for it, not a killed mutant). Three of the seven are killed by the twin's own refusals rather than by the loop's gates; the other four are killed by the judge. The reasons for the three stopped runs were read afterwards by running the twin on the mutant's `week-90.json`, since the `flow` record keeps only the hash of a program's standard error.


### U8: the lapse cost in the replenishment objective (2026-11-15) **[measured; G24 to G26 hold; claims L1, L2 and L3 all FAIL]**

*Code: `build_models.py --lapse lapse.json`, `lapse.json`, the arms CL and TL of `closed_loop.py`, `scripts/check_lapse.py` (G24, G25 and the builder's mutants), `scripts/experiment_lapse.py`. The design, the margins and the sizing were committed first (`111309f`); L = 100 was fixed there and run once. The judge's output is kept in `docs/experiment-u8.log`.* Seeds 20261112 and 1, the same weeks as U7c; D, C and T are U7c's (that run was repeated byte for byte).

**G24 [holds], G25 [holds], G26 [holds].** The lapse term (events a week, lapse cost per unit short, quantile, target) was recomputed by the judge's own code for every plan of CL and TL (240 replenishment plans in each of the four runs) and agrees to 1e-9; an item with no event keeps the old target exactly; with a lapse cost of 0 the builder writes the old plan byte for byte (`.sol` equal, `.json` equal less its `lapse` member); the cap of 3.5 is exercised with a huge cost on a fixture. G21 to G23 as in U7c: every plan verified (480 plans in TL, 9 and 6 of them stopped at the node limit in the outreach half; none in CL), the decisions equal their plans, the models were fitted once, every record of every step is clean in its week (1,025 for CL and 2,052 for TL) and a changed byte is detected, the demand and the weeks before 90 equal D's. **Mutants: 8 of 8 killed.** The builder's seven by G24 or G25 (the sign of the shift flipped, the window taken as one week, the events counted through the week itself, the events divided by 4, the cost not divided by the forecast, an absolute quantile instead of an increment on 1.28, the cap removed; `check_lapse.py --mutants`); the loop's, the lapse flag dropped from arm CL, by G24/G26 (40 of 40 plans of the short run have no `lapse` member; its controls, the unmutated arms C, B and CL, are clean).

| seed | arm | units ordered | stockout cells | units short | written off | events | lapses |
|---|---|---:|---:|---:|---:|---:|---:|
| 20261112 | D | 306,630 | 2,763 | 19,488 | 13,723 | 24,909 | 1,500 |
| 20261112 | C | 204,500 | 11,369 | 93,639 | 4,563 | 24,546 | 2,049 |
| 20261112 | CL | 204,780 | 11,235 | 93,882 | 4,533 | 24,562 | 2,010 |
| 20261112 | T | 204,500 | 11,369 | 93,639 | 4,563 | 24,873 | 1,634 |
| 20261112 | TL | 204,780 | 11,236 | 93,894 | 4,533 | 24,885 | 1,603 |
| 1 | D | 327,850 | 2,226 | 15,519 | 12,340 | 26,311 | 1,380 |
| 1 | C | 197,840 | 12,836 | 115,901 | 4,120 | 25,708 | 2,142 |
| 1 | CL | 197,320 | 12,733 | 116,730 | 4,010 | 25,731 | 2,092 |
| 1 | T | 197,840 | 12,836 | 115,901 | 4,120 | 26,024 | 1,740 |
| 1 | TL | 197,320 | 12,734 | 116,732 | 4,010 | 26,043 | 1,701 |

**The claims.** **(L1) FAILS:** CL has 0.988 and 0.992 of C's stockout cells (margin 0.95). **(L2) FAILS:** CL has 0.981 and 0.977 of C's lapses (margin 0.97): the direction is right, a fall of 1.9 and 2.3 percent where 3 was asked (L1 asked for 5 and got falls of 1.2 and 0.8). **(L3) FAILS, as expected:** TL has 1.069 and 1.233 of D's lapses (margin 1.00); against T's 1.089 and 1.261 that is 2 percent less. The margins were not moved.

**Why (measured after the failure, so a diagnosis and not a gate):** the plan is limited by the room constraints, not by the target. In the 240 plans of C (seed 20261112) the cold room binds in 152 and is zero in 140 (the pharmacy already holds more than its cap), the shelf room binds in 29; only 35,927 of 48,000 cells reach their target in C and 35,734 in CL. A higher target changes the objective where the room allows, and the room mostly does not: units ordered went from 204,500 to 204,780 (plus 0.1 percent) and from 197,840 to 197,320. This is the limitation already written in the report on the first version ("the twin's pharmacies ignore their own space limits, so 69 of 96 decisions have no refrigerated room"): **the twin's own policy orders without those limits and the planner obeys them, which is most of why C orders a third to two fifths less and has the stockouts.** The sizing of the design missed it: it estimated a 5 to 15 percent fall in stockout cells from the target alone, which the room constraints made impossible, and that is an error of the design, not of the measurement.

**What this shows and does not show.** A lapse cost that moves the target is the wrong lever here: it is built correctly (G24, G25) and its effect is real but small: stockout cells down 1.2 and 0.8 percent (5 asked), lapses down 1.9 and 2.3 percent (3 asked), units ordered up 0.1 percent on one seed and down 0.3 on the other. It does not show that a lapse cost is useless: with the room constraints out of the way it may matter, which was not run. Other values of L were not run either (the diagnosis says the room limits, not L, are the cap on the plan; that is not measured for other L). **The change that the diagnosis points to is the room constraint** (relaxing it, or giving the twin's pharmacies the same limit), which changes what C is compared with and has not been tried; it needs its own design and margins.
