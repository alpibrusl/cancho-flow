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


def simulate(p, n, items, pharmacies, root):
    """Weekly sales at every pharmacy for every item, under a plain order-up-to policy. Demand is drawn week by week in a fixed order and does not depend on the
    stock, so two policies see the same demand; the sales are the demand cut at the stock on hand (the censoring), and the stock has lots that expire.
    Returns (dispensing rows, true-demand rows, the counts the truth records)."""
    rd = root.fork("demand")
    rb = root.fork("base_rates")
    base = [[rb.categorical(p["item_base_rate_milli"]) for _ in items] for _ in pharmacies]
    gi = {it[0]: GROUPS.index(it[6]) for it in items}
    cells = []  # per (pharmacy, item): [lots, pending, sold history, base milli, group, pack, shelf weeks]
    for pi, ph in enumerate(pharmacies):
        for ii, it in enumerate(items):
            b = base[pi][ii]
            shelf_weeks = it[1] // 7
            m0 = mean_milli(b, ph[4], 1_000_000)
            cells.append([[[shelf_weeks, m0 * 2 // 1000 + 1]], 0, [], b, gi[it[0]], it[5], shelf_weeks, ph[4], ph[0], it[0]])
    disp, truth, sold_out, wasted, sold_total, demand_total = [], [], 0, 0, 0, 0
    for week in range(n["weeks"]):
        for c in cells:
            lots, pending, hist, b, g, pack, shelf_weeks, scale, phid, itid = c
            received = pending
            if received:
                lots.append([week + shelf_weeks, received])
            c[1] = 0
            written_off = 0
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
            c[1] = ordered
            disp.append((phid, itid, week, stock_start, received, written_off, sold, int(demand > stock_start), stock_end, ordered))
            truth.append((phid, itid, week, demand))
            sold_out += demand > stock_start
            wasted += written_off
            sold_total += sold
            demand_total += demand
    return disp, truth, {"stockout_cells": sold_out, "written_off_units": wasted, "units_sold": sold_total, "units_demanded": demand_total}


def generate(world, seed, size, tables=("core", "dispensing")):
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
        "params": {k: {"value": v["value"], "source": v["source"]} for k, v in world["params"].items()},
        "realised": {
            "cold_chain_items": cold,
            "controlled_items": controlled,
            "critical_items": critical,
            "patients_by_age_band": dict(zip(AGE_BANDS, ages)),
            "patients_by_copay_band": dict(zip(COPAY_BANDS, copays)),
        },
    }
    if "dispensing" in tables:
        disp, tdem, sim = simulate(p, n, items, pharmacies, root)
        files["dispensing.csv"] = _csv(("pharmacy", "item", "week", "stock_start", "received", "written_off", "units", "stockout", "stock_end", "ordered"), disp)
        files["truth/demand.csv"] = _csv(("pharmacy", "item", "week", "demand"), tdem)  # the analysis never reads this file; the gates do
        truth["counts"]["weeks"] = n["weeks"]
        truth["realised"].update(sim)
        truth["realised"]["items_by_group"] = {g: sum(1 for it in items if it[6] == g) for g in GROUPS}
    files["truth.json"] = json.dumps(truth, sort_keys=True, separators=(",", ":")) + "\n"
    return files, truth
