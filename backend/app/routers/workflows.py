"""Agent workflows (investigate → plan → route for approval → verify) and the audit log."""
from __future__ import annotations

import json
import logging

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import agents, db, patterns
from ..deps import User, actions_for, current_user, full_analysis, get_ds, get_session, iso, production_analysis

log = logging.getLogger("smartfactory")
router = APIRouter(prefix="/api")


class WorkflowCreate(BaseModel):
    finding_id: str = Field(min_length=2, max_length=16)
    dataset_id: str | None = None


class VerifyRequest(BaseModel):
    compare_dataset_id: str | None = None


def _wf_dict(s: Session, wf: db.WorkflowRun, with_steps: bool = True) -> dict:
    acts = [a for a in actions_for(s, wf.dataset_id, include_plant=wf.dataset_id is None) if a["workflow_id"] == wf.id] if with_steps else []
    out = {"id": wf.id, "dataset_id": wf.dataset_id, "finding_id": wf.finding_id, "finding_title": wf.finding_title,
           "status": wf.status, "mode": wf.mode, "requested_by": wf.requested_by, "created_at": iso(wf.created_at),
           "updated_at": iso(wf.updated_at), "plan": json.loads(wf.plan_json or "{}")}
    if with_steps:
        out["steps"] = json.loads(wf.steps_json or "[]")
        out["actions"] = acts
    return out


@router.post("/workflows", status_code=201)
def start(body: WorkflowCreate, s: Session = Depends(get_session), user: User = Depends(current_user)):
    ds = get_ds(s, body.dataset_id) if body.dataset_id else None
    prod, plant = full_analysis(s, ds)
    is_plant = body.finding_id[0] in "MB"
    try:
        wf = agents.run(s, body.finding_id, prod, plant, None if is_plant else (ds.id if ds else None),
                        user.name or "Anonymous", user.role, actions_for(s, ds.id if ds else None))
    except KeyError:
        raise HTTPException(404, f"Evidence {body.finding_id} not found. Load the dataset it belongs to.")
    return _wf_dict(s, wf)


@router.get("/workflows")
def list_workflows(dataset_id: str | None = None, s: Session = Depends(get_session)):
    q = sa.select(db.WorkflowRun).order_by(db.WorkflowRun.created_at.desc()).limit(100)
    if dataset_id:
        q = q.where(sa.or_(db.WorkflowRun.dataset_id == dataset_id, db.WorkflowRun.dataset_id.is_(None)))
    rows = s.scalars(q).all()
    counts = dict(s.execute(sa.select(db.Action.workflow_id, sa.func.count()).where(db.Action.status == "pending")
                            .group_by(db.Action.workflow_id)).all())
    return [{**_wf_dict(s, w, with_steps=False), "pending_approvals": int(counts.get(w.id, 0))} for w in rows]


@router.get("/workflows/{wf_id}")
def get_workflow(wf_id: str, s: Session = Depends(get_session)):
    wf = s.get(db.WorkflowRun, wf_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return _wf_dict(s, wf)


@router.post("/workflows/{wf_id}/verify")
def verify(wf_id: str, body: VerifyRequest | None = None, s: Session = Depends(get_session), user: User = Depends(current_user)):
    wf = s.get(db.WorkflowRun, wf_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    comparison = None
    target = body.compare_dataset_id if body else None
    if wf.dataset_id:
        base = get_ds(s, wf.dataset_id)
        if not target:   # default: the most recent other dataset
            target = s.scalar(sa.select(db.Dataset.id).where(db.Dataset.id != base.id)
                              .order_by(db.Dataset.uploaded_at.desc()).limit(1))
        if target:
            cur = get_ds(s, target)
            comparison = patterns.compare(production_analysis(s, base), production_analysis(s, cur), base.name, cur.name)
    cur_ds = get_ds(s, target) if target else None
    prod, plant = full_analysis(s, cur_ds)
    findings = (prod["findings"] if prod else []) + plant["findings"]
    out = agents.verify(s, wf, findings, comparison, user.name, user.role)
    return {"verification": out, "workflow": _wf_dict(s, wf)}


@router.get("/audit")
def audit_log(limit: int = 100, s: Session = Depends(get_session)):
    rows = s.scalars(sa.select(db.AuditLog).order_by(db.AuditLog.id.desc()).limit(max(1, min(limit, 500)))).all()
    return [{"at": iso(r.at), "actor": r.actor, "actor_role": r.actor_role, "event": r.event, "entity": r.entity,
             "entity_id": r.entity_id, "detail": r.detail} for r in rows]
