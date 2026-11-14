"""A's twin: electric reefer trucks delivering to the pharmacies (docs/use-cases.md section 4.2 and the U4a margins of section 7a).

Integer arithmetic only. A day's deliveries are sorted by the end of their window and cut into routes of at most 3 stops; the routes take trucks (the biggest battery to the
costliest route). A stop's energy in watt-hours is driving + refrigeration + doors, with a noise; the analysis sees the total, `truth/` holds the parts and the excursion probability.
"""
from .core import _csv

MAX_STOPS = 3
DAY_START_MIN = 7 * 60
SPEED_UNITS = 60  # minutes per hour


def generate(p, n, pharmacies, root):
    """Returns ({file name: text}, realised counts)."""
    days = n["weeks"] * 7
    n_trucks = max(2, n["pharmacies"] // 2)
    rt = root.fork("trucks")
    trucks = [("T%02d" % (i + 1), rt.categorical(p["truck_battery_kwh"])) for i in range(n_trucks)]
    rl = root.fork("locations")
    grid = p["grid_km"]
    loc = {ph[0]: (rl.below(grid + 1), rl.below(grid + 1)) for ph in pharmacies}
    rw = root.fork("temperature")
    temps = []
    for d in range(days):
        wk = d // 7
        dist = abs(wk % 52 - p["warm_peak_week"])
        dist = min(dist, 52 - dist)
        temps.append(p["temp_mean_c"] + p["temp_amplitude_c"] * (26 - 2 * dist) // 26 + rw.normal_micro() * p["temp_noise_c"] // 1_000_000)
    rd = root.fork("deliveries")
    rr = root.fork("routing")
    rn = root.fork("noise")
    rx = root.fork("excursions")
    deliveries, routes, tele, parts, exc, day_rows = [], [], [], [], [], []
    realised = {"deliveries": 0, "routes": 0, "stops": 0, "excursions": 0, "late_stops": 0, "energy_violations": 0}
    rid = 0
    for d in range(days):
        T = temps[d]
        day_rows.append((d, T))
        todays = []
        for ph in pharmacies:
            if rd.bernoulli(p["delivery_prob_ppm"]):
                start = rd.categorical(p["window_start_hours"]) * 60
                todays.append((start + 120, start, ph[0]))
        todays.sort()
        for e, s, phid in todays:
            deliveries.append((d, phid, s, e))
        realised["deliveries"] += len(todays)
        built = []
        for i in range(0, len(todays), MAX_STOPS):
            chunk = todays[i:i + MAX_STOPS]
            t = DAY_START_MIN
            x = y = 0
            rows = []
            total_km = 0
            for seq, (e, s, phid) in enumerate(chunk, 1):
                px, py = loc[phid]
                km = abs(px - x) + abs(py - y)
                travel = km * SPEED_UNITS // p["speed_kmh"]
                arrive = max(t + travel, s)
                wait = arrive - (t + travel)
                door = rr.categorical(p["door_open_minutes"])
                service = max(door, rr.categorical(p["stop_service_minutes"]))
                elapsed = travel + wait + service
                fridge_ppm = 1_000_000 + p["fridge_temp_ppm"] * max(0, T - 20) // 10
                drive_wh = km * p["drive_wh_per_km"]
                fridge_wh = p["fridge_w"] * elapsed * fridge_ppm // (1_000_000 * 60)
                door_wh = p["door_w"] * door // 60
                raw = drive_wh + fridge_wh + door_wh
                wh = max(0, raw * (1_000_000 + p["noise_ppm"] * rn.normal_micro() // 1_000_000) // 1_000_000)
                prob = min(1_000_000, p["excursion_base_ppm"] + p["excursion_per_door_min_ppm"] * door + p["excursion_per_10c_ppm"] * max(0, T - 20) // 10)
                ex = int(rx.bernoulli(prob))
                temp_dc = (82 + rx.below(30)) if ex else (40 + rx.below(35))
                rows.append([seq, phid, km, arrive, e, door, temp_dc, wh, elapsed, drive_wh, fridge_wh, door_wh, prob, ex])
                total_km += km
                t = arrive + service
                x, y = px, py
                realised["late_stops"] += int(arrive > e)
            # the return to the depot, with the refrigeration still running
            km = x + y
            travel = km * SPEED_UNITS // p["speed_kmh"]
            fridge_ppm = 1_000_000 + p["fridge_temp_ppm"] * max(0, T - 20) // 10
            drive_wh = km * p["drive_wh_per_km"]
            fridge_wh = p["fridge_w"] * travel * fridge_ppm // (1_000_000 * 60)
            raw = drive_wh + fridge_wh
            wh = max(0, raw * (1_000_000 + p["noise_ppm"] * rn.normal_micro() // 1_000_000) // 1_000_000)
            rows.append([len(chunk) + 1, "DEPOT", km, t + travel, t + travel, 0, 40 + rx.below(35), wh, travel, drive_wh, fridge_wh, 0, 0, 0])
            total_km += km
            built.append((sum(r[7] for r in rows), total_km, rows))
        # biggest battery to the costliest route; routes of a day never outnumber the trucks (3 stops of at most 10 pharmacies a day would need 4)
        order = sorted(range(len(built)), key=lambda k: (-built[k][0], k))
        free = sorted(range(len(trucks)), key=lambda k: (-trucks[k][1], k))
        for k, ti in zip(order, free):
            energy, km, rows = built[k]
            rid += 1
            name = "R%06d" % rid
            tr = trucks[ti]
            routes.append((name, d, tr[0], len(rows) - 1, km, energy, DAY_START_MIN, T))
            realised["energy_violations"] += int(energy > (tr[1] - p["reserve_kwh"]) * 1000)
            for r in rows:
                tele.append((name, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
                parts.append((name, r[0], r[9], r[10], r[11]))
                exc.append((name, r[0], r[12], r[13]))
                realised["excursions"] += r[13]
            realised["stops"] += len(rows) - 1
            realised["routes"] += 1
        assert len(built) <= len(trucks), "more routes in a day than trucks"
    files = {
        "trucks.csv": _csv(("truck", "battery_kwh"), trucks),
        "locations.csv": _csv(("pharmacy", "x_km", "y_km"), [(k, v[0], v[1]) for k, v in sorted(loc.items())]),
        "days.csv": _csv(("day", "outside_temp_c"), day_rows),
        "deliveries.csv": _csv(("day", "pharmacy", "window_start_min", "window_end_min"), deliveries),
        "routes.csv": _csv(("route", "day", "truck", "stops", "distance_km", "energy_wh", "depart_min", "outside_temp_c"), routes),
        "telemetry.csv": _csv(("route", "seq", "pharmacy", "km", "arrive_min", "window_end_min", "door_open_min", "cabin_temp_dc", "energy_wh", "minutes"), tele),
        "depot.csv": _csv(("hour", "cap_kw", "tariff_milli"), [(h, p["depot_cap_kw"][h], p["depot_tariff_milli"][h]) for h in range(24)]),
        "truth/energy_parts.csv": _csv(("route", "seq", "drive_wh", "fridge_wh", "door_wh"), parts),  # the analysis never reads this file; the gates do
        "truth/excursion.csv": _csv(("route", "seq", "true_ppm", "excursion"), exc),  # the analysis never reads this file; the gates do
    }
    return files, realised
