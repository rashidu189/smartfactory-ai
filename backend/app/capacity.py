"""Production bottleneck forecasting (Level 3).

For each line we find the constraint station (Theory of Constraints: the station with the highest
load, ties broken by queue/WIP), project each station's daily capacity, load and WIP forward with a
linear trend, and compare the projected constraint capacity with ERP demand (open work orders).

Definitions per station-day:
  run time      = available_minutes - downtime_minutes
  capacity      = run time x 60 / ideal_cycle_time_s           (units the station could make)
  utilisation % = units_processed x ideal_cycle_time_s / (run time x 60) x 100
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .validation import ValidationError

HISTORY = 14
HORIZON = 7
STATION_COLS = ["date", "line", "station", "available_minutes", "downtime_minutes", "units_processed", "ideal_cycle_time_s", "wip_units"]
ORDER_COLS = ["order_id", "line", "quantity", "due_date"]


def normalise_stations(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: str(c).strip().lower().replace(" ", "_") for c in df.columns})
    df = df.rename(columns={"cycle_time_s": "ideal_cycle_time_s", "units": "units_processed", "wip": "wip_units"})
    missing = [c for c in STATION_COLS if c not in df.columns and c != "wip_units"]
    if missing:
        raise ValidationError("Missing required column(s): " + ", ".join(missing), ["Station files need: " + ", ".join(STATION_COLS)])
    if "wip_units" not in df.columns:
        df["wip_units"] = 0
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in STATION_COLS[3:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if df[STATION_COLS].isna().any().any():
        raise ValidationError("Some station rows have invalid dates or numbers.")
    if (df["ideal_cycle_time_s"] <= 0).any() or (df["available_minutes"] <= 0).any():
        raise ValidationError("ideal_cycle_time_s and available_minutes must be greater than 0.")
    df["line"] = df["line"].astype(str).str.strip()
    df["station"] = df["station"].astype(str).str.strip()
    return df[STATION_COLS]


def normalise_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: str(c).strip().lower().replace(" ", "_") for c in df.columns})
    df = df.rename(columns={"qty": "quantity", "due": "due_date", "work_order": "order_id", "id": "order_id"})
    missing = [c for c in ORDER_COLS if c not in df.columns]
    if missing:
        raise ValidationError("Missing required column(s): " + ", ".join(missing),
                              ["Work orders need: order_id, line, quantity, due_date; optional product, status, customer"])
    df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce").dt.date
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    if df[["due_date", "quantity"]].isna().any().any():
        raise ValidationError("Some work orders have an invalid due_date or quantity.")
    for c, default in (("product", ""), ("status", "planned"), ("customer", "")):
        df[c] = df[c].fillna(default).astype(str) if c in df.columns else default
    df["order_id"] = df["order_id"].astype(str).str.strip()
    df["line"] = df["line"].astype(str).str.strip()
    return df


def _trend(y: np.ndarray, steps: int) -> tuple[float, np.ndarray]:
    x = np.arange(len(y), dtype=float)
    if len(y) < 3 or np.allclose(y, y[0]):
        return 0.0, np.full(steps, float(y[-1]))
    slope, intercept = np.polyfit(x, y, 1)
    fut = intercept + slope * np.arange(len(y), len(y) + steps)
    return float(slope), fut


def analyse(stations: pd.DataFrame, orders: pd.DataFrame) -> dict:
    if stations.empty:
        return {"lines": [], "stations": [], "findings": [], "horizon_days": HORIZON, "forecast_from": None}
    st = stations.copy()
    st["run_min"] = (st["available_minutes"] - st["downtime_minutes"]).clip(lower=1)
    st["capacity"] = st["run_min"] * 60 / st["ideal_cycle_time_s"]
    st["utilisation"] = (st["units_processed"] * st["ideal_cycle_time_s"] / (st["run_min"] * 60) * 100).clip(upper=150)
    last_day = max(st["date"])
    start = last_day + timedelta(days=1)
    days = [start + timedelta(days=i) for i in range(HORIZON)]
    open_orders = orders[~orders["status"].str.lower().isin(["completed", "closed", "cancelled"])] if not orders.empty else orders

    station_rows, line_rows, findings = [], [], []
    for line, lg in st.groupby("line", sort=True):
        per = []
        for name, g in lg.groupby("station"):
            g = g.sort_values("date").tail(HISTORY)
            cap_slope, cap_fut = _trend(g["capacity"].to_numpy(), HORIZON)
            ut_slope, ut_fut = _trend(g["utilisation"].to_numpy(), HORIZON)
            wip_slope, wip_fut = _trend(g["wip_units"].to_numpy(), HORIZON)
            recent = g.tail(7)
            per.append({
                "line": line, "station": name,
                "utilisation_pct": round(float(recent["utilisation"].mean()), 1),
                "capacity_per_day": round(float(recent["capacity"].mean()), 0),
                "units_per_day": round(float(recent["units_processed"].mean()), 0),
                "wip_units": round(float(recent["wip_units"].mean()), 0),
                "downtime_per_day": round(float(recent["downtime_minutes"].mean()), 1),
                "cycle_time_s": round(float(recent["ideal_cycle_time_s"].mean()), 2),
                "trend": {"capacity_per_day": round(cap_slope, 1), "utilisation_pct": round(ut_slope, 2), "wip_units": round(wip_slope, 1)},
                "forecast": {"capacity": [round(max(0, float(v)), 0) for v in cap_fut],
                             "utilisation_pct": [round(float(v), 1) for v in ut_fut],
                             "wip_units": [round(max(0, float(v)), 0) for v in wip_fut]},
                "history": {"dates": [str(d) for d in g["date"]], "utilisation_pct": [round(float(v), 1) for v in g["utilisation"]],
                            "wip_units": [int(v) for v in g["wip_units"]], "capacity": [round(float(v), 0) for v in g["capacity"]]},
            })
        per.sort(key=lambda r: (-r["utilisation_pct"], -r["wip_units"]))
        constraint = per[0]
        for r in per:
            r["is_constraint"] = r is constraint
        # Projected constraint = the station with the lowest projected capacity each day.
        proj_cap = np.min(np.array([r["forecast"]["capacity"] for r in per]), axis=0)
        proj_station = [per[int(i)]["station"] for i in np.argmin(np.array([r["forecast"]["capacity"] for r in per]), axis=0)]
        lo = open_orders[open_orders["line"] == line] if not open_orders.empty else open_orders
        demand = [float(lo.loc[lo["due_date"] == d, "quantity"].sum()) if len(lo) else 0.0 for d in days]
        has_demand = sum(demand) > 0
        gap = [round(max(0.0, dm - c), 0) for dm, c in zip(demand, proj_cap)] if has_demand else [0.0] * HORIZON
        short_days = sum(1 for g_ in gap if g_ > 0)
        row = {
            "line": line, "constraint_station": constraint["station"], "constraint_utilisation_pct": constraint["utilisation_pct"],
            "constraint_wip": constraint["wip_units"], "capacity_per_day": constraint["capacity_per_day"],
            "forecast_days": [str(d) for d in days], "projected_capacity": [float(v) for v in proj_cap],
            "projected_constraint": proj_station, "demand": demand, "shortfall": gap,
            "shortfall_units": float(sum(gap)), "shortfall_days": short_days,
            "demand_units": float(sum(demand)), "has_demand": has_demand,
            "constraint_shift": proj_station[-1] != constraint["station"],
        }
        line_rows.append(row)
        station_rows.extend(per)

        # Findings
        if has_demand and short_days:
            pct = row["shortfall_units"] / row["demand_units"] * 100
            findings.append(_f("critical" if pct >= 5 or short_days >= 3 else "warning", line,
                               f"{line}: {proj_station[-1]} cannot meet demand on {short_days} of {HORIZON} days",
                               f"Projected {proj_station[-1]} capacity {min(proj_cap):,.0f}–{max(proj_cap):,.0f} units/day vs ERP demand "
                               f"{min(demand):,.0f}–{max(demand):,.0f}; shortfall ≈ {row['shortfall_units']:,.0f} units ({pct:.1f}% of demand) "
                               f"from {days[0]} to {days[-1]}. Current {constraint['station']} load {constraint['utilisation_pct']}%, "
                               f"capacity trend {constraint['trend']['capacity_per_day']:+.0f} units/day per day.", pct))
        if constraint["trend"]["wip_units"] >= 5 and constraint["utilisation_pct"] >= 90:
            findings.append(_f("warning", line,
                               f"{line}: queue building in front of {constraint['station']}",
                               f"WIP at {constraint['station']} averages {constraint['wip_units']:.0f} units and is rising "
                               f"{constraint['trend']['wip_units']:+.1f} units/day at {constraint['utilisation_pct']}% load; "
                               f"projected {constraint['forecast']['wip_units'][-1]:.0f} units by {days[-1]}.", constraint["utilisation_pct"]))
        elif not has_demand and max(constraint["forecast"]["utilisation_pct"]) >= 97:
            findings.append(_f("warning", line, f"{line}: {constraint['station']} projected near full load",
                               f"Load projected to reach {max(constraint['forecast']['utilisation_pct']):.0f}% within {HORIZON} days "
                               f"(no ERP demand loaded for this line).", constraint["utilisation_pct"]))

    order = {"critical": 0, "warning": 1}
    findings.sort(key=lambda f: (order[f["severity"]], -f["value"]))
    for i, f in enumerate(findings, start=1):
        f["id"] = f"B{i}"
    return {"lines": line_rows, "stations": station_rows, "findings": findings, "horizon_days": HORIZON,
            "forecast_from": str(start), "history_days": HISTORY, "last_data_day": str(last_day)}


def _f(sev, line, title, evidence, value):
    return {"id": "", "severity": sev, "category": "bottleneck", "line": line, "date": f"next {HORIZON} days",
            "metric": "shortfall", "value": round(float(value), 1), "threshold": None, "title": title,
            "evidence": evidence + " Linear-trend projection, not a guarantee."}
