"""The twin as a stepping environment (docs/use-cases.md section 7a, U7a): the same world, one week at a time, with the decisions of the tools as input.

With no decisions it writes every file of the batch twin byte for byte (G18). The stock and the delivery run week by week and day by day (core.StockSim, delivery.DeliveryWorld); the refill series cannot be
stepped as the batch twin draws it, because that draws a patient's items one after the other from one stream, so an outcome of one item moves every draw of the next. It is stepped with common random numbers:
the batch twin is run once without decisions, and every refill event keeps the uniform number it has there; an event beyond what the batch twin had (an outreach kept a patient on) takes its number from a
stream of its own. Each effect is then causal: a decision can change an outcome from its week on and nothing before.
"""
import hashlib

from . import core, decisions as dec_mod, delivery
from .core import GROUPS, _csv
from .prng import SplitMix64
from .world import OUTREACH_PARAMS, TwinError


class _Rec(SplitMix64):
    """A stream that logs every `below` it answers, so that the draws of a patient can be read back; forks are logged by their label."""

    def __init__(self, seed, reg):
        SplitMix64.__init__(self, seed)
        self.reg = reg
        self.log = []

    def below(self, n):
        v = SplitMix64.below(self, n)
        self.log.append((n, v))
        return v

    def fork(self, label):
        h = hashlib.sha256(("%d:%s" % (self.seed, label)).encode("utf-8")).digest()
        c = _Rec(int.from_bytes(h[:8], "big"), self.reg)
        self.reg[label] = c
        return c


def _entities(world, seed, size):
    files, truth = core.generate(world, seed, size, ("core",))

    def rows(name):
        lines = files[name].splitlines()
        return [ln.split(",") for ln in lines[1:]]
    items = [(r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5]), r[6]) for r in rows("items.csv")]
    pharmacies = [(r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in rows("pharmacies.csv")]
    patients = [(r[0], r[1], r[2], int(r[3]), int(r[4]), r[5]) for r in rows("patients.csv")]
    return files, truth, items, pharmacies, patients


def _crn(p, n, patients, items, stockouts, root):
    """The batch refill series without decisions, with the numbers it drew: {(patient, item): (first week, [uniforms])} and the batch's rows."""
    rec = _Rec(root.seed, {})
    rows, hazards, counts = core.refill_series(p, n, patients, items, stockouts, rec)
    chronic = [it[0] for it in items if it[6] == "chronic"]
    per = {}
    for r in rows:
        per[(r[0], r[1])] = per.get((r[0], r[1]), 0) + 1
    table = {}
    for pid, age, home, n_items, interval_days, copay in patients:
        log = rec.reg[pid].log
        pool, chosen, pos = list(chronic), [], 0
        for _ in range(min(n_items, len(pool))):
            chosen.append(pool.pop(log[pos][1]))
            pos += 1
        for it in sorted(chosen):
            w0 = log[pos][1]
            pos += 1
            k = per.get((pid, it), 0)
            table[(pid, it)] = (w0, [log[pos + j][1] for j in range(k)])
            pos += k
    return table, rows, hazards, counts


def run(world, seed, size, tables, decisions_dir=None, through=None):
    """Returns ({file name: text}, truth). `through`: the last week to run (default: all)."""
    p = {k: v["value"] for k, v in world["params"].items()}
    n = world["sizes"][size]
    weeks = n["weeks"]
    last = weeks - 1 if through is None else min(through, weeks - 1)
    root = SplitMix64(seed)
    files, truth, items, pharmacies, patients = _entities(world, seed, size)
    n_pharm = {ph[0]: (ph[2], ph[3]) for ph in pharmacies}
    item_info = {it[0]: (it[5], bool(it[2])) for it in items}
    coupled, with_delivery, with_stock, with_refills = "coupled" in tables, "delivery" in tables, "dispensing" in tables, "refills" in tables
    if coupled and (not with_delivery or not with_stock or "depot_cap_kw" not in world["params"]):
        raise TwinError("twin.bad-tables", "the table coupled needs dispensing and delivery, and the delivery parameters in the world file", "use --tables core,dispensing,delivery,coupled")
    if with_delivery and "depot_cap_kw" not in world["params"]:
        raise TwinError("twin.missing-param", "the table delivery needs the delivery parameters in the world file", "add the delivery parameters (docs/use-cases.md section 4.2)")
    # the world the batch twin makes without decisions: its refill numbers, and its stock for the stockouts they were drawn against
    crn, window = {}, p["stockout_window_weeks"]
    if with_refills:
        dflags = None
        if coupled:
            _f, _r, dflags = delivery.generate(p, n, pharmacies, root)
        ddisp, _t, _c = core.simulate(p, n, items, pharmacies, root, dflags)
        crn, _rows, _haz, _cnt = _crn(p, n, patients, items, {(r[0], r[1], r[2]) for r in ddisp if r[7]}, root)
    trucks = set()
    if with_delivery:
        probe = delivery.DeliveryWorld(p, n, pharmacies, root)
        trucks = {t[0] for t in probe.trucks}
    dec = {}
    if decisions_dir is not None:
        dec = dec_mod.load(decisions_dir, weeks, item_info, n_pharm, trucks, set(crn))
        for w, d in dec.items():
            if d["orders"] and not with_stock:
                raise TwinError("twin.decision-tables", "week-%d.json has orders and the tables have no dispensing" % w, "ask for the dispensing table, or leave the orders out")
            if d["outreach"] and not with_refills:
                raise TwinError("twin.decision-tables", "week-%d.json has outreach and the tables have no refills" % w, "ask for the refills table, or leave the outreach out")
            if d["outreach"] and "outreach_uplift_ppm" not in world["params"]:
                raise TwinError("twin.missing-param", "week-%d.json has outreach and the world file has no outreach_uplift_ppm" % w, "add outreach_uplift_ppm to the world file")
            if d["charge"] and not with_delivery:
                raise TwinError("twin.decision-tables", "week-%d.json has charges and the tables have no delivery" % w, "ask for the delivery table, or leave the charges out")
    uplift = dict(zip(dec_mod.ACTIONS, world["params"]["outreach_uplift_ppm"]["value"])) if "outreach_uplift_ppm" in world["params"] else {}
    dw = delivery.DeliveryWorld(p, n, pharmacies, root) if with_delivery else None
    flags = {"late": dw.late_weeks, "warm": dw.warm_weeks} if coupled else None
    sim = core.StockSim(p, n, items, pharmacies, root, flags) if with_stock else None
    # the refill world: events due by week, the state of each series
    chronic_home = {pt[0]: pt for pt in patients}
    due, state, order_idx = {}, {}, {pt[0]: i for i, pt in enumerate(patients)}
    if with_refills:
        for (pid, it), (w0, u) in crn.items():
            pt = chronic_home[pid]
            interval = max(1, pt[4] // 7)
            fixed = p["lapse_base_ppm"] + p["lapse_per_extra_item_ppm"] * (pt[3] - 1) + p["lapse_copay_ppm"][core.COPAY_BANDS.index(pt[5])] + p["lapse_age_ppm"][core.AGE_BANDS.index(pt[1])]
            state[(pid, it)] = {"home": pt[2], "interval": interval, "fixed": fixed, "u": u, "j": 0, "extra": None}
            if w0 < weeks:
                due.setdefault(w0, []).append((pid, it))
    extra_root = root.fork("refills_extra")
    rrows, rhaz = [], []
    seen_events = lapses = 0
    stockouts = set()
    done_disp = 0
    charged = False
    for W in range(last + 1):
        if dw is not None:
            prev = dec.get(W - 1)
            for d in range(7 * W, 7 * W + 7):
                avail = None
                if prev is not None and prev["charge"]:
                    avail = {tr: k for (day, tr), k in prev["charge"].items() if day == d}
                    charged = True
                dw.day(d, avail)
        if sim is not None:
            sim.step(W, dec[W]["orders"] if W in dec and dec[W]["orders"] else None)
            for r in sim.disp[done_disp:]:
                if r[7]:
                    stockouts.add((r[0], r[1], r[2]))
            done_disp = len(sim.disp)
        if with_refills:
            acts = dec[W - 1]["outreach"] if (W - 1) in dec else {}
            events = due.pop(W, [])
            if acts:
                missing = [k for k in acts if k not in set(events)]
                if missing:
                    raise TwinError("twin.decision-not-due", "week-%d.json acts on %s and %s, which is not a refill event due in week %d" % (W - 1, missing[0][0], missing[0][1], W), "act only on the events due in the week after the decision")
            for key in events:
                st = state[key]
                pid, it = key
                seen = int(any((st["home"], it, x) in stockouts for x in range(max(0, W - window + 1), W + 1)))
                chance = min(1_000_000, st["fixed"] + p["lapse_stockout_ppm"] * seen)
                if key in acts:
                    chance = chance * (1_000_000 - uplift[acts[key]]) // 1_000_000
                if st["j"] < len(st["u"]):
                    u = st["u"][st["j"]]
                else:
                    if st["extra"] is None:
                        st["extra"] = extra_root.fork(pid).fork(it)
                    u = st["extra"].ppm()
                st["j"] += 1
                lapse = u < chance
                rrows.append((pid, it, st["home"], W, st["interval"], seen, int(not lapse)))
                rhaz.append((pid, it, W, chance))
                seen_events += seen
                if lapse:
                    lapses += 1
                else:
                    nxt = W + st["interval"]
                    if nxt < weeks:
                        due.setdefault(nxt, []).append(key)
    # ---- the files, as the batch twin writes them ----
    truth["tables"] = sorted(tables)
    if coupled:
        files["truth/coupling.csv"] = _csv(("pharmacy", "week", "late", "warm"), [(ph[0], w, int((ph[0], w) in dw.late_weeks), int((ph[0], w) in dw.warm_weeks)) for ph in pharmacies for w in range(last + 1)])
    if with_stock:
        files["dispensing.csv"] = _csv(("pharmacy", "item", "week", "stock_start", "received", "written_off", "units", "stockout", "stock_end", "ordered"), sim.disp)
        files["truth/demand.csv"] = _csv(("pharmacy", "item", "week", "demand", "true_mean_milli"), sim.truth)
        truth["counts"]["weeks"] = last + 1
        truth["realised"].update(sim.counts())
        if with_refills:
            rrows.sort(key=lambda r: (order_idx[r[0]], r[1], r[3]))
            rhaz.sort(key=lambda r: (order_idx[r[0]], r[1], r[2]))
            files["truth/refill_hazard.csv"] = _csv(("patient", "item", "due_week", "true_lapse_ppm"), rhaz)
            files["refills.csv"] = _csv(("patient", "item", "pharmacy", "due_week", "interval_weeks", "stockout_seen", "filled"), rrows)
            truth["realised"].update({"refill_events": len(rrows), "refill_events_seen_a_stockout": seen_events, "refill_lapses": lapses})
        truth["realised"]["items_by_group"] = {g: sum(1 for it in items if it[6] == g) for g in GROUPS}
    if with_delivery:
        files.update(dw.files())
        from .world import DELIVERY_PARAMS
        truth["delivery_params"] = {k: {"value": world["params"][k]["value"], "source": world["params"][k]["source"]} for k in DELIVERY_PARAMS}
        truth["delivery_realised"] = dw.realised
        if charged:
            files["truth/short.csv"] = _csv(("route", "seq"), dw.short)  # the stops a route did not reach for want of energy (decisions only)
    import json
    files["truth.json"] = json.dumps(truth, sort_keys=True, separators=(",", ":")) + "\n"
    return files, truth
