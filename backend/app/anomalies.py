"""Statistical anomaly detection on actual metrics (findings A1, A2 …).

Three robust detectors, all on line-day values:
  1. Peer anomaly  – a line is far from the other lines on the same day.
  2. Sudden change – a line is far from its own trailing 7-day baseline (onset detection).
  3. Shift gap     – one shift performs consistently worse than the others on the same line.

"Robust z" = 0.6745 * (x - median) / MAD (Iglewicz & Hoaglin); |z| > 3.5 is flagged.
Only the harmful direction is flagged (low achievement, high defects, high downtime).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .kpis import by_line_date, summarise

Z = 3.5
TRAIL = 7
METRICS = {
    # metric: (direction of harm, MAD floor, label, unit)
    "target_achievement_pct": (-1, 1.5, "target achievement", "%"),
    "defect_rate_pct": (+1, 0.25, "defect rate", "%"),
    "downtime_minutes": (+1, 8.0, "downtime", " min"),
}


def _robust_z(x: float, med: float, mad: float, floor: float) -> float:
    return 0.6745 * (x - med) / max(mad, floor)


def _group_days(days: list[str]) -> str:
    return days[0] if len(days) == 1 else f"{days[0]} → {days[-1]}"


def detect(df: pd.DataFrame) -> list[dict]:
    daily = pd.DataFrame(by_line_date(df))
    if daily.empty or daily["line"].nunique() < 1:
        return []
    out: list[dict] = []
    n_lines = daily["line"].nunique()

    for metric, (sign, floor, label, unit) in METRICS.items():
        piv = daily.pivot(index="date", columns="line", values=metric).sort_index()

        # 1. Peer anomaly (needs >= 3 lines)
        if n_lines >= 3:
            hits: dict[str, list[tuple[str, float, float, float]]] = {}
            resid = []
            for date, row in piv.iterrows():
                for line, x in row.dropna().items():
                    peers = row.drop(line).dropna()
                    if len(peers) >= 2:
                        resid.append(abs(x - peers.median()))
            pooled_mad = float(np.median(resid)) if resid else 0.0
            for date, row in piv.iterrows():
                for line, x in row.dropna().items():
                    peers = row.drop(line).dropna()
                    if len(peers) < 2:
                        continue
                    med = float(peers.median())
                    z = _robust_z(x, med, pooled_mad, floor)
                    if sign * z > Z:
                        hits.setdefault(line, []).append((date, x, med, z))
            for line, h in hits.items():
                days = [d for d, *_ in h]
                zmax = max(abs(z) for *_, z in h)
                avg_x = np.mean([x for _, x, _, _ in h])
                avg_m = np.mean([m for _, _, m, _ in h])
                rel = (f"{avg_x / avg_m:.1f}× the other lines" if metric == "downtime_minutes" and avg_m > 0
                       else f"{avg_x - avg_m:+.1f}{'pp' if unit == '%' else unit} vs the other lines")
                out.append(_finding("peer", line, metric, label, days, zmax,
                                    f"{line} {label} unusual vs peers on {len(days)} of {len(piv)} days",
                                    f"On {_group_days(days)} the {label} averaged {avg_x:.1f}{unit} vs a peer median of "
                                    f"{avg_m:.1f}{unit} ({rel}); max robust z = {zmax:.1f} (threshold {Z}).",
                                    len(piv)))

        # 2. Sudden change vs the line's own trailing baseline
        for line in piv.columns:
            s = piv[line].dropna()
            h = []
            for i in range(3, len(s)):
                window = s.iloc[max(0, i - TRAIL):i]
                med = float(window.median())
                mad = float((window - med).abs().median())
                z = _robust_z(float(s.iloc[i]), med, mad, floor)
                if sign * z > Z:
                    h.append((s.index[i], float(s.iloc[i]), med, z))
            if h:
                # Report the onset (first flagged day) — that is where an investigation should start.
                first = h[0]
                days = [d for d, *_ in h]
                out.append(_finding("change", line, metric, label, days, max(abs(z) for *_, z in h),
                                    f"{line} {label} changed suddenly from {first[0]}",
                                    f"{label.capitalize()} moved from a trailing {TRAIL}-day median of {first[2]:.1f}{unit} "
                                    f"to {first[1]:.1f}{unit} on {first[0]} (robust z = {first[3]:.1f}); "
                                    f"{len(days)} day(s) flagged in total ({_group_days(days)}).",
                                    len(s)))

    # 3. Shift gap per line
    if "shift" in df.columns and (df["shift"] != "").any():
        for line, g in df[df["shift"] != ""].groupby("line"):
            shifts = {sh: summarise(sg) for sh, sg in g.groupby("shift")}
            if len(shifts) < 2:
                continue
            ach = {k: v["target_achievement_pct"] for k, v in shifts.items() if v["target_achievement_pct"] is not None}
            dr = {k: v["defect_rate_pct"] for k, v in shifts.items() if v["defect_rate_pct"] is not None}
            if ach and max(ach.values()) - min(ach.values()) >= 5:
                worst, best = min(ach, key=ach.get), max(ach, key=ach.get)
                out.append(_finding("shift", line, "target_achievement_pct", "target achievement", [], 0,
                                    f"{line}: shift {worst} achieves {ach[best] - ach[worst]:.1f}pp less than shift {best}",
                                    f"Target achievement by shift: " + ", ".join(f"{k} {v:.1f}%" for k, v in sorted(ach.items())) + ".",
                                    0, severity="warning"))
            if dr and min(dr.values()) > 0 and max(dr.values()) / min(dr.values()) >= 1.5 and max(dr.values()) > 1.0:
                worst, best = max(dr, key=dr.get), min(dr, key=dr.get)
                out.append(_finding("shift", line, "defect_rate_pct", "defect rate", [], 0,
                                    f"{line}: shift {worst} defect rate is {dr[worst] / dr[best]:.1f}× shift {best}",
                                    f"Defect rate by shift: " + ", ".join(f"{k} {v:.2f}%" for k, v in sorted(dr.items())) + ".",
                                    0, severity="warning"))

    order = {"critical": 0, "warning": 1}
    out.sort(key=lambda f: (order[f["severity"]], f["line"], f["metric"], f["detector"]))
    for i, f in enumerate(out, start=1):
        f["id"] = f"A{i}"
    return out


def _finding(detector, line, metric, label, days, zmax, title, evidence, total_days, severity=None):
    if severity is None:
        severity = "critical" if (zmax >= 7 or len(days) >= 3) else "warning"
    return {
        "id": "", "severity": severity, "category": "anomaly", "detector": detector,
        "line": line, "date": _group_days(days) if days else None, "metric": metric,
        "value": round(float(zmax), 1), "threshold": Z,
        "title": title, "evidence": evidence,
    }
