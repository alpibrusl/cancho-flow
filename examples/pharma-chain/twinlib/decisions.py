"""The decisions of the tools, as input to the stepping twin (docs/use-cases.md section 7a, U7a).

A decisions directory holds files `week-<W>.json`, each the decisions made at the end of week W from the data through week W:

    {"week": W,
     "orders":   [{"pharmacy": "P001", "item": "I0001", "units": 40}, ...],      the order placed at the end of week W (arrives in week W+1), instead of the order-up-to rule
     "outreach": [{"patient": "N000001", "item": "I0001", "action": "call"}, ...], an action on a refill event due in week W+1
     "charge":   [{"truck": "T01", "day": 7, "kwh": 60}, ...]}                      the energy a truck holds for its route of that day, a day of week W+1

Every member is optional; a week with no file has no decisions (the twin's own policies). Everything is checked before anything runs: a refusal is a TwinError `twin.decision-<name>` with a repair, and
nothing reaches a traceback. Numbers are whole numbers.
"""
import json
import os

from .world import TwinError

MAX_BYTES = 1_048_576
ACTIONS = ("call", "reminder", "switch90", "delivery")
KEYS = {"week", "orders", "outreach", "charge"}


def _bad(rule, msg, repair):
    raise TwinError("twin.decision-" + rule, msg, repair)


def _whole(v):
    return isinstance(v, int) and not isinstance(v, bool)


def load(path, weeks, items, pharmacies, trucks, patients_with):
    """Returns {week: {"orders": {(pharmacy, item): units}, "outreach": {(patient, item): action}, "charge": {(day, truck): kwh}}}.
    items: {item: (pack, cold)}; pharmacies: {pharmacy: (shelf capacity, cold capacity)}; trucks: set of names; patients_with: set of (patient, item) pairs that exist."""
    out = {}
    try:
        names = sorted(os.listdir(path))
    except OSError:
        _bad("unreadable", "the decisions directory cannot be read", "check the path of --decisions")
    for name in names:
        if not (name.startswith("week-") and name.endswith(".json")):
            _bad("file", "%r in the decisions directory is not week-<W>.json" % name, "keep only week-<W>.json files there")
        digits = name[len("week-"):-len(".json")]
        if not digits.isascii() or not digits.isdigit() or len(digits) > 6 or (len(digits) > 1 and digits[0] == "0"):
            _bad("file", "%r is not week-<W>.json with W a whole number without leading zeros" % name, "name the file week-<W>.json")
        w = int(digits)
        full = os.path.join(path, name)
        try:
            with open(full, "rb") as f:
                raw = f.read(MAX_BYTES + 1)
        except OSError:
            _bad("unreadable", "%s cannot be read" % name, "check the file")
        if len(raw) > MAX_BYTES:
            _bad("too-large", "%s is larger than %d bytes" % (name, MAX_BYTES), "split the decisions: one file per week")
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            _bad("json", "%s is not JSON" % name, "write the decisions as one JSON object")
        if not isinstance(doc, dict) or set(doc) - KEYS or doc.get("week") != w or not _whole(doc.get("week")):
            _bad("week", "%s must be an object whose members are week (equal to %d), orders, outreach and charge" % (name, w), "fix the members of %s" % name)
        if not 0 <= w < weeks:
            _bad("week", "%s names a week outside 0 to %d" % (name, weeks - 1), "decide only for the weeks the world has")
        res = {"orders": {}, "outreach": {}, "charge": {}}
        for e in _list(doc, "orders", name):
            _members(e, {"pharmacy", "item", "units"}, name)
            ph, it, u = e["pharmacy"], e["item"], e["units"]
            if ph not in pharmacies:
                _bad("unknown-pharmacy", "%s orders for the pharmacy %r, which is not in the world" % (name, ph), "use a pharmacy of pharmacies.csv")
            if it not in items:
                _bad("unknown-item", "%s orders the item %r, which is not in the world" % (name, it), "use an item of items.csv")
            if not _whole(u) or u < 0:
                _bad("number", "%s orders %r units of %s at %s: units are whole numbers, not negative" % (name, u, it, ph), "give a whole number of units, 0 or more")
            pack, cold = items[it]
            if u % pack:
                _bad("pack", "%s orders %d of %s, which is not a multiple of its pack size %d" % (name, u, it, pack), "order whole packs")
            cap = pharmacies[ph][1] if cold else pharmacies[ph][0]
            if u > cap:
                _bad("over-capacity", "%s orders %d of %s at %s, above the %d units of its space" % (name, u, it, ph, cap), "order no more than the space holds")
            if (ph, it) in res["orders"]:
                _bad("duplicate", "%s orders %s at %s twice" % (name, it, ph), "one order per pharmacy and item")
            res["orders"][(ph, it)] = u
        for e in _list(doc, "outreach", name):
            _members(e, {"patient", "item", "action"}, name)
            pa, it, ac = e["patient"], e["item"], e["action"]
            if (pa, it) not in patients_with:
                _bad("unknown-patient", "%s acts on %r and %r, which is not a patient and an item they take" % (name, pa, it), "use a patient and one of their items")
            if ac not in ACTIONS:
                _bad("unknown-action", "%s uses the action %r" % (name, ac), "the actions are " + ", ".join(ACTIONS))
            if (pa, it) in res["outreach"]:
                _bad("duplicate", "%s acts on %s and %s twice" % (name, pa, it), "one action per event")
            res["outreach"][(pa, it)] = ac
        for e in _list(doc, "charge", name):
            _members(e, {"truck", "day", "kwh"}, name)
            tr, d, k = e["truck"], e["day"], e["kwh"]
            if tr not in trucks:
                _bad("unknown-truck", "%s charges the truck %r, which is not in the world" % (name, tr), "use a truck of trucks.csv")
            if not _whole(d) or not 7 * (w + 1) <= d <= 7 * (w + 1) + 6:
                _bad("day", "%s charges for the day %r: the days of week %d are %d to %d" % (name, d, w + 1, 7 * (w + 1), 7 * (w + 1) + 6), "charge for a day of the week after the decision")
            if not _whole(k) or k < 0:
                _bad("number", "%s charges %r kWh: whole kWh, not negative" % (name, k), "give a whole number of kWh, 0 or more")
            if (d, tr) in res["charge"]:
                _bad("duplicate", "%s charges %s for day %d twice" % (name, tr, d), "one charge per truck and day")
            res["charge"][(d, tr)] = k
        out[w] = res
    return out


def _list(doc, key, name):
    v = doc.get(key, [])
    if not isinstance(v, list):
        _bad("week", "the member %s of %s is not a list" % (key, name), "make it a list of objects")
    return v


def _members(e, keys, name):
    if not isinstance(e, dict) or set(e) != keys:
        _bad("week", "an entry of %s must be an object with exactly the members %s" % (name, ", ".join(sorted(keys))), "fix the entry")
    for k in ("pharmacy", "item", "patient", "action", "truck"):
        if k in e and not isinstance(e[k], str):
            _bad("type", "the member %s of an entry of %s is not a string" % (k, name), "give %s as a string" % k)
