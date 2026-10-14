"""Operational copilot: chat with Gemini grounded in plant data through function calling.

Gemini never sees a raw data dump. It must call tools that return the computed KPIs, findings,
anomalies, patterns, forecasts, ML machine-health scores, bottlenecks, ERP orders, inspections and
actions, and cite finding IDs. Every tool call is logged and returned so the manager can audit it.
The same tool set is used by the investigation agents (agents.py).
"""
from __future__ import annotations

from .ai import is_configured, make_client, model_name
from .evidence import ID_RE

SYSTEM = """You are SmartFactory Copilot, an operations assistant for a factory production manager.
Answer questions about the plant by calling the provided tools.
Evidence IDs: F = KPI threshold findings, A = statistical anomalies, P = short-term trend risk,
V = visual inspection defects, M = ML machine-failure predictions, B = bottleneck / capacity forecasts.
Rules:
- Always call tools to get numbers. Never invent data, machines, people or costs.
- Cite evidence IDs in square brackets when you use them, e.g. [F1] [M7].
- Clearly separate facts (measured), correlations, hypotheses and recommendations.
- P, M and B items are model estimates or projections, not certainties; say so when using them.
- If the data cannot answer the question, say what data would be needed.
- Be concise: short paragraphs or bullet points, under 200 words unless asked for more.
"""

MAX_TURNS = 12


class CopilotUnavailable(Exception):
    pass


def build_tools(analysis: dict | None, plant: dict, actions: list[dict], log: list[dict]):
    lines = sorted(set((analysis or {}).get("overall", {}).get("lines", []))
                   | {m["line"] for m in plant["machine_health"].get("machines", []) if m.get("line")}
                   | {l["line"] for l in plant["capacity"].get("lines", [])})
    findings = (analysis["findings"] if analysis else []) + plant["findings"]

    def _norm(line: str) -> str | None:
        if not line or line.lower() == "all":
            return None
        for l in lines:
            if l.lower().replace(" ", "") == line.lower().replace(" ", ""):
                return l
        return line

    def _need_prod() -> dict | None:
        return None if analysis else {"error": "No production dataset is loaded."}

    def get_plant_overview() -> dict:
        """Plant-wide KPIs for the loaded production period (target achievement %, output variance, defect rate %, downtime) and the list of lines."""
        log.append({"tool": "get_plant_overview", "args": {}})
        return _need_prod() or analysis["overall"]

    def get_line_summary(line: str) -> dict:
        """KPIs for one production line (e.g. 'Line 03') or 'all': achievement, variance, defect rate, downtime, top downtime reasons."""
        log.append({"tool": "get_line_summary", "args": {"line": line}})
        if not analysis:
            return _need_prod()
        l = _norm(line)
        rows = [s for s in analysis["by_line"] if l is None or s["line"] == l]
        return {"lines": rows} if rows else {"error": f"Unknown line {line}. Valid: {lines}"}

    def get_daily_series(line: str) -> dict:
        """Day-by-day KPIs for one line (or 'all' for plant totals). Use to see trends and when a change started."""
        log.append({"tool": "get_daily_series", "args": {"line": line}})
        if not analysis:
            return _need_prod()
        l = _norm(line)
        keep = ("date", "target_achievement_pct", "defect_rate_pct", "downtime_minutes", "output_variance")
        rows = analysis["by_date"] if l is None else [r for r in analysis["by_line_date"] if r["line"] == l]
        return {"line": l or "all", "days": [{k: r[k] for k in keep} for r in rows]}

    def get_findings(line: str) -> dict:
        """All evidence items (F, A, P, V, M, B) with IDs, severity and evidence text. Pass a line name or 'all'."""
        log.append({"tool": "get_findings", "args": {"line": line}})
        l = _norm(line)
        return {"findings": [{k: f[k] for k in ("id", "severity", "category", "line", "title", "evidence")}
                             for f in findings if l is None or f["line"] == l]}

    def get_patterns(line: str) -> dict:
        """Downtime Pareto (reasons, minutes, share), shift and product comparison. Pass a line or 'all'."""
        log.append({"tool": "get_patterns", "args": {"line": line}})
        if not analysis:
            return _need_prod()
        p = analysis["patterns"]
        l = _norm(line)
        if l is None:
            return {k: p[k] for k in ("downtime_pareto", "downtime_vital_few", "failure_type_minutes", "by_shift", "by_product", "by_weekday")}
        return {"downtime_pareto": p["downtime_pareto_by_line"].get(l, []),
                "by_shift": [r for r in p["by_line_shift"] if r["line"] == l]}

    def get_risk_forecast(line: str) -> dict:
        """Short-term (3-day) trend projection per line from production KPIs. Pass a line or 'all'."""
        log.append({"tool": "get_risk_forecast", "args": {"line": line}})
        if not analysis:
            return _need_prod()
        l = _norm(line)
        return {"method": "Least-squares linear trend over the last 7 days, projected 3 days ahead. Not a guarantee.",
                "forecasts": [f for f in analysis["forecasts"] if l is None or f["line"] == l]}

    def get_correlations() -> dict:
        """Per-line Pearson correlation between daily downtime and target achievement. Correlation is not causation."""
        log.append({"tool": "get_correlations", "args": {}})
        return _need_prod() or {"correlations": analysis["correlations"]}

    def get_machine_health(line: str) -> dict:
        """ML failure-risk prediction per machine from sensor data (probability of failure within the horizon, main sensor drivers) and model test metrics. Pass a line or 'all'."""
        log.append({"tool": "get_machine_health", "args": {"line": line}})
        mh = plant["machine_health"]
        l = _norm(line)
        keep = ("machine_id", "machine_code", "line", "machine_type", "failure_probability", "risk_level", "horizon_hours", "drivers", "last_values", "as_of")
        model = mh.get("model")
        return {"model": {k: model[k] for k in ("id", "algorithm", "horizon_hours", "threshold", "metrics")} if model else None,
                "finding_ids": {m["machine_code"]: f"M{m['machine_id']}" for m in mh.get("machines", [])},
                "machines": [{k: m.get(k) for k in keep} for m in mh.get("machines", []) if l is None or m["line"] == l]}

    def get_bottlenecks(line: str) -> dict:
        """Station-level constraint analysis and 7-day capacity forecast vs ERP demand per line. Pass a line or 'all'."""
        log.append({"tool": "get_bottlenecks", "args": {"line": line}})
        cap = plant["capacity"]
        l = _norm(line)
        keep = ("line", "constraint_station", "constraint_utilisation_pct", "constraint_wip", "capacity_per_day",
                "forecast_days", "projected_capacity", "demand", "shortfall", "shortfall_units", "shortfall_days")
        return {"forecast_from": cap.get("forecast_from"),
                "lines": [{k: r[k] for k in keep} for r in cap.get("lines", []) if l is None or r["line"] == l],
                "stations": [{k: r[k] for k in ("line", "station", "utilisation_pct", "capacity_per_day", "wip_units", "trend", "is_constraint")}
                             for r in cap.get("stations", []) if l is None or r["line"] == l]}

    def get_visual_inspections(line: str) -> dict:
        """Results of AI photo inspections of parts (defect type, severity, confidence). Pass a line or 'all'."""
        log.append({"tool": "get_visual_inspections", "args": {"line": line}})
        l = _norm(line)
        keep = ("seq", "line", "part", "defect_detected", "defect_type", "severity", "confidence", "description", "created_at")
        return {"inspections": [{k: i[k] for k in keep} for i in (analysis or {}).get("inspections", [])
                                if l is None or i["line"] == l]}

    def get_actions() -> dict:
        """Corrective actions with status (pending approval / approved / rejected / in_progress / completed), owner and notes."""
        log.append({"tool": "get_actions", "args": {}})
        keep = ("title", "owner_role", "finding_ids", "status", "priority", "note", "due_date")
        return {"actions": [{k: a.get(k) for k in keep} for a in actions]}

    return [get_plant_overview, get_line_summary, get_daily_series, get_findings, get_patterns, get_risk_forecast,
            get_correlations, get_machine_health, get_bottlenecks, get_visual_inspections, get_actions]


def valid_ids(analysis: dict | None, plant: dict) -> set[str]:
    return {f["id"] for f in ((analysis or {}).get("findings", []) + plant["findings"])}


def chat(analysis: dict | None, plant: dict, actions: list[dict], history: list[dict], message: str) -> dict:
    if not is_configured():
        raise CopilotUnavailable("The copilot needs Gemini. Set GEMINI_API_KEY in backend/.env (or Cloud Run env vars) and restart the backend. Check with: python -m app.check_gemini")
    from google import genai
    from google.genai import types

    log: list[dict] = []
    tools = build_tools(analysis, plant, actions, log)
    contents = [types.Content(role="model" if h["role"] == "model" else "user",
                              parts=[types.Part.from_text(text=h["text"])])
                for h in history[-MAX_TURNS:]]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))

    client = make_client()
    resp = client.models.generate_content(
        model=model_name(),
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=tools,
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=10),
        ),
    )
    text = resp.text or "I could not produce an answer from the available data."
    valid = valid_ids(analysis, plant)
    found = set(ID_RE.findall(text))
    key = lambda s: (s[0], int(s[1:]))  # noqa: E731
    return {"answer": text, "cited_ids": sorted(found & valid, key=key), "invalid_ids": sorted(found - valid, key=key),
            "tool_calls": log, "model": model_name()}
