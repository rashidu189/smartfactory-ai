"""Deterministic KPI calculations and rule-based findings.

Numbers are computed here, in code. The AI layer only explains them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class Thresholds:
    achievement_warning: float = 90.0   # % of target
    achievement_critical: float = 75.0
    defect_rate_warning: float = 3.0     # % of inspected
    defect_rate_critical: float = 5.0
    downtime_vs_baseline: float = 1.5    # x the plant-wide median daily downtime per line


def _pct(num: float, den: float) -> float | None:
    return round(num / den * 100, 2) if den else None


def summarise(df: pd.DataFrame) -> dict:
    target = df.loc[df["target_output"] > 0, "target_output"].sum()
    actual_for_target = df.loc[df["target_output"] > 0, "actual_output"].sum()
    inspected = df["inspected_units"].sum()
    defective = df["defective_units"].sum()
    return {
        "target_output": int(target),
        "actual_output": int(df["actual_output"].sum()),
        "target_achievement_pct": _pct(actual_for_target, target),
        "output_variance": int(actual_for_target - target),
        "inspected_units": int(inspected),
        "defective_units": int(defective),
        "defect_rate_pct": _pct(defective, inspected),
        "downtime_minutes": round(float(df["downtime_minutes"].sum()), 1),
        "records": int(len(df)),
    }


def overall(df: pd.DataFrame) -> dict:
    out = summarise(df)
    out["date_from"] = str(min(df["date"]))
    out["date_to"] = str(max(df["date"]))
    out["lines"] = sorted(df["line"].unique().tolist())
    out["days"] = int(df["date"].nunique())
    return out


def by_line(df: pd.DataFrame) -> list[dict]:
    rows = []
    for line, g in df.groupby("line", sort=True):
        s = summarise(g)
        s["line"] = line
        s["days"] = int(g["date"].nunique())
        s["avg_daily_downtime"] = round(float(g.groupby("date")["downtime_minutes"].sum().mean()), 1)
        reasons = (
            g.loc[g["downtime_reason"] != ""]
            .groupby("downtime_reason")["downtime_minutes"].sum()
            .sort_values(ascending=False)
        )
        s["top_downtime_reasons"] = [
            {"reason": r, "minutes": round(float(m), 1)} for r, m in reasons.head(3).items()
        ]
        rows.append(s)
    return rows


def by_date(df: pd.DataFrame) -> list[dict]:
    rows = []
    for date, g in df.groupby("date", sort=True):
        s = summarise(g)
        s["date"] = str(date)
        rows.append(s)
    return rows


def by_line_date(df: pd.DataFrame) -> list[dict]:
    rows = []
    for (line, date), g in df.groupby(["line", "date"], sort=True):
        s = summarise(g)
        s["line"] = line
        s["date"] = str(date)
        rows.append(s)
    return rows


def find_issues(df: pd.DataFrame, t: Thresholds) -> list[dict]:
    """Rule-based checks. Each finding carries the evidence that triggered it."""
    findings: list[dict] = []
    lines = by_line(df)
    daily = by_line_date(df)

    # Plant-wide baseline: median daily downtime per line-day.
    baseline = float(pd.Series([d["downtime_minutes"] for d in daily]).median() or 0)

    def add(severity, category, line, title, evidence, metric, value, threshold, date=None):
        findings.append({
            "id": "",
            "severity": severity,
            "category": category,
            "line": line,
            "date": date,
            "title": title,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "evidence": evidence,
        })

    for s in lines:
        line = s["line"]
        ach = s["target_achievement_pct"]
        if ach is not None and ach < t.achievement_warning:
            sev = "critical" if ach < t.achievement_critical else "warning"
            add(sev, "output", line,
                f"{line} achieved {ach}% of target",
                f"Actual {s['actual_output']:,} vs target {s['target_output']:,} "
                f"(variance {s['output_variance']:+,}) over {s['days']} day(s).",
                "target_achievement_pct", ach,
                t.achievement_critical if sev == "critical" else t.achievement_warning)
        dr = s["defect_rate_pct"]
        if dr is not None and dr > t.defect_rate_warning:
            sev = "critical" if dr > t.defect_rate_critical else "warning"
            add(sev, "quality", line,
                f"{line} defect rate {dr}%",
                f"{s['defective_units']:,} defective of {s['inspected_units']:,} inspected.",
                "defect_rate_pct", dr,
                t.defect_rate_critical if sev == "critical" else t.defect_rate_warning)
        if baseline and s["avg_daily_downtime"] > baseline * t.downtime_vs_baseline:
            reasons = ", ".join(f"{r['reason']} ({r['minutes']:.0f} min)" for r in s["top_downtime_reasons"]) or "no reasons recorded"
            add("warning", "downtime", line,
                f"{line} downtime {s['avg_daily_downtime']:.0f} min/day vs {baseline:.0f} baseline",
                f"Total {s['downtime_minutes']:.0f} min. Top recorded reasons: {reasons}.",
                "avg_daily_downtime", s["avg_daily_downtime"], round(baseline * t.downtime_vs_baseline, 1))

    # Individual line-days that are far outside normal, even if the line average looks fine.
    low_days: dict[str, list[dict]] = {}
    for d in daily:
        ach = d["target_achievement_pct"]
        if ach is not None and ach < t.achievement_critical:
            low_days.setdefault(d["line"], []).append(d)
    for line, days in low_days.items():
        total_days = sum(1 for d in daily if d["line"] == line)
        worst = min(days, key=lambda d: d["target_achievement_pct"])
        first, last = days[0]["date"], days[-1]["date"]
        span = first if first == last else f"{first} to {last}"
        add("critical" if len(days) >= 3 else "warning", "output", line,
            f"{line} below {t.achievement_critical:.0f}% of target on {len(days)} of {total_days} days",
            f"Low days: {span}; worst {worst['target_achievement_pct']}% on {worst['date']} "
            f"(actual {worst['actual_output']:,} vs target {worst['target_output']:,}).",
            "low_achievement_days", len(days), t.achievement_critical, date=span)

    order = {"critical": 0, "warning": 1}
    findings.sort(key=lambda f: (order[f["severity"]], f["line"], f["date"] or ""))
    for i, f in enumerate(findings, start=1):
        f["id"] = f"F{i}"
    return findings


def correlations(df: pd.DataFrame) -> list[dict]:
    """Simple per-line correlations across line-days. Reported as correlation, never causation."""
    daily = pd.DataFrame(by_line_date(df))
    out = []
    for line, g in daily.groupby("line"):
        if len(g) < 5:
            continue
        g = g.dropna(subset=["target_achievement_pct"])
        if g["downtime_minutes"].std() == 0 or g["target_achievement_pct"].std() == 0:
            continue
        r = g["downtime_minutes"].corr(g["target_achievement_pct"])
        out.append({"line": line, "pair": "downtime_minutes vs target_achievement_pct",
                    "pearson_r": round(float(r), 2), "n_days": int(len(g))})
    return out


def analyse(df: pd.DataFrame, thresholds: Thresholds | None = None) -> dict:
    t = thresholds or Thresholds()
    return {
        "overall": overall(df),
        "by_line": by_line(df),
        "by_date": by_date(df),
        "by_line_date": by_line_date(df),
        "findings": find_issues(df, t),
        "correlations": correlations(df),
        "thresholds": asdict(t),
    }
