"""Shared FastAPI dependencies and serialisers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote

import sqlalchemy as sa
from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from . import analysis, db, evidence
from .agents import ROLES

get_session = db.get_session


@dataclass
class User:
    name: str
    role: str


def current_user(x_user_name: str | None = Header(default=None), x_user_role: str | None = Header(default=None)) -> User:
    """Prototype identity: name + role sent by the UI. In production put the app behind
    Identity-Aware Proxy / Firebase Auth and map the signed-in user to a role."""
    role = (x_user_role or "operator").strip().lower()
    if role not in ROLES:
        role = "operator"
    return User(name=unquote(x_user_name or "").strip()[:100], role=role)


def iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if isinstance(d, datetime) else (str(d) if d else None)


def inspection_dict(i: db.Inspection) -> dict:
    return {"id": i.id, "seq": i.seq, "line": i.line, "part": i.part, "notes": i.notes,
            "defect_detected": i.defect_detected, "defect_type": i.defect_type, "severity": i.severity,
            "confidence": i.confidence, "description": i.description, "visible_evidence": i.visible_evidence,
            "recommended_action": i.recommended_action, "image_quality_ok": i.image_quality_ok,
            "model": i.model, "created_at": iso(i.created_at),
            "finding_id": f"V{i.seq}" if i.defect_detected and i.severity != "none" else None,
            "image_url": f"/api/inspections/{i.id}/image"}


def action_dict(a: db.Action, approvals: list[db.Approval] | None = None) -> dict:
    return {"id": a.id, "dataset_id": a.dataset_id, "title": a.title, "owner_role": a.owner_role,
            "finding_ids": a.finding_ids.split() if a.finding_ids else [], "source": a.source,
            "status": a.status, "note": a.note, "priority": a.priority, "due_date": iso(a.due_date),
            "workflow_id": a.workflow_id, "action_type": a.action_type,
            "approval_levels": a.approval_levels, "approved_levels": a.approved_levels,
            "next_approver": (None if a.status != "pending" else ("supervisor" if a.approved_levels == 0 else "plant_manager")),
            "approvals": [{"level": p.level, "role": p.role, "decision": p.decision, "by_name": p.by_name,
                           "comment": p.comment, "at": iso(p.at)} for p in (approvals or [])],
            "created_at": iso(a.created_at), "updated_at": iso(a.updated_at)}


def actions_for(s: Session, ds_id: str | None, include_plant: bool = True) -> list[dict]:
    q = sa.select(db.Action)
    conds = []
    if ds_id:
        conds.append(db.Action.dataset_id == ds_id)
    if include_plant:
        conds.append(db.Action.dataset_id.is_(None))
    if conds:
        q = q.where(sa.or_(*conds))
    rows = s.scalars(q.order_by(db.Action.created_at)).all()
    appr: dict[str, list] = {}
    if rows:
        for p in s.scalars(sa.select(db.Approval).where(db.Approval.action_id.in_([a.id for a in rows])).order_by(db.Approval.id)).all():
            appr.setdefault(p.action_id, []).append(p)
    return [action_dict(a, appr.get(a.id)) for a in rows]


def insight_dict(r: db.InsightRun | None) -> dict | None:
    if not r:
        return None
    return {"source": r.source, "model": r.model, "note": r.note, "question": r.question,
            "report": json.loads(r.report_json), "generated_at": iso(r.created_at)}


def get_ds(s: Session, ds_id: str) -> db.Dataset:
    ds = s.get(db.Dataset, ds_id)
    if not ds:
        raise HTTPException(404, "Dataset not found.")
    return ds


def production_analysis(s: Session, ds: db.Dataset) -> dict:
    records = s.scalars(sa.select(db.ProductionRecord).where(db.ProductionRecord.dataset_id == ds.id)).all()
    insp = s.scalars(sa.select(db.Inspection).where(db.Inspection.dataset_id == ds.id).order_by(db.Inspection.seq)).all()
    return analysis.build(analysis.records_to_df(records), [inspection_dict(i) for i in insp])


def full_analysis(s: Session, ds: db.Dataset | None) -> tuple[dict | None, dict]:
    """(production analysis or None, plant data). Production analysis 'findings' are production-only."""
    return (production_analysis(s, ds) if ds else None), evidence.plant(s)


def merged_for_ai(prod: dict, plant: dict) -> dict:
    """Production analysis with plant-level findings appended (for insights / reports)."""
    m = dict(prod)
    m["findings"] = prod["findings"] + plant["findings"]
    mh, cap = plant["machine_health"], plant["capacity"]
    m["plant_summary"] = {
        "ml_model": ({k: mh["model"][k] for k in ("id", "algorithm", "horizon_hours", "threshold")} | {"test_metrics": mh["model"]["metrics"]}) if mh.get("model") else None,
        "machines_at_risk": [{k: x.get(k) for k in ("machine_code", "line", "failure_probability", "risk_level")}
                             for x in mh.get("machines", []) if x.get("risk_level") in ("high", "medium")],
        "constraints": [{k: l[k] for k in ("line", "constraint_station", "constraint_utilisation_pct", "shortfall_units", "shortfall_days")}
                        for l in cap.get("lines", [])],
    }
    return m


def latest_insight(s: Session, ds_id: str) -> db.InsightRun | None:
    return s.scalars(sa.select(db.InsightRun).where(db.InsightRun.dataset_id == ds_id)
                     .order_by(db.InsightRun.id.desc()).limit(1)).first()
