"""Builds the full production analysis for a dataset:
KPIs + rule findings (F) + statistical anomalies (A) + trend risk (P) + visual defects (V) + patterns."""
from __future__ import annotations

import pandas as pd

from . import anomalies, forecast, kpis, patterns, vision

COLUMNS = ["date", "line", "shift", "product", "target_output", "actual_output", "inspected_units",
           "defective_units", "downtime_minutes", "downtime_reason"]


def records_to_df(records) -> pd.DataFrame:
    return pd.DataFrame([{c: getattr(r, c) for c in COLUMNS} for r in records], columns=COLUMNS)


def build(df: pd.DataFrame, inspections: list[dict] | None = None,
          thresholds: kpis.Thresholds | None = None) -> dict:
    t = thresholds or kpis.Thresholds()
    a = kpis.analyse(df, t)
    a["forecasts"] = forecast.line_forecasts(df, t)
    a["inspections"] = inspections or []
    a["patterns"] = patterns.analyse(df)
    a["findings"] = (a["findings"] + anomalies.detect(df) + forecast.risk_findings(a["forecasts"])
                     + vision.visual_findings(a["inspections"]))
    a["finding_counts"] = {k: sum(f["id"].startswith(p) for f in a["findings"])
                           for k, p in (("kpi", "F"), ("anomaly", "A"), ("risk", "P"), ("visual", "V"))}
    return a
