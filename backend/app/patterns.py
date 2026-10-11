"""Quality-defect and downtime pattern analysis (Pareto, shift, product, weekday) and period comparison."""
from __future__ import annotations

import pandas as pd

from .forecast import FAILURE_PATTERN
from .kpis import summarise


def _pareto(g: pd.DataFrame) -> list[dict]:
    g = g[g["downtime_reason"].fillna("") != ""]
    total = float(g["downtime_minutes"].sum())
    if not total:
        return []
    s = g.groupby("downtime_reason")["downtime_minutes"].agg(["sum", "count"]).sort_values("sum", ascending=False)
    cum = 0.0
    rows = []
    for reason, r in s.iterrows():
        cum += float(r["sum"])
        rows.append({"reason": reason, "minutes": round(float(r["sum"]), 1), "events": int(r["count"]),
                     "share_pct": round(float(r["sum"]) / total * 100, 1), "cumulative_pct": round(cum / total * 100, 1),
                     "failure_type": bool(FAILURE_PATTERN.search(reason))})
    return rows


def _group_kpis(df: pd.DataFrame, col: str) -> list[dict]:
    if col not in df.columns or not (df[col] != "").any():
        return []
    out = []
    for key, g in df[df[col] != ""].groupby(col):
        s = summarise(g)
        s[col] = key
        s["days"] = int(g["date"].nunique())
        out.append(s)
    return out


def analyse(df: pd.DataFrame) -> dict:
    d = df.copy()
    d["weekday"] = pd.to_datetime(d["date"]).dt.day_name()
    weekday = _group_kpis(d, "weekday")
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday.sort(key=lambda r: order.index(r["weekday"]))
    pareto = _pareto(d)
    vital = [r["reason"] for r in pareto if r["cumulative_pct"] <= 80] or [r["reason"] for r in pareto[:1]]
    return {
        "downtime_pareto": pareto,
        "downtime_vital_few": vital,
        "downtime_pareto_by_line": {line: _pareto(g)[:5] for line, g in d.groupby("line")},
        "failure_type_minutes": round(float(d.loc[d["downtime_reason"].fillna("").str.contains(FAILURE_PATTERN), "downtime_minutes"].sum()), 1),
        "by_shift": _group_kpis(d, "shift"),
        "by_line_shift": [{**summarise(g), "line": l, "shift": s} for (l, s), g in d[d["shift"] != ""].groupby(["line", "shift"])] if (d["shift"] != "").any() else [],
        "by_product": _group_kpis(d, "product"),
        "by_weekday": weekday,
    }


def compare(base: dict, current: dict, base_name: str, current_name: str) -> dict:
    """Compare two analyses (e.g. before and after corrective actions)."""
    def per_day(s):
        return round(s["downtime_minutes"] / s["days"], 1) if s.get("days") else None

    b = {s["line"]: s for s in base["by_line"]}
    c = {s["line"]: s for s in current["by_line"]}
    rows = []
    for line in sorted(set(b) | set(c)):
        x, y = b.get(line), c.get(line)
        row = {"line": line, "in_base": x is not None, "in_current": y is not None}
        if x and y:
            # (metric, +1 if higher is better, minimum change that counts as a real difference)
            for k, better, tol in (("target_achievement_pct", 1, 1.0), ("defect_rate_pct", -1, 0.25)):
                if x[k] is not None and y[k] is not None:
                    delta = round(float(y[k] - x[k]), 2)
                    row[k] = {"base": x[k], "current": y[k], "delta": delta,
                              "trend": "improved" if delta * better > tol else "worse" if delta * better < -tol else "same"}
            bd, cd = per_day(x), per_day(y)
            delta = round(cd - bd, 1)
            row["downtime_per_day"] = {"base": bd, "current": cd, "delta": delta,
                                       "trend": "improved" if delta < -5 else "worse" if delta > 5 else "same"}
        rows.append(row)
    ob, oc = base["overall"], current["overall"]
    return {
        "base": {"name": base_name, "from": ob["date_from"], "to": ob["date_to"]},
        "current": {"name": current_name, "from": oc["date_from"], "to": oc["date_to"]},
        "plant": {k: {"base": ob[k], "current": oc[k], "delta": round((oc[k] or 0) - (ob[k] or 0), 2)}
                  for k in ("target_achievement_pct", "defect_rate_pct", "downtime_minutes")},
        "lines": rows,
    }
