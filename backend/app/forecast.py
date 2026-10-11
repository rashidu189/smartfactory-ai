"""Predictive risk: short-horizon statistical projection per line.

Method (deliberately simple and explainable):
  * Build the daily series per line (target achievement %, defect rate %, downtime min).
  * Fit a least-squares linear trend over the most recent WINDOW days.
  * Project HORIZON days ahead; compare the projection with the thresholds.
  * Count failure-type downtime events (predictive-maintenance signal) recently vs earlier.
This is a statistical projection, not a guarantee, and is labelled as such everywhere.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .kpis import Thresholds, by_line_date

WINDOW = 7
HORIZON = 3
FAILURE_PATTERN = re.compile(r"fail|breakdown|fault|mechanical|electrical|jam|leak|overheat", re.I)


def _trend(values: list[float]) -> tuple[float, float]:
    """Return (slope per day, projected value HORIZON days after the last point)."""
    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    if len(y) < 2 or np.allclose(y, y[0]):
        return 0.0, float(y[-1])
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept + slope * (len(y) - 1 + HORIZON))


def line_forecasts(df: pd.DataFrame, t: Thresholds) -> list[dict]:
    daily = pd.DataFrame(by_line_date(df))
    if daily.empty:
        return []
    baseline = float(daily["downtime_minutes"].median() or 0)
    df = df.copy()
    df["is_failure"] = df["downtime_reason"].fillna("").str.contains(FAILURE_PATTERN)
    out = []
    for line, g in daily.groupby("line", sort=True):
        g = g.sort_values("date")
        if len(g) < 5:
            out.append({"line": line, "status": "insufficient_data", "days": int(len(g))})
            continue
        recent = g.tail(WINDOW)
        res = {"line": line, "status": "ok", "window_days": int(len(recent)), "horizon_days": HORIZON,
               "from": recent["date"].iloc[0], "to": recent["date"].iloc[-1], "metrics": {}}
        for m in ("target_achievement_pct", "defect_rate_pct", "downtime_minutes"):
            vals = recent[m].dropna().tolist()
            if len(vals) < 2:
                continue
            slope, proj = _trend(vals)
            if m != "downtime_minutes":
                proj = max(0.0, min(proj, 100.0 if m == "defect_rate_pct" else 200.0))
            else:
                proj = max(0.0, proj)
            res["metrics"][m] = {"recent_avg": round(float(np.mean(vals)), 2),
                                 "slope_per_day": round(slope, 2), "projected": round(proj, 2)}

        lg = df[df["line"] == line]
        dates = sorted(lg["date"].unique())
        cut = dates[-WINDOW] if len(dates) > WINDOW else dates[0]
        rec_fail = lg[(lg["date"] >= cut) & lg["is_failure"]]
        prev_fail = lg[(lg["date"] < cut) & lg["is_failure"]]
        res["failure_events_recent"] = int(len(rec_fail))
        res["failure_events_before"] = int(len(prev_fail))
        res["failure_minutes_recent"] = round(float(rec_fail["downtime_minutes"].sum()), 1)
        res["failure_reasons"] = sorted(rec_fail["downtime_reason"].unique().tolist())[:3]

        # Risk scoring: each signal adds points, explained in `drivers`.
        score, drivers = 0, []
        ach = res["metrics"].get("target_achievement_pct")
        if ach:
            if ach["projected"] < t.achievement_critical:
                score += 3
                drivers.append(f"achievement projected {ach['projected']:.0f}% (< {t.achievement_critical:.0f}%)")
            elif ach["projected"] < t.achievement_warning:
                score += 1
                drivers.append(f"achievement projected {ach['projected']:.0f}% (< {t.achievement_warning:.0f}%)")
        dr = res["metrics"].get("defect_rate_pct")
        if dr:
            if dr["projected"] > t.defect_rate_critical:
                score += 3
                drivers.append(f"defect rate projected {dr['projected']:.1f}% (> {t.defect_rate_critical:.0f}%)")
            elif dr["projected"] > t.defect_rate_warning:
                score += 2
                drivers.append(f"defect rate projected {dr['projected']:.1f}% (> {t.defect_rate_warning:.0f}%)")
        dt = res["metrics"].get("downtime_minutes")
        if dt and baseline and dt["projected"] > baseline * t.downtime_vs_baseline:
            score += 2
            drivers.append(f"downtime projected {dt['projected']:.0f} min/day (baseline {baseline:.0f})")
        if res["failure_events_recent"] >= 3 and res["failure_events_recent"] > res["failure_events_before"]:
            score += 2
            drivers.append(f"{res['failure_events_recent']} failure-type stops in last {len(recent)} days "
                           f"vs {res['failure_events_before']} before")
        res["risk_score"] = score
        res["risk_level"] = "high" if score >= 4 else "medium" if score >= 2 else "low"
        res["drivers"] = drivers
        out.append(res)
    return out


def risk_findings(forecasts: list[dict]) -> list[dict]:
    """Convert medium/high risks to findings (IDs P1, P2 …) so AI can cite them."""
    items = [f for f in forecasts if f.get("status") == "ok" and f["risk_level"] in ("high", "medium")]
    items.sort(key=lambda f: (-f["risk_score"], f["line"]))
    findings = []
    for i, f in enumerate(items, start=1):
        maint = ""
        if f["failure_events_recent"]:
            maint = (f" Failure-type stops: {f['failure_events_recent']} recently "
                     f"({f['failure_minutes_recent']:.0f} min; {', '.join(f['failure_reasons'])}).")
        findings.append({
            "id": f"P{i}",
            "severity": "critical" if f["risk_level"] == "high" else "warning",
            "category": "risk",
            "line": f["line"],
            "date": f"next {f['horizon_days']} days",
            "title": f"{f['line']}: {f['risk_level']} risk over the next {f['horizon_days']} days",
            "metric": "risk_score",
            "value": f["risk_score"],
            "threshold": 2,
            "evidence": f"Linear trend over {f['window_days']} days ({f['from']} to {f['to']}): "
                        + "; ".join(f["drivers"]) + "." + maint + " Statistical projection, not a guarantee.",
        })
    return findings
