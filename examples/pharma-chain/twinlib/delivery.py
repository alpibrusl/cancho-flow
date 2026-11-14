"""A's twin: electric reefer trucks delivering to the pharmacies (docs/use-cases.md section 4.2 and the U4a margins of section 7a).

Integer arithmetic only. A day's deliveries are sorted by the end of their window and cut into routes of at most 3 stops; the routes take trucks (the biggest battery to the
costliest route). A stop's energy in watt-hours is driving + refrigeration + doors, with a noise; the analysis sees the total, `truth/` holds the parts and the excursion probability.
"""
from .core import _csv

MAX_STOPS = 3
DAY_START_MIN = 7 * 60
SPEED_UNITS = 60  # minutes per hour


class DeliveryWorld:
    """The deliveries, one day at a time. `day(d, available)` runs day d: `available`, if given, is {truck: kWh} and a route whose truck holds less than the energy the route actually uses ends short:
    the stops after the point where the energy runs out are not delivered (they are written in `short`, and their pharmacy-week counts as late) (U7). Without it every route is driven."""

    def __init__(self, p, n, pharmacies, root):
        self.p, self.n, self.pharmacies = p, n, pharmacies
        self.days = n["weeks"] * 7
        n_trucks = max(2, n["pharmacies"] // 2)
        rt = root.fork("trucks")
        self.trucks = [("T%02d" % (i + 1), rt.categorical(p["truck_battery_kwh"])) for i in range(n_trucks)]
        rl = root.fork("locations")
        grid = p["grid_km"]
        self.loc = {ph[0]: (rl.below(grid + 1), rl.below(grid + 1)) for ph in pharmacies}
        rw = root.fork("temperature")
        self.temps = []
        for d in range(self.days):
            wk = d // 7
            dist = abs(wk % 52 - p["warm_peak_week"])
            dist = min(dist, 52 - dist)
            self.temps.append(p["temp_mean_c"] + p["temp_amplitude_c"] * (26 - 2 * dist) // 26 + rw.normal_micro() * p["temp_noise_c"] // 1_000_000)
        self.rd = root.fork("deliveries")
        self.rr = root.fork("routing")
        self.rn = root.fork("noise")
        self.rx = root.fork("excursions")
        self.deliveries, self.routes, self.tele, self.parts, self.exc, self.day_rows, self.short = [], [], [], [], [], [], []
        self.late_weeks, self.warm_weeks = set(), set()
        self.realised = {"deliveries": 0, "routes": 0, "stops": 0, "excursions": 0, "late_stops": 0, "energy_violations": 0}
        self.rid = 0

    def day(self, d, available=None):
        p, pharmacies, loc, trucks = self.p, self.pharmacies, self.loc, self.trucks
        rd, rr, rn, rx, realised = self.rd, self.rr, self.rn, self.rx, self.realised
        T = self.temps[d]
        self.day_rows.append((d, T))
        todays = []
        for ph in pharmacies:
            if rd.bernoulli(p["delivery_prob_ppm"]):
                start = rd.categorical(p["window_start_hours"]) * 60
                todays.append((start + 120, start, ph[0]))
        todays.sort()
        for e, s, phid in todays:
            self.deliveries.append((d, phid, s, e))
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
                if arrive > e:
                    self.late_weeks.add((phid, d // 7))
                if ex:
                    self.warm_weeks.add((phid, d // 7))
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
            self.rid += 1
            name = "R%06d" % self.rid
            tr = trucks[ti]
            self.routes.append((name, d, tr[0], len(rows) - 1, km, energy, DAY_START_MIN, T))
            realised["energy_violations"] += int(energy > (tr[1] - p["reserve_kwh"]) * 1000)
            if available is not None and tr[0] in available and energy > available[tr[0]] * 1000:
                used = 0  # the stops the energy reaches are delivered, the others are not
                for r in rows[:-1]:
                    used += r[7]
                    if used > available[tr[0]] * 1000:
                        self.short.append((name, r[0]))
                        self.late_weeks.add((r[1], d // 7))
            for r in rows:
                self.tele.append((name, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
                self.parts.append((name, r[0], r[9], r[10], r[11]))
                self.exc.append((name, r[0], r[12], r[13]))
                realised["excursions"] += r[13]
            realised["stops"] += len(rows) - 1
            realised["routes"] += 1
        assert len(built) <= len(trucks), "more routes in a day than trucks"

    def files(self):
        p, loc = self.p, self.loc
        return {
            "trucks.csv": _csv(("truck", "battery_kwh"), self.trucks),
            "locations.csv": _csv(("pharmacy", "x_km", "y_km"), [(k, v[0], v[1]) for k, v in sorted(loc.items())]),
            "days.csv": _csv(("day", "outside_temp_c"), self.day_rows),
            "deliveries.csv": _csv(("day", "pharmacy", "window_start_min", "window_end_min"), self.deliveries),
            "routes.csv": _csv(("route", "day", "truck", "stops", "distance_km", "energy_wh", "depart_min", "outside_temp_c"), self.routes),
            "telemetry.csv": _csv(("route", "seq", "pharmacy", "km", "arrive_min", "window_end_min", "door_open_min", "cabin_temp_dc", "energy_wh", "minutes"), self.tele),
            "depot.csv": _csv(("hour", "cap_kw", "tariff_milli"), [(h, p["depot_cap_kw"][h], p["depot_tariff_milli"][h]) for h in range(24)]),
            "truth/energy_parts.csv": _csv(("route", "seq", "drive_wh", "fridge_wh", "door_wh"), self.parts),  # the analysis never reads this file; the gates do
            "truth/excursion.csv": _csv(("route", "seq", "true_ppm", "excursion"), self.exc),  # the analysis never reads this file; the gates do
        }


def generate(p, n, pharmacies, root):
    """The whole horizon at once: the batch twin. Returns ({file name: text}, realised counts, {"late": weeks, "warm": weeks})."""
    w = DeliveryWorld(p, n, pharmacies, root)
    for d in range(w.days):
        w.day(d)
    return w.files(), w.realised, {"late": w.late_weeks, "warm": w.warm_weeks}
