"""Unified evidence registry.

Every finding the AI may cite has an ID:
  F  rule-based KPI thresholds          (production dataset)
  A  statistical anomalies              (production dataset)
  P  short-term trend risk per line     (production dataset)
  V  visual inspection defects          (production dataset)
  M  ML machine-failure predictions     (plant level, live sensor data)
  B  bottleneck / capacity forecasts    (plant level, stations + ERP orders)

Plant-level results are cached per instance and recomputed when plant data changes or after a TTL.
"""
from __future__ import annotations

import re
import threading
import time

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import capacity, db, machine_health

ID_RE = re.compile(r"\b([FAPVMB]\d{1,4})\b")
TTL_S = 60
_lock = threading.Lock()
_cache: dict = {"version": -1, "at": 0.0, "value": None}
_version = 0


def invalidate() -> None:
    global _version
    with _lock:
        _version += 1


def _compute(s: Session) -> dict:
    try:
        ml = machine_health.predict(s)
    except Exception as e:  # noqa: BLE001 - plant data problems must not break production views
        ml = {"model": None, "machines": [], "error": f"{type(e).__name__}: {e}"}
    st = pd.read_sql(sa.select(*[getattr(db.StationRecord, c) for c in capacity.STATION_COLS]), s.bind)
    wo = pd.read_sql(sa.select(db.WorkOrder.order_id, db.WorkOrder.line, db.WorkOrder.quantity, db.WorkOrder.due_date,
                               db.WorkOrder.status, db.WorkOrder.product, db.WorkOrder.customer), s.bind)
    if not st.empty:
        st["date"] = pd.to_datetime(st["date"]).dt.date
    if not wo.empty:
        wo["due_date"] = pd.to_datetime(wo["due_date"]).dt.date
    cap = capacity.analyse(st, wo)
    m_f = machine_health.machine_findings(ml)
    return {"machine_health": ml, "capacity": cap, "findings": m_f + cap["findings"],
            "has_sensors": bool(ml.get("machines")), "has_stations": not st.empty, "work_orders": int(len(wo))}


def plant(s: Session) -> dict:
    with _lock:
        fresh = _cache["version"] == _version and time.time() - _cache["at"] < TTL_S and _cache["value"] is not None
        if fresh:
            return _cache["value"]
        version = _version
    value = _compute(s)
    with _lock:
        _cache.update(version=version, at=time.time(), value=value)
    return value


def merge(production_analysis: dict | None, plant_data: dict) -> list[dict]:
    """All findings, production first, then plant-level."""
    prod = production_analysis["findings"] if production_analysis else []
    return prod + plant_data["findings"]
