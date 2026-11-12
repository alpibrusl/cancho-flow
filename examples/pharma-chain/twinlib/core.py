"""The shared entities of the chain: items, pharmacies and patients (docs/use-cases.md sections 4.1 to 4.3 read them).

`generate(world, seed, size)` returns ({file name: text}, truth). Nothing here reads a clock, a path or the environment.
"""
import json

from .prng import SplitMix64

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


def generate(world, seed, size):
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

    r = root.fork("pharmacies")
    pharmacies = []
    for i in range(n["pharmacies"]):
        pharmacies.append(("P%03d" % (i + 1), 1 + r.below(p["regions"]), r.categorical(p["shelf_capacity_units"]), r.categorical(p["cold_capacity_units"])))

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
        "items.csv": _csv(("item", "shelf_life_days", "cold_chain", "critical", "controlled", "pack_size"), items),
        "pharmacies.csv": _csv(("pharmacy", "region", "shelf_capacity_units", "cold_capacity_units"), pharmacies),
        "patients.csv": _csv(("patient", "age_band", "home_pharmacy", "n_items", "refill_interval_days", "copay_band"), patients),
    }
    truth = {
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
    files["truth.json"] = json.dumps(truth, sort_keys=True, separators=(",", ":")) + "\n"
    return files, truth
