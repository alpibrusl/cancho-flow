"""The world file: the named parameters of the twin, each with where it came from (docs/use-cases.md section 2, T3).

Every refusal is a TwinError with a rule tag `twin.<name>`; nothing here reaches a traceback.
"""
import json

SOURCES = ("choice", "read", "fitted")
SIZES = ("small", "large")
MAX_COUNT = 1_000_000


class TwinError(Exception):
    def __init__(self, rule, message, repair="see docs/use-cases.md"):
        Exception.__init__(self, message)
        self.rule = rule
        self.message = message
        self.repair = repair


# name -> kind. share: an integer in parts per million; weighted: a list of [positive integer, positive integer]; weights(n): n positive
# integers; count: a positive integer.
PARAMS = {
    "cold_chain_share_ppm": "share",
    "controlled_share_ppm": "share",
    "critical_share_ppm": "share",
    "shelf_life_days": "weighted",
    "pack_sizes": "weighted",
    "refill_interval_days": "weighted",
    "items_per_patient": "weighted",
    "shelf_capacity_units": "weighted",
    "cold_capacity_units": "weighted",
    "age_band_weights": "weights5",
    "copay_band_weights": "weights3",
    "regions": "count",
}


def _int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _check_value(name, kind, v):
    ok = False
    if kind == "share":
        ok = _int(v) and 0 <= v <= 1_000_000
    elif kind == "count":
        ok = _int(v) and 1 <= v <= 1000
    elif kind == "weighted":
        ok = (isinstance(v, list) and 1 <= len(v) <= 64
              and all(isinstance(p, list) and len(p) == 2 and _int(p[0]) and p[0] >= 1 and _int(p[1]) and p[1] >= 1 for p in v))
    elif kind in ("weights5", "weights3"):
        n = 5 if kind == "weights5" else 3
        ok = isinstance(v, list) and len(v) == n and all(_int(w) and w >= 1 for w in v)
    if not ok:
        raise TwinError("twin.bad-param", "parameter %s is not a valid %s" % (name, kind), "fix the value of %s in the world file" % name)


def parse(text):
    try:
        w = json.loads(text)
    except ValueError:
        raise TwinError("twin.bad-world", "the world file is not JSON", "give a JSON file of schema twin.world.v1")
    if not isinstance(w, dict) or w.get("schema") != "twin.world.v1":
        raise TwinError("twin.bad-world", "the world file does not say schema twin.world.v1")
    name = w.get("name")
    if not isinstance(name, str) or not name or len(name) > 64 or any(c in name for c in ',"\n\r'):
        raise TwinError("twin.bad-world", "the world needs a short plain name")
    sizes = w.get("sizes")
    if not isinstance(sizes, dict) or set(sizes) != set(SIZES):
        raise TwinError("twin.bad-world", "sizes must hold exactly small and large")
    for s in SIZES:
        e = sizes[s]
        if not isinstance(e, dict) or set(e) != {"pharmacies", "items", "patients"} or not all(_int(e[k]) and 1 <= e[k] <= MAX_COUNT for k in e):
            raise TwinError("twin.bad-world", "size %s needs pharmacies, items and patients, each 1 to %d" % (s, MAX_COUNT))
    params = w.get("params")
    if not isinstance(params, dict):
        raise TwinError("twin.bad-world", "the world has no params")
    for k in params:
        if k not in PARAMS:
            raise TwinError("twin.unknown-param", "unknown parameter %s" % k, "the parameters are: " + ", ".join(sorted(PARAMS)))
    for k, kind in PARAMS.items():
        if k not in params:
            raise TwinError("twin.missing-param", "parameter %s is missing" % k, "add %s to the world file" % k)
        e = params[k]
        if not isinstance(e, dict) or "value" not in e or e.get("source") not in SOURCES or not isinstance(e.get("note"), str):
            raise TwinError("twin.bad-param", "parameter %s needs value, source (choice, read or fitted) and note" % k)
        if e["source"] != "choice" and not isinstance(e.get("from"), str):
            raise TwinError("twin.bad-param", "parameter %s is %s and must say where from" % (k, e["source"]), "add a `from` naming the file or source")
        _check_value(k, kind, e["value"])
    return w
