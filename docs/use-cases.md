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
