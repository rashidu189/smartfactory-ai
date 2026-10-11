"""SYNTHETIC demo data for Level 3 features (sensors, stations, work orders).

Deterministic (seeded) so tests and demos are reproducible. All of it is labelled synthetic in the UI.

Sensor story (60 days hourly, 12 machines, ending 2026-10-11 23:00):
  * Most failures are preceded by 2–5 days of degradation (vibration / temperature / current drift),
    then a failure event, ~8 h without readings, and a maintenance reset.
  * L03-PRS-01 (Line 03 press) failed on 2026-10-05 and 2026-10-08 and is degrading again now.
  * L01-CNV-01 (Line 01 conveyor drive) shows rising temperature in the last ~3 days (no failure yet).
  * L02-PKG-01 has random sensor spikes but no real degradation (tests false alarms).
Station story (30 days): Line 02 Pressing station is the constraint, with rising utilisation and WIP.
Work orders: open orders for the next 14 days, with a demand spike on Line 02.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

END = datetime(2026, 10, 11, 23, 0)
DAYS = 60
MACHINES = [
    ("L01-CNV-01", "Line 01", "Conveyor drive"), ("L01-FIL-01", "Line 01", "Filler"),
    ("L02-PRS-01", "Line 02", "Press"), ("L02-PKG-01", "Line 02", "Packer"),
    ("L03-PRS-01", "Line 03", "Press"), ("L03-CNC-01", "Line 03", "CNC mill"),
    ("L03-CNV-01", "Line 03", "Conveyor drive"), ("L04-MLD-01", "Line 04", "Moulder"),
    ("L04-PRS-01", "Line 04", "Press"), ("L05-INJ-01", "Line 05", "Injection moulder"),
    ("L05-CNV-01", "Line 05", "Conveyor drive"), ("L05-PKG-01", "Line 05", "Packer"),
]
BASE = {"temperature_c": 62.0, "vibration_mm_s": 2.2, "current_a": 15.0, "pressure_bar": 6.0, "rpm": 1480.0}
NOISE = {"temperature_c": 1.2, "vibration_mm_s": 0.22, "current_a": 0.5, "pressure_bar": 0.12, "rpm": 12.0}

# (machine, failure time, degradation hours, signature) — signature = which signals drift and how much
FAILURES = [
    ("L03-PRS-01", datetime(2026, 8, 25, 14), 96, {"vibration_mm_s": 3.5, "temperature_c": 9}),
    ("L03-PRS-01", datetime(2026, 9, 18, 6), 72, {"vibration_mm_s": 4.0, "current_a": 3}),
    ("L03-PRS-01", datetime(2026, 10, 5, 9), 90, {"vibration_mm_s": 4.2, "temperature_c": 10}),
    ("L03-PRS-01", datetime(2026, 10, 8, 16), 48, {"vibration_mm_s": 3.8, "temperature_c": 8}),
    ("L02-PRS-01", datetime(2026, 9, 2, 20), 110, {"vibration_mm_s": 3.0, "pressure_bar": -1.2}),
    ("L04-MLD-01", datetime(2026, 8, 30, 3), 80, {"temperature_c": 14, "current_a": 2.5}),
    ("L04-MLD-01", datetime(2026, 9, 27, 11), 70, {"temperature_c": 12, "current_a": 3}),
    ("L05-INJ-01", datetime(2026, 9, 9, 15), 100, {"temperature_c": 11, "pressure_bar": -1.0}),
    ("L01-FIL-01", datetime(2026, 9, 21, 8), 60, {"current_a": 3.5, "vibration_mm_s": 2.0}),
    ("L03-CNC-01", datetime(2026, 9, 14, 22), 84, {"vibration_mm_s": 3.2, "rpm": -60}),
    ("L05-CNV-01", datetime(2026, 10, 1, 4), 72, {"temperature_c": 10, "vibration_mm_s": 2.5}),
]
# Degradation in progress at END (no failure yet): (machine, start, hours to reach full signature, signature)
ONGOING = [
    ("L03-PRS-01", END - timedelta(hours=60), 96, {"vibration_mm_s": 4.0, "temperature_c": 9}),
    ("L01-CNV-01", END - timedelta(hours=72), 96, {"temperature_c": 12, "vibration_mm_s": 1.8}),
]


def sensors() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (machines, readings, events)."""
    rng = np.random.default_rng(42)
    start = END - timedelta(days=DAYS) + timedelta(hours=1)
    hours = pd.date_range(start, END, freq="h")
    readings, events = [], []
    for code, line, mtype in MACHINES:
        n = len(hours)
        drift = {k: np.zeros(n) for k in BASE}
        down = np.zeros(n, dtype=bool)
        fails = [f for f in FAILURES if f[0] == code]
        for _, ft, deg_h, sig in fails:
            idx_f = hours.get_indexer([ft], method="nearest")[0]
            for k, amp in sig.items():
                for j in range(max(0, idx_f - deg_h), idx_f):
                    frac = (j - (idx_f - deg_h)) / deg_h
                    drift[k][j] += amp * frac ** 1.5
            down[idx_f: idx_f + 8] = True
            events.append({"machine_code": code, "ts": ft, "event_type": "failure", "description": f"{mtype} failure"})
            events.append({"machine_code": code, "ts": ft + timedelta(hours=8), "event_type": "maintenance",
                           "description": "Corrective maintenance after failure"})
        for mc, st, full_h, sig in ONGOING:
            if mc != code:
                continue
            i0 = hours.get_indexer([st], method="nearest")[0]
            for k, amp in sig.items():
                for j in range(i0, n):
                    drift[k][j] += amp * min(1.0, (j - i0) / full_h) ** 1.5
        # Planned maintenance roughly every 3 weeks
        for k in range(1, DAYS // 21 + 1):
            events.append({"machine_code": code, "ts": start + timedelta(days=21 * k - 3, hours=sum(map(ord, code)) % 12),
                           "event_type": "maintenance", "description": "Planned preventive maintenance"})
        daily = np.sin(np.arange(n) / 24 * 2 * np.pi)
        for i, ts in enumerate(hours):
            if down[i]:
                continue
            r = {"machine_code": code, "ts": ts.to_pydatetime()}
            for k, base in BASE.items():
                v = base + drift[k][i] + rng.normal(0, NOISE[k])
                if k == "temperature_c":
                    v += 1.5 * daily[i]
                r[k] = round(float(v), 3)
            if code == "L02-PKG-01" and rng.random() < 0.02:     # harmless sensor spikes
                r["vibration_mm_s"] = round(r["vibration_mm_s"] + rng.uniform(2, 4), 3)
            readings.append(r)
    m = pd.DataFrame(MACHINES, columns=["machine_code", "line", "machine_type"])
    return m, pd.DataFrame(readings), pd.DataFrame(events).sort_values("ts").reset_index(drop=True)


STATIONS = ["Cutting", "Pressing", "Assembly", "Packing"]
LINES = ["Line 01", "Line 02", "Line 03", "Line 04", "Line 05"]
CYCLE = {"Cutting": 40.0, "Pressing": 46.0, "Assembly": 43.0, "Packing": 36.0}  # ideal seconds per unit


def stations(end: date = date(2026, 10, 11), days: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for d in range(days):
        day = end - timedelta(days=days - 1 - d)
        for line in LINES:
            demand_units = 1000 + rng.normal(0, 25)
            for st in STATIONS:
                avail = 960.0  # 2 shifts x 8 h
                down = float(max(0, rng.normal(30, 8)))
                cycle = CYCLE[st] * (1 + rng.normal(0, 0.01))
                wip = max(0, rng.normal(60, 10))
                units = demand_units
                if line == "Line 02" and st == "Pressing":
                    cycle = CYCLE[st] * (1.05 + 0.006 * d)      # tool wear: cycle time creeping up
                    down = float(max(0, rng.normal(45 + d * 1.2, 8)))
                    capacity = (avail - down) * 60 / cycle
                    units = min(demand_units, capacity * 0.97)
                    wip = 60 + d * 9 + rng.normal(0, 8)            # queue building in front of the press
                if line == "Line 03" and st == "Pressing" and 7 <= (day - date(2026, 9, 28)).days <= 13:
                    down = float(max(0, rng.normal(190, 30)))
                    capacity = (avail - down) * 60 / cycle
                    units = min(demand_units, capacity * 0.97)
                    wip = 80 + rng.normal(30, 10)
                rows.append({"date": day.isoformat(), "line": line, "station": st, "available_minutes": avail,
                             "downtime_minutes": round(down, 1), "units_processed": int(units),
                             "ideal_cycle_time_s": round(cycle, 2), "wip_units": int(max(0, wip))})
    return pd.DataFrame(rows)


def work_orders(start: date = date(2026, 10, 12), days: int = 14) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    rows, n = [], 1
    products = {"Line 01": "Bottle Cap A", "Line 02": "Bottle Cap B", "Line 03": "Pump Housing",
                "Line 04": "Valve Seal", "Line 05": "Spray Nozzle"}
    for d in range(days):
        due = start + timedelta(days=d)
        for line, product in products.items():
            qty = int(rng.normal(980, 40))
            if line == "Line 02" and d >= 3:
                qty = int(qty * 1.18)       # customer demand spike
            rows.append({"order_id": f"WO-{26000 + n}", "product": product, "line": line, "quantity": qty,
                         "due_date": due.isoformat(), "status": "released" if d < 3 else "planned", "customer": f"C-{100 + (n % 7)}"})
            n += 1
    return pd.DataFrame(rows)


def simulate_readings(last_ts: datetime, hours: int, repaired_after: dict[str, datetime], seed: int = 0) -> pd.DataFrame:
    """Continue the synthetic sensor streams for `hours` after `last_ts` (used by the IoT simulator).
    Ongoing degradation keeps growing unless the machine had maintenance after the degradation started."""
    rng = np.random.default_rng(seed or int(last_ts.timestamp()) % 100000)
    rows = []
    for h in range(1, hours + 1):
        ts = last_ts + timedelta(hours=h)
        for code, line, mtype in MACHINES:
            r = {"machine_code": code, "line": line, "machine_type": mtype, "ts": ts}
            drift = {k: 0.0 for k in BASE}
            for mc, st, full_h, sig in ONGOING:
                if mc == code and not (repaired_after.get(code) and repaired_after[code] > st):
                    frac = min(1.0, (ts - st) / timedelta(hours=full_h))
                    for k, amp in sig.items():
                        drift[k] += amp * frac ** 1.5
            daily = np.sin((ts.hour) / 24 * 2 * np.pi)
            for k, base in BASE.items():
                v = base + drift[k] + rng.normal(0, NOISE[k]) + (1.5 * daily if k == "temperature_c" else 0)
                r[k] = round(float(v), 3)
            rows.append(r)
    return pd.DataFrame(rows)
