"""Gemini integration.

Gemini receives only the validated KPIs and rule-based findings, and must cite
finding IDs for every statement. Citations are checked after the response; any
item that cites no real finding is dropped.

Configuration (environment variables, read by the google-genai SDK):
  Gemini API:  GEMINI_API_KEY=...
  Vertex AI:   GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT=..., GOOGLE_CLOUD_LOCATION=...
  Model:       GEMINI_MODEL (default gemini-2.5-flash)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger("smartfactory.ai")

DEFAULT_MODEL = "gemini-2.5-flash"
# Default to Vertex AI when running on Google Cloud with a project set and no API key.
if (os.getenv("GOOGLE_CLOUD_PROJECT") and not os.getenv("GEMINI_API_KEY")
        and not os.getenv("GOOGLE_API_KEY") and "GOOGLE_GENAI_USE_VERTEXAI" not in os.environ):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"


class Insight(BaseModel):
    statement: str
    kind: Literal["fact", "correlation", "hypothesis"]
    confidence: Literal["low", "medium", "high"]
    finding_ids: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    title: str
    rationale: str
    priority: Literal["high", "medium", "low"]
    owner_role: str
    finding_ids: list[str] = Field(default_factory=list)
    verify_by: str = Field(description="What data or check would confirm this action worked")


class AIReport(BaseModel):
    summary: str
    insights: list[Insight]
    recommendations: list[Recommendation]
    data_gaps: list[str]


SYSTEM_PROMPT = """You are SmartFactory AI, an assistant for a factory production manager.
You receive production KPIs that were calculated in code and a list of findings, each with an ID:
F = rule-based KPI findings, A = statistical anomalies, P = short-term trend risk (projections),
V = AI visual inspection of part photos, M = ML machine-failure predictions from sensor data (model estimates),
B = bottleneck / capacity forecasts against ERP demand (projections). Your job is to explain them and suggest practical next steps.

Strict rules:
- Use ONLY the numbers and facts in the input. Never invent machines, people, causes, costs or data.
- Every insight and recommendation must cite at least one finding ID from the input in finding_ids.
- Label each insight: "fact" (directly measured), "correlation" (two metrics move together),
  or "hypothesis" (a possible explanation that needs checking). Do not state a cause as a fact
  unless the data directly records it (e.g. a recorded downtime reason).
- Correlations in the input are Pearson r across line-days; they do not prove causation.
- Treat P, M and B findings as early warnings: recommend preventive checks, and say they are projections.
- Prefer a small number of high-value recommendations (3-6). Name an owner role, not a person.
- In data_gaps, list information that would be needed to confirm hypotheses.
- Keep language plain and concise. The summary is at most 3 sentences.
"""


def is_configured() -> bool:
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes"):
        return True
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def build_payload(analysis: dict, question: str | None = None) -> dict:
    """Compact, evidence-only context for the model."""
    lines = [
        {k: s[k] for k in ("line", "target_achievement_pct", "output_variance", "defect_rate_pct",
                           "downtime_minutes", "avg_daily_downtime", "top_downtime_reasons", "days")}
        for s in analysis["by_line"]
    ]
    return {
        "period": {k: analysis["overall"][k] for k in ("date_from", "date_to", "days")},
        "plant_totals": {k: analysis["overall"][k] for k in (
            "target_achievement_pct", "output_variance", "defect_rate_pct", "downtime_minutes")},
        "thresholds": analysis["thresholds"],
        "lines": lines,
        "findings": [
            {k: f[k] for k in ("id", "severity", "category", "line", "date", "title", "evidence")}
            for f in analysis["findings"]
        ],
        "correlations": analysis["correlations"],
        "risk_forecasts": [
            {k: f.get(k) for k in ("line", "risk_level", "risk_score", "drivers", "metrics",
                                    "failure_events_recent", "failure_events_before")}
            for f in analysis.get("forecasts", []) if f.get("status") == "ok"
        ],
        "plant_summary": analysis.get("plant_summary"),
        "downtime_pareto_top": analysis.get("patterns", {}).get("downtime_pareto", [])[:5],
        "manager_question": question or None,
    }


def _check_citations(report: AIReport, valid_ids: set[str]) -> tuple[AIReport, int]:
    dropped = 0

    def clean(items):
        nonlocal dropped
        kept = []
        for it in items:
            it.finding_ids = [i for i in it.finding_ids if i in valid_ids]
            if it.finding_ids:
                kept.append(it)
            else:
                dropped += 1
        return kept

    report.insights = clean(report.insights)
    report.recommendations = clean(report.recommendations)
    return report, dropped


def generate(analysis: dict, question: str | None = None) -> dict:
    valid_ids = {f["id"] for f in analysis["findings"]}
    if not analysis["findings"]:
        return {
            "source": "rules",
            "model": None,
            "note": "No findings breached the configured thresholds, so there is nothing to explain.",
            "report": AIReport(summary="All lines are within the configured thresholds for this period.",
                               insights=[], recommendations=[], data_gaps=[]).model_dump(),
        }

    if not is_configured():
        return {
            "source": "rules",
            "model": None,
            "note": "Gemini is not configured (set GEMINI_API_KEY or Vertex AI variables). "
                    "Showing a rule-based summary instead.",
            "report": fallback_report(analysis).model_dump(),
        }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        payload = build_payload(analysis, question)
        resp = client.models.generate_content(
            model=model_name(),
            contents="Production data (JSON):\n" + json.dumps(payload, default=str),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=AIReport,
                temperature=0.2,
            ),
        )
        report = resp.parsed if isinstance(resp.parsed, AIReport) else AIReport.model_validate_json(resp.text)
        report, dropped = _check_citations(report, valid_ids)
        note = f"{dropped} item(s) removed because they did not cite valid evidence." if dropped else None
        return {"source": "gemini", "model": model_name(), "note": note, "report": report.model_dump()}
    except Exception as exc:  # noqa: BLE001 - never crash the request on an AI failure
        log.exception("Gemini call failed")
        return {
            "source": "rules",
            "model": None,
            "note": f"Gemini request failed ({type(exc).__name__}). Showing a rule-based summary instead.",
            "report": fallback_report(analysis).model_dump(),
        }


def fallback_report(analysis: dict) -> AIReport:
    """Deterministic, template-based report used when Gemini is unavailable."""
    f = analysis["findings"]
    crit = [x for x in f if x["severity"] == "critical"]
    insights: list[Insight] = []
    recs: list[Recommendation] = []

    for x in f[:10]:
        kind, conf = {"risk": ("hypothesis", "medium"), "visual": ("fact", "medium"), "machine": ("hypothesis", "medium"),
                      "bottleneck": ("hypothesis", "medium")}.get(x["category"], ("fact", "high"))
        insights.append(Insight(statement=f"{x['title']}. {x['evidence']}", kind=kind,
                                confidence=conf, finding_ids=[x["id"]]))

    by_line: dict[str, list[dict]] = {}
    for x in f:
        by_line.setdefault(x["line"], []).append(x)

    for c in analysis["correlations"]:
        related = [x for x in by_line.get(c["line"], []) if x["category"] in ("output", "downtime")]
        if c["pearson_r"] <= -0.5 and related:
            insights.append(Insight(
                statement=f"On {c['line']}, days with more downtime tended to have lower target achievement "
                          f"(r = {c['pearson_r']}, {c['n_days']} days). This is a correlation, not proof of cause.",
                kind="correlation", confidence="medium",
                finding_ids=[x["id"] for x in related]))

    templates = {
        "output": ("Review the production plan and losses on {line}",
                   "Output is below target; confirm whether the gap is from downtime, speed loss or planning.",
                   "Production supervisor", "Daily target achievement back above the warning threshold"),
        "quality": ("Run a quality containment check on {line}",
                    "Defect rate is above threshold; isolate affected batches and check top defect types.",
                    "Quality engineer", "Defect rate below threshold for 5 consecutive days"),
        "downtime": ("Investigate the main downtime reasons on {line}",
                     "Downtime is above the plant baseline; review the top recorded reasons with maintenance.",
                     "Maintenance lead", "Average daily downtime back under the baseline"),
        "risk": ("Schedule a preventive check on {line} before the projected decline",
                 "Trend projection flags rising risk; inspect the equipment behind recent failure-type stops.",
                 "Maintenance lead", "Next 3 days of KPIs stay inside thresholds"),
        "anomaly": ("Investigate the unusual pattern on {line} from its onset date",
                    "Statistical anomaly detected; compare shift logs, materials and changes around the onset date.",
                    "Production supervisor", "Metric returns to its normal range vs peers"),
        "machine": ("Raise a preventive maintenance work order for the flagged machine on {line}",
                    "ML model predicts elevated failure risk; inspect the drifting sensors before a breakdown.",
                    "Maintenance lead", "Failure probability drops below the alert threshold after maintenance"),
        "bottleneck": ("Add capacity or re-plan orders at the constraint station on {line}",
                       "Projected constraint capacity is below ERP demand; consider overtime, offloading or re-sequencing.",
                       "Production planner", "Projected shortfall reaches zero in the next forecast"),
        "visual": ("Quarantine and re-inspect the affected batch on {line}",
                   "Photo inspection found a visible defect; confirm extent with a manual inspection.",
                   "Quality engineer", "Follow-up photos and manual checks show no repeat defect"),
    }
    seen = set()
    for x in f:
        key = (x["line"], x["category"])
        if key in seen:
            continue
        seen.add(key)
        title, why, owner, verify = templates[x["category"]]
        recs.append(Recommendation(title=title.format(line=x["line"]), rationale=why,
                                   priority="high" if x["severity"] == "critical" else "medium",
                                   owner_role=owner, finding_ids=[x["id"]], verify_by=verify))

    lines_hit = sorted(by_line)
    summary = (f"{len(f)} finding(s) across {len(lines_hit)} line(s) ({', '.join(lines_hit)}); "
               f"{len(crit)} critical. Rule-based summary: causes are not inferred.")
    return AIReport(summary=summary, insights=insights, recommendations=recs[:8],
                    data_gaps=["Shift-level operator and changeover logs",
                               "Defect type / Pareto data per line",
                               "Planned vs unplanned downtime split"])
