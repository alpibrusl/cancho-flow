"""The shared entities of the chain: items, pharmacies and patients (docs/use-cases.md sections 4.1 to 4.3 read them).

`generate(world, seed, size)` returns ({file name: text}, truth). Nothing here reads a clock, a path or the environment.
"""
import json

from .prng import SplitMix64

GROUPS = ("chronic", "respiratory", "allergy")
AGE_BANDS = ("18-39", "40-54", "55-64", "65-74", "75+")
COPAY_BANDS = ("low", "mid", "high")


def _csv(header, rows):
    out = [",".join(header)]
    for r in rows:
        cells = [str(c) for c in r]
        for c in cells:
            assert not any(ch in c for ch in ',"\n\r'), c
        out.append(",".join(cells))
    return "\n".join(out) + "\n"


def season_ppm(week, peak, amp_ppm):
    """The seasonal multiplier in parts per million, a triangle over the 52 weeks of a year: 1+amp at the peak, 1-amp half a year away."""
    d = abs(week % 52 - peak)
    d = min(d, 52 - d)
    return 1_000_000 + amp_ppm * (26 - 2 * d) // 26


def mean_milli(base_milli, scale_ppm, seas_ppm):
    return max(1, base_milli * scale_ppm // 1_000_000 * seas_ppm // 1_000_000)


class StockSim:
    """Weekly sales at every pharmacy for every item, under a plain order-up-to policy, one week at a time. Demand is drawn week by week in a fixed order and does not depend on the
    stock, so two policies see the same demand; the sales are the demand cut at the stock on hand (the censoring), and the stock has lots that expire. `step(week, orders)` runs one
    week: `orders`, if given, is {(pharmacy, item): units} and replaces the order-up-to rule for those cells at the end of the week (U7)."""

    def __init__(self, p, n, items, pharmacies, root, flags=None):
        self.p, self.n, self.flags = p, n, flags
        self.rd = root.fork("demand")
        rb = root.fork("base_rates")
        base = [[rb.categorical(p["item_base_rate_milli"]) for _ in items] for _ in pharmacies]
        gi = {it[0]: GROUPS.index(it[6]) for it in items}
        self.cells = []  # per (pharmacy, item): [lots, pending, sold history, base milli, group, pack, shelf weeks, scale, pharmacy, item, held, cold]
        for pi, ph in enumerate(pharmacies):
            for ii, it in enumerate(items):
                b = base[pi][ii]
                shelf_weeks = it[1] // 7
                m0 = mean_milli(b, ph[4], 1_000_000)
                self.cells.append([[[shelf_weeks, m0 * 2 // 1000 + 1]], 0, [], b, gi[it[0]], it[5], shelf_weeks, ph[4], ph[0], it[0], 0, it[2]])
        self.disp, self.truth = [], []
        self.sold_out = self.wasted = self.sold_total = self.demand_total = 0
        self.enforce = bool(p.get("enforce_capacity", 0))  # U10: the space limits (the shelf and cold capacities of pharmacies.csv) bind the orders
        self.caps = {ph[0]: (ph[2], ph[3]) for ph in pharmacies}

    def step(self, week, orders=None):
        p, flags, rd = self.p, self.flags, self.rd
        pend = []
        for c in self.cells:
            lots, pending, hist, b, g, pack, shelf_weeks, scale, phid, itid, held, cold = c
            arriving = pending + held
            c[10] = 0
            if flags and (phid, week) in flags["late"]:
                c[10] = arriving  # a late delivery of the week: what was due is held to the next week (docs/use-cases.md section 4.2, U4d)
                arriving = 0
            received = arriving
            discarded = received if (flags and cold and (phid, week) in flags["warm"]) else 0  # a warm delivery of the week: the cold-chain batch is thrown away on arrival
            if received and not discarded:
                lots.append([week + shelf_weeks, received])
            c[1] = 0
            written_off = discarded
            kept = []
            for exp, u in lots:
                if exp <= week:
                    written_off += u
                else:
                    kept.append([exp, u])
            kept.sort()
            c[0] = lots = kept
            stock_start = sum(u for _, u in lots)
            seas = season_ppm(week, p["season_peak_week"][g], p["season_amplitude_ppm"][g])
            demand = rd.poisson_milli(mean_milli(b, scale, seas))
            sold = min(demand, stock_start)
            need = sold
            for lot in lots:
                take = min(need, lot[1])
                lot[1] -= take
                need -= take
            c[0] = lots = [lot for lot in lots if lot[1] > 0]
            stock_end = sum(u for _, u in lots)
            hist.append(sold)
            recent = hist[-p["trailing_weeks"]:]
            target = -(-p["order_cover_ppm"] * sum(recent) // (1_000_000 * len(recent)))
            want = max(0, target - stock_end)
            ordered = -(-want // pack) * pack if want else 0
            given = orders is not None and (phid, itid) in orders
            default = ordered
            if given:
                ordered = orders[(phid, itid)]
            c[1] = ordered
            if self.enforce:
                pend.append((len(self.disp), c, pack, default, given, cold, stock_end))
            self.disp.append((phid, itid, week, stock_start, received, written_off, sold, int(demand > stock_start), stock_end, ordered))
            self.truth.append((phid, itid, week, demand, mean_milli(b, scale, seas)))
            self.sold_out += demand > stock_start
            self.wasted += written_off
            self.sold_total += sold
            self.demand_total += demand
        if self.enforce:
            self._limit(week, pend)

    def _limit(self, week, pend):
        """The space limits (U10): for each pharmacy and class the room is max(0, capacity - the stock at the end of the week); the orders given by a decision must fit in it (else twin.decision-over-room), and the orders of the
        policy are what is left of the room, cut in proportion when they do not fit (each order times the room over the total, rounded down to whole packs)."""
        groups = {}
        for item in pend:
            c, cold = item[1], item[5]
            groups.setdefault((c[8], cold), []).append(item)
        for (phid, cold), its in groups.items():
            cap = self.caps[phid][1 if cold else 0]
            room = max(0, cap - sum(it[6] for it in its))
            given = sum(it[1][1] for it in its if it[4])
            if given > room:
                from .world import TwinError
                raise TwinError("twin.decision-over-room", "the orders of week %d for %s (%s items) are %d units, above the %d units of room that its stock leaves" % (week, phid, "cold-chain" if cold else "other", given, room), "order no more than the room")
            left = room - given
            total = sum(it[3] for it in its if not it[4])
            if total > left:
                for idx, c, pack, default, was_given, _cold, _se in its:
                    if was_given:
                        continue
                    ordered = (default * left // total) // pack * pack
                    c[1] = ordered
                    self.disp[idx] = self.disp[idx][:-1] + (ordered,)

    def counts(self):
        return {"stockout_cells": self.sold_out, "written_off_units": self.wasted, "units_sold": self.sold_total, "units_demanded": self.demand_total}


def simulate(p, n, items, pharmacies, root, flags=None):
    """The whole horizon at once: the batch twin. Returns (dispensing rows, true-demand rows, the counts the truth records)."""
    sim = StockSim(p, n, items, pharmacies, root, flags)
    for week in range(n["weeks"]):
        sim.step(week)
    return sim.disp, sim.truth, sim.counts()


def refill_series(p, n, patients, items, stockouts, root):
    """For every patient, the series of refills of each chronic item they take, from a random first due week every interval, until the first one that is not
    filled (a lapse) or the end of the horizon. A refill is not filled with a probability that is the sum of a base, the regimen, the co-payment, the age
    band and, when the home pharmacy was out of the item in the weeks up to the due date, the coupling. Returns (rows, the true lapse probability of each, counts)."""
    chronic = [it[0] for it in items if it[6] == "chronic"]
    r = root.fork("refills")
    window = p["stockout_window_weeks"]
    rows, hazards, seen_events, lapses = [], [], 0, 0
    for pid, age, home, n_items, interval_days, copay in patients:
        rp = r.fork(pid)
        pool = list(chronic)
        chosen = []
        for _ in range(min(n_items, len(pool))):
            chosen.append(pool.pop(rp.below(len(pool))))
        interval = max(1, interval_days // 7)
        fixed = p["lapse_base_ppm"] + p["lapse_per_extra_item_ppm"] * (n_items - 1) + p["lapse_copay_ppm"][COPAY_BANDS.index(copay)] + p["lapse_age_ppm"][AGE_BANDS.index(age)]
        for it in sorted(chosen):
            w = rp.below(interval)
            while w < n["weeks"]:
                seen = int(any((home, it, x) in stockouts for x in range(max(0, w - window + 1), w + 1)))
                chance = min(1_000_000, fixed + p["lapse_stockout_ppm"] * seen)
                lapse = rp.bernoulli(chance)
                rows.append((pid, it, home, w, interval, seen, int(not lapse)))
                hazards.append((pid, it, w, chance))
                seen_events += seen
                if lapse:
                    lapses += 1
                    break
                w += interval
    return rows, hazards, {"refill_events": len(rows), "refill_events_seen_a_stockout": seen_events, "refill_lapses": lapses}


def generate(world, seed, size, tables=("core", "dispensing", "refills")):
    from .world import DELIVERY_PARAMS, OUTREACH_PARAMS, TwinError
    p = {k: v["value"] for k, v in world["params"].items()}
    n = world["sizes"][size]
    root = SplitMix64(seed)

    r = root.fork("items")
    items, cold, controlled, critical = [], 0, 0, 0
    for i in range(n["items"]):
        c = r.bernoulli(p["cold_chain_share_ppm"])
        k = r.bernoulli(p["controlled_share_ppm"])
        x = r.bernoulli(p["critical_share_ppm"])
        cold += c
        controlled += k
        critical += x
        items.append(("I%04d" % (i + 1), r.categorical(p["shelf_life_days"]), int(c), int(x), int(k), r.categorical(p["pack_sizes"])))
    rg = root.fork("item_groups")
    items = [it + (GROUPS[rg.weighted_index(p["therapeutic_group_weights"])],) for it in items]

    r = root.fork("pharmacies")
    pharmacies = []
    for i in range(n["pharmacies"]):
        pharmacies.append(("P%03d" % (i + 1), 1 + r.below(p["regions"]), r.categorical(p["shelf_capacity_units"]), r.categorical(p["cold_capacity_units"])))
    rs = root.fork("pharmacy_scales")
    pharmacies = [ph + (rs.categorical(p["pharmacy_scale_ppm"]),) for ph in pharmacies]

    r = root.fork("patients")
    patients, ages, copays = [], [0] * len(AGE_BANDS), [0] * len(COPAY_BANDS)
    for i in range(n["patients"]):
        a = r.weighted_index(p["age_band_weights"])
        c = r.weighted_index(p["copay_band_weights"])
        ages[a] += 1
        copays[c] += 1
        patients.append(("N%06d" % (i + 1), AGE_BANDS[a], "P%03d" % (1 + r.below(n["pharmacies"])), r.categorical(p["items_per_patient"]),
                         r.categorical(p["refill_interval_days"]), COPAY_BANDS[c]))

    files = {
        "items.csv": _csv(("item", "shelf_life_days", "cold_chain", "critical", "controlled", "pack_size", "therapeutic_group"), items),
        "pharmacies.csv": _csv(("pharmacy", "region", "shelf_capacity_units", "cold_capacity_units", "scale_ppm"), pharmacies),
        "patients.csv": _csv(("patient", "age_band", "home_pharmacy", "n_items", "refill_interval_days", "copay_band"), patients),
    }
    truth = {
        "tables": sorted(tables),
        "schema": "twin.truth.v1",
        "world": world["name"],
        "seed": seed,
        "size": size,
        "counts": {"items": n["items"], "pharmacies": n["pharmacies"], "patients": n["patients"]},
        "params": {k: {"value": v["value"], "source": v["source"]} for k, v in world["params"].items() if k not in DELIVERY_PARAMS and k not in OUTREACH_PARAMS},
        "realised": {
            "cold_chain_items": cold,
            "controlled_items": controlled,
            "critical_items": critical,
            "patients_by_age_band": dict(zip(AGE_BANDS, ages)),
            "patients_by_copay_band": dict(zip(COPAY_BANDS, copays)),
        },
    }
    flags = None
    if "coupled" in tables:
        if "delivery" not in tables or "dispensing" not in tables or "depot_cap_kw" not in world["params"]:
            raise TwinError("twin.bad-tables", "the table coupled needs dispensing and delivery, and the delivery parameters in the world file", "use --tables core,dispensing,delivery,coupled")
        from . import delivery as _dl
        _f, _r, flags = _dl.generate(p, n, pharmacies, root)  # the same streams as the delivery tables below: asking twice gives the same bytes
        files["truth/coupling.csv"] = _csv(("pharmacy", "week", "late", "warm"), [(ph[0], w, int((ph[0], w) in flags["late"]), int((ph[0], w) in flags["warm"])) for ph in pharmacies for w in range(n["weeks"])])  # the analysis never reads this file; the gates do
    if "dispensing" in tables:
        disp, tdem, sim = simulate(p, n, items, pharmacies, root, flags)
        files["dispensing.csv"] = _csv(("pharmacy", "item", "week", "stock_start", "received", "written_off", "units", "stockout", "stock_end", "ordered"), disp)
        files["truth/demand.csv"] = _csv(("pharmacy", "item", "week", "demand", "true_mean_milli"), tdem)  # the analysis never reads this file; the gates do
        truth["counts"]["weeks"] = n["weeks"]
        truth["realised"].update(sim)
        if "refills" in tables:
            stockouts = {(row[0], row[1], row[2]) for row in disp if row[7]}
            rrows, rhaz, rcounts = refill_series(p, n, patients, items, stockouts, root)
            files["truth/refill_hazard.csv"] = _csv(("patient", "item", "due_week", "true_lapse_ppm"), rhaz)  # the analysis never reads this file; the gates do
            files["refills.csv"] = _csv(("patient", "item", "pharmacy", "due_week", "interval_weeks", "stockout_seen", "filled"), rrows)
            truth["realised"].update(rcounts)
        truth["realised"]["items_by_group"] = {g: sum(1 for it in items if it[6] == g) for g in GROUPS}
    if "delivery" in tables:
        if "depot_cap_kw" not in world["params"]:
            raise TwinError("twin.missing-param", "the table delivery needs the delivery parameters in the world file", "add the delivery parameters (docs/use-cases.md section 4.2)")
        from . import delivery
        dfiles, dreal, _flags = delivery.generate(p, n, pharmacies, root)
        files.update(dfiles)
        truth["delivery_params"] = {k: {"value": world["params"][k]["value"], "source": world["params"][k]["source"]} for k in DELIVERY_PARAMS}
        truth["delivery_realised"] = dreal
    files["truth.json"] = json.dumps(truth, sort_keys=True, separators=(",", ":")) + "\n"
    return files, truth
