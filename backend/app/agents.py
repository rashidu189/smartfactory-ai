"""AI agents that investigate an issue, plan corrective actions and route them for human approval.

Workflow for one evidence item (F/A/P/V/M/B):
  1. Investigator agent  – Gemini + data tools (same tools as the copilot) gathers related evidence
                           and proposes root-cause hypotheses, each citing evidence IDs.
  2. Planner agent       – Gemini turns the investigation into a prioritised corrective-action plan
                           (action type, owner role, due date, expected effect, how to verify).
  3. Coordinator         – deterministic code: checks citations, applies the approval policy, creates
                           the actions (status 'pending') and writes the audit log. Agents never approve.
  4. Humans approve      – Supervisor (level 1) and, where policy requires, Plant manager (level 2).
  5. Verifier            – after work is done, compares the evidence then vs now and records the result.

Without Gemini, steps 1–2 use transparent rule-based logic (mode = "rules"), so the workflow still runs.

Approval policy (Coordinator):
  * production_change                      -> Supervisor + Plant manager (affects schedule / customers)
  * maintenance_work_order, priority high  -> Supervisor + Plant manager (equipment must stop)
  * everything else                        -> Supervisor
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import copilot, db
from .ai import is_configured, model_name

log = logging.getLogger("smartfactory.agents")

ActionType = Literal["corrective", "maintenance_work_order", "quality_containment", "production_change"]
ROLES = {"operator": 0, "engineer": 0, "supervisor": 1, "plant_manager": 2}
ROLE_LABEL = {"operator": "Operator", "engineer": "Engineer", "supervisor": "Supervisor", "plant_manager": "Plant manager"}


class Hypothesis(BaseModel):
    statement: str
    kind: Literal["fact", "correlation", "hypothesis"]
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(default_factory=list)
    how_to_verify: str = ""


class Investigation(BaseModel):
    summary: str
    hypotheses: list[Hypothesis]
    related_evidence_ids: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    title: str
    action_type: ActionType
    owner_role: str
    priority: Literal["high", "medium", "low"]
    due_in_days: int = Field(ge=0, le=30)
    evidence_ids: list[str] = Field(default_factory=list)
    expected_effect: str
    verification: str


class Plan(BaseModel):
    objective: str
    steps: list[PlanStep]


INVESTIGATOR_SYSTEM = copilot.SYSTEM + """
You are now acting as the INVESTIGATOR agent. You are given one evidence item to investigate.
Use the tools to look for related evidence on the same line and plant-wide (KPIs, anomalies, downtime
Pareto, shifts, machine health, bottlenecks, inspections). Write investigation notes: what is measured,
what correlates, and 2-4 root-cause hypotheses ranked by plausibility, each with the evidence IDs that
support it and how to verify it. Do not recommend actions yet."""

STRUCTURE_PROMPT = """Convert these investigation notes into the JSON schema. Keep only evidence IDs from this list:
{ids}. Every hypothesis must cite at least one ID. Notes:
{notes}"""

PLANNER_SYSTEM = """You are the PLANNER agent for a factory. Turn the investigation into a prioritised corrective-action
plan of 2-5 steps. Each step: a concrete action, action_type (corrective | maintenance_work_order |
quality_containment | production_change), an owner ROLE (not a person), priority, due_in_days, the evidence IDs
it addresses (only from the investigation), the expected effect stated cautiously, and how to verify it with data.
Order steps by priority. Contain risks first (safety/quality), then fix causes, then prevent recurrence.
Do not invent data, costs or names."""


# ---------------- helpers ----------------

def _all_findings(analysis: dict | None, plant: dict) -> list[dict]:
    return ((analysis or {}).get("findings", []) + plant["findings"])


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def audit(s: Session, actor: str, role: str, event: str, entity: str, entity_id: str, detail: str = "") -> None:
    s.add(db.AuditLog(actor=actor[:100], actor_role=role[:30], event=event, entity=entity, entity_id=entity_id, detail=detail[:1000]))


# ---------------- rule-based agents (no Gemini) ----------------

def _rules_investigate(root: dict, analysis: dict | None, plant: dict) -> Investigation:
    fs = _all_findings(analysis, plant)
    same_line = [f for f in fs if f["line"] == root["line"] and f["id"] != root["id"]]
    hyps: list[Hypothesis] = [Hypothesis(statement=f"{root['title']}. {root['evidence']}", kind="fact" if root["category"] not in ("risk", "machine", "bottleneck") else "hypothesis",
                                         confidence="high" if root["category"] not in ("risk", "machine", "bottleneck") else "medium",
                                         evidence_ids=[root["id"]], how_to_verify="Re-check the metric in the next data period.")]
    cats = {f["category"] for f in same_line}
    ids_of = lambda *c: [f["id"] for f in same_line if f["category"] in c][:3]  # noqa: E731
    if analysis:
        corr = next((c for c in analysis["correlations"] if c["line"] == root["line"]), None)
        down_ids = ids_of("downtime", "anomaly")
        if corr and corr["pearson_r"] <= -0.5 and (down_ids or root["category"] in ("downtime", "output", "anomaly")):
            hyps.append(Hypothesis(statement=f"On {root['line']}, days with more downtime had lower target achievement "
                                             f"(r = {corr['pearson_r']}, {corr['n_days']} days): downtime is a likely driver of lost output.",
                                   kind="correlation", confidence="medium", evidence_ids=[root["id"], *down_ids][:4],
                                   how_to_verify="Check whether output recovers on days without the top downtime reason."))
        par = analysis["patterns"]["downtime_pareto_by_line"].get(root["line"], [])
        if par and par[0]["share_pct"] >= 30:
            hyps.append(Hypothesis(statement=f"'{par[0]['reason']}' accounts for {par[0]['share_pct']}% of downtime on {root['line']} "
                                             f"({par[0]['minutes']:.0f} min, {par[0]['events']} events).",
                                   kind="fact", confidence="high", evidence_ids=[root["id"], *ids_of("downtime")][:3],
                                   how_to_verify="Review maintenance logs for this reason."))
    if "machine" in cats or root["category"] == "machine":
        mids = [root["id"]] if root["category"] == "machine" else ids_of("machine")
        hyps.append(Hypothesis(statement=f"Equipment degradation on {root['line']} (sensor drift detected by the ML model) may be causing stops "
                                         f"and defects before a breakdown.", kind="hypothesis", confidence="medium",
                               evidence_ids=list(dict.fromkeys([root["id"], *mids])), how_to_verify="Inspect the machine; check vibration/temperature after maintenance."))
    if "bottleneck" in cats or root["category"] == "bottleneck":
        bids = [root["id"]] if root["category"] == "bottleneck" else ids_of("bottleneck")
        hyps.append(Hypothesis(statement=f"A capacity constraint on {root['line']} limits output against ERP demand.",
                               kind="hypothesis", confidence="medium", evidence_ids=list(dict.fromkeys([root["id"], *bids])),
                               how_to_verify="Compare constraint station throughput with demand after re-planning."))
    if cats & {"quality", "visual"} or root["category"] in ("quality", "visual"):
        q = ids_of("quality", "visual")
        hyps.append(Hypothesis(statement=f"Quality losses on {root['line']} add to the output gap; visual inspection and defect data should be reviewed together.",
                               kind="hypothesis", confidence="low", evidence_ids=list(dict.fromkeys([root["id"], *q])),
                               how_to_verify="Pareto of defect types per shift."))
    shift = [f for f in same_line if f.get("detector") == "shift"]
    if shift:
        hyps.append(Hypothesis(statement=shift[0]["title"] + " — work method, staffing or settings may differ between shifts.",
                               kind="correlation", confidence="medium", evidence_ids=[shift[0]["id"]],
                               how_to_verify="Compare setup sheets and operator training between shifts."))
    related = [f["id"] for f in sorted(same_line, key=lambda f: f["severity"] != "critical")][:8]
    return Investigation(summary=f"Rule-based investigation of {root['id']} on {root['line']}: {len(same_line)} related evidence item(s) "
                                 f"on the same line ({', '.join(sorted(cats)) or 'none'}). Causes are proposed as hypotheses, not facts.",
                         hypotheses=hyps[:5], related_evidence_ids=related,
                         data_gaps=["Maintenance work-order history", "Defect type per unit", "Operator / changeover logs"])


TEMPLATES = {
    "machine": ("Inspect and service {what} before failure", "maintenance_work_order", "Maintenance lead", "high", 1,
                "Lower failure risk; avoid an unplanned stop", "Failure probability below the alert threshold after service"),
    "bottleneck": ("Re-plan orders / add overtime at the constraint on {line}", "production_change", "Production planner", "high", 2,
                   "Close the projected capacity shortfall", "Projected shortfall reaches zero in the next forecast"),
    "visual": ("Quarantine and 100% re-inspect the affected batch on {line}", "quality_containment", "Quality engineer", "high", 0,
               "Stop defective parts reaching customers", "No defects found in follow-up inspection"),
    "quality": ("Containment check and defect Pareto on {line}", "quality_containment", "Quality engineer", "medium", 1,
                "Identify the main defect types", "Defect rate below the warning threshold"),
    "downtime": ("Root-cause the top downtime reason on {line} with maintenance", "corrective", "Maintenance lead", "medium", 3,
                 "Reduce downtime toward the plant baseline", "Average daily downtime back under the baseline"),
    "output": ("Daily loss review on {line} (downtime, speed, quality losses)", "corrective", "Production supervisor", "medium", 2,
               "Recover target achievement", "Target achievement above the warning threshold"),
    "anomaly": ("Review changes around the onset date on {line}", "corrective", "Production supervisor", "medium", 2,
                "Explain the unusual pattern", "Metric back within the normal range vs peers"),
    "risk": ("Preventive check on {line} before the projected decline", "corrective", "Production supervisor", "medium", 1,
             "Prevent the projected decline", "Next days' KPIs stay inside thresholds"),
}


def _rules_plan(root: dict, inv: Investigation, analysis: dict | None, plant: dict) -> Plan:
    fs = {f["id"]: f for f in _all_findings(analysis, plant)}
    order = [root["id"]] + [i for i in inv.related_evidence_ids if i != root["id"]]
    steps, seen = [], set()
    for fid in order:
        f = fs.get(fid)
        if not f or f["category"] in seen or f["category"] not in TEMPLATES:
            continue
        seen.add(f["category"])
        t = TEMPLATES[f["category"]]
        what = f["title"].split(" (")[0] if f["category"] == "machine" else f["line"]
        steps.append(PlanStep(title=t[0].format(line=f["line"], what=what), action_type=t[1], owner_role=t[2], priority=t[3],
                              due_in_days=t[4], evidence_ids=[fid], expected_effect=t[5], verification=t[6]))
        if len(steps) >= 4:
            break
    rank = {"high": 0, "medium": 1, "low": 2}
    steps.sort(key=lambda x: (rank[x.priority], x.due_in_days))
    return Plan(objective=f"Resolve {root['id']}: {root['title']}", steps=steps)


# ---------------- Gemini agents ----------------

def _gemini_investigate(root, analysis, plant, actions, valid) -> tuple[Investigation, list[dict], str]:
    from google import genai
    from google.genai import types

    tool_log: list[dict] = []
    tools = copilot.build_tools(analysis, plant, actions, tool_log)
    client = genai.Client()
    task = (f"Investigate evidence item {root['id']} ({root['category']}, {root['severity']}) on {root['line']}: "
            f"{root['title']}. Evidence: {root['evidence']}")
    notes = client.models.generate_content(
        model=model_name(), contents=task,
        config=types.GenerateContentConfig(system_instruction=INVESTIGATOR_SYSTEM, tools=tools, temperature=0.2,
                                           automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=10)),
    ).text or ""
    resp = client.models.generate_content(
        model=model_name(), contents=STRUCTURE_PROMPT.format(ids=", ".join(sorted(valid)), notes=notes),
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Investigation, temperature=0.1),
    )
    inv = resp.parsed if isinstance(resp.parsed, Investigation) else Investigation.model_validate_json(resp.text)
    return inv, tool_log, notes


def _gemini_plan(root, inv: Investigation) -> Plan:
    from google import genai
    from google.genai import types

    client = genai.Client()
    resp = client.models.generate_content(
        model=model_name(),
        contents="Root evidence:\n" + json.dumps({k: root[k] for k in ("id", "category", "severity", "line", "title", "evidence")})
                 + "\nInvestigation:\n" + inv.model_dump_json(),
        config=types.GenerateContentConfig(system_instruction=PLANNER_SYSTEM, response_mime_type="application/json",
                                           response_schema=Plan, temperature=0.2),
    )
    return resp.parsed if isinstance(resp.parsed, Plan) else Plan.model_validate_json(resp.text)


# ---------------- coordinator ----------------

def approval_levels(step: PlanStep) -> int:
    if step.action_type == "production_change":
        return 2
    if step.action_type == "maintenance_work_order" and step.priority == "high":
        return 2
    return 1


def _clean(inv: Investigation, plan: Plan, root_id: str, valid: set[str]) -> tuple[Investigation, Plan, int]:
    dropped = 0
    keep = []
    for h in inv.hypotheses:
        h.evidence_ids = [i for i in h.evidence_ids if i in valid]
        if h.evidence_ids:
            keep.append(h)
        else:
            dropped += 1
    inv.hypotheses = keep
    inv.related_evidence_ids = [i for i in inv.related_evidence_ids if i in valid]
    for st in plan.steps:
        st.evidence_ids = [i for i in st.evidence_ids if i in valid] or [root_id]
    plan.steps = plan.steps[:6]
    return inv, plan, dropped


def run(s: Session, root_id: str, analysis: dict | None, plant: dict, dataset_id: str | None,
        actor: str, actor_role: str, actions: list[dict]) -> db.WorkflowRun:
    fs = {f["id"]: f for f in _all_findings(analysis, plant)}
    root = fs.get(root_id)
    if not root:
        raise KeyError(root_id)
    valid = set(fs)
    wf = db.WorkflowRun(id=uuid.uuid4().hex[:12], dataset_id=dataset_id, finding_id=root_id, finding_title=root["title"][:300],
                        status="running", requested_by=actor)
    s.add(wf)
    audit(s, actor, actor_role, "workflow_started", "workflow", wf.id, f"Investigate {root_id}: {root['title']}")
    steps: list[dict] = []
    mode = "gemini" if is_configured() else "rules"
    note = None

    t0 = _now()
    tool_log: list[dict] = []
    notes = ""
    try:
        if mode == "gemini":
            inv, tool_log, notes = _gemini_investigate(root, analysis, plant, actions, valid)
        else:
            inv = _rules_investigate(root, analysis, plant)
    except Exception as e:  # noqa: BLE001
        log.exception("Investigator failed")
        mode, note = "rules", f"Gemini investigator failed ({type(e).__name__}); used rule-based investigation."
        inv = _rules_investigate(root, analysis, plant)
    try:
        plan = _gemini_plan(root, inv) if mode == "gemini" else _rules_plan(root, inv, analysis, plant)
    except Exception as e:  # noqa: BLE001
        log.exception("Planner failed")
        note = (note or "") + f" Gemini planner failed ({type(e).__name__}); used rule-based plan."
        plan = _rules_plan(root, inv, analysis, plant)
    inv, plan, dropped = _clean(inv, plan, root_id, valid)

    steps.append({"agent": "Investigator", "mode": mode, "started_at": t0, "finished_at": _now(),
                  "description": "Gathers related evidence with data tools and proposes root-cause hypotheses.",
                  "tool_calls": tool_log, "notes": notes[:4000], "output": inv.model_dump(),
                  "note": f"{dropped} uncited hypothesis(es) removed." if dropped else None})
    steps.append({"agent": "Planner", "mode": mode, "started_at": steps[-1]["finished_at"], "finished_at": _now(),
                  "description": "Turns the investigation into a prioritised corrective-action plan.", "output": plan.model_dump()})

    # Coordinator: create actions under approval policy.
    created = []
    for st in plan.steps:
        lv = approval_levels(st)
        a = db.Action(id=uuid.uuid4().hex[:10], dataset_id=dataset_id, title=st.title[:200], owner_role=st.owner_role[:100],
                      finding_ids=" ".join(st.evidence_ids[:10]), source="agent", status="pending", priority=st.priority,
                      due_date=date.today() + timedelta(days=st.due_in_days), workflow_id=wf.id, action_type=st.action_type,
                      approval_levels=lv, note="")
        created.append(a)
    steps.append({"agent": "Coordinator", "mode": "code", "started_at": _now(), "finished_at": _now(),
                  "description": "Checks citations, applies the approval policy and routes actions to people. Never approves.",
                  "output": {"actions": [{"title": a.title, "action_type": a.action_type, "priority": a.priority,
                                          "approval_route": ["Supervisor"] + (["Plant manager"] if a.approval_levels == 2 else []),
                                          "due_date": str(a.due_date)} for a in created]}})
    wf.mode = mode
    wf.steps_json = json.dumps(steps, default=str)
    wf.plan_json = json.dumps({"objective": plan.objective, "root": {k: root.get(k) for k in ("id", "category", "line", "title", "value", "severity")},
                               "note": note}, default=str)
    wf.status = "awaiting_approval" if created else "done"
    wf.updated_at = db.utcnow()
    s.flush()
    for a in created:
        s.add(a)
        audit(s, "Coordinator agent", "agent", "action_proposed", "action", a.id,
              f"{a.title} | route: {'Supervisor → Plant manager' if a.approval_levels == 2 else 'Supervisor'}")
    s.commit()
    return wf


# ---------------- approvals ----------------

class ApprovalError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def decide(s: Session, action: db.Action, role: str, name: str, decision: str, comment: str) -> db.Action:
    if action.status != "pending":
        raise ApprovalError(409, f"Action is '{action.status}', not awaiting approval.")
    level = action.approved_levels + 1
    if ROLES.get(role, 0) < level:
        need = "Supervisor" if level == 1 else "Plant manager"
        raise ApprovalError(403, f"Level {level} approval requires the {need} role (you are {ROLE_LABEL.get(role, role)}).")
    if not name.strip():
        raise ApprovalError(422, "Enter your name before approving.")
    s.add(db.Approval(action_id=action.id, level=level, role=role, decision=decision, by_name=name, comment=comment))
    if decision == "rejected":
        action.status = "rejected"
    else:
        action.approved_levels = level
        if level >= action.approval_levels:
            action.status = "approved"
    action.updated_at = db.utcnow()
    audit(s, name, role, f"action_{decision}", "action", action.id, f"Level {level}: {comment}")
    _update_workflow(s, action.workflow_id)
    s.commit()
    return action


def set_progress(s: Session, action: db.Action, status: str, role: str, name: str, note: str | None) -> db.Action:
    allowed = {"approved": {"in_progress", "completed"}, "in_progress": {"completed"}}
    if status and status not in allowed.get(action.status, set()):
        raise ApprovalError(409, f"Cannot move an action from '{action.status}' to '{status}'. Approve it first.")
    if status:
        action.status = status
        audit(s, name or "Anonymous", role, f"action_{status}", "action", action.id, note or "")
    if note is not None:
        action.note = note
    action.updated_at = db.utcnow()
    _update_workflow(s, action.workflow_id)
    s.commit()
    return action


def _update_workflow(s: Session, wf_id: str | None) -> None:
    if not wf_id:
        return
    wf = s.get(db.WorkflowRun, wf_id)
    if not wf or wf.status == "verified":
        return
    acts = s.scalars(sa.select(db.Action).where(db.Action.workflow_id == wf_id)).all()
    st = {a.status for a in acts}
    if "pending" in st:
        wf.status = "awaiting_approval"
    elif st <= {"rejected"}:
        wf.status = "rejected"
    elif st <= {"completed", "rejected"}:
        wf.status = "done"
    else:
        wf.status = "in_progress"
    wf.updated_at = db.utcnow()


# ---------------- verifier ----------------

def verify(s: Session, wf: db.WorkflowRun, current_findings: list[dict], comparison: dict | None, actor: str, role: str) -> dict:
    plan = json.loads(wf.plan_json or "{}")
    root = plan.get("root", {})
    now = {f["id"]: f for f in current_findings}
    same = [f for f in current_findings if f["line"] == root.get("line") and f["category"] == root.get("category")]
    details = []
    result = "inconclusive"
    if root.get("category") == "machine":
        cur = now.get(root["id"])
        if cur is None:
            result, msg = "improved", f"{root['id']} is no longer flagged: failure probability is below the alert threshold."
        else:
            result = "improved" if cur["value"] < (root.get("value") or 1) * 0.5 else "not_improved"
            msg = f"Failure probability {root.get('value')} → {cur['value']}."
        details.append(msg)
    elif root.get("category") == "bottleneck":
        result = "improved" if not same else "not_improved"
        details.append("No bottleneck finding remains on this line." if not same else f"Still flagged: {same[0]['title']}.")
    elif comparison:
        row = next((r for r in comparison["lines"] if r["line"] == root.get("line")), None)
        if row and row.get("target_achievement_pct"):
            ach, dr, dt = row["target_achievement_pct"], row.get("defect_rate_pct"), row.get("downtime_per_day")
            trends = [x["trend"] for x in (ach, dr, dt) if x]
            result = "improved" if "improved" in trends and "worse" not in trends else "not_improved" if "worse" in trends else "no_change"
            details.append(f"{root['line']}: achievement {ach['base']}% → {ach['current']}% ({ach['trend']})"
                           + (f"; defect rate {dr['base']}% → {dr['current']}% ({dr['trend']})" if dr else "")
                           + (f"; downtime/day {dt['base']} → {dt['current']} min ({dt['trend']})" if dt else "") + ".")
            details.append(f"Compared {comparison['base']['name']} with {comparison['current']['name']}.")
    else:
        details.append("Load a newer production dataset to compare before and after.")
    out = {"result": result, "details": details, "checked_at": _now()}
    steps = json.loads(wf.steps_json or "[]")
    steps.append({"agent": "Verifier", "mode": "code", "started_at": out["checked_at"], "finished_at": _now(),
                  "description": "Compares the evidence before and after the actions.", "output": out})
    wf.steps_json = json.dumps(steps, default=str)
    if result == "improved":
        wf.status = "verified"
    wf.updated_at = db.utcnow()
    audit(s, actor or "Verifier agent", role or "agent", "workflow_verified", "workflow", wf.id, f"{result}: {' '.join(details)}")
    s.commit()
    return out
