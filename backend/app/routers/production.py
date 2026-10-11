"""Production datasets, analysis, AI insights, copilot, visual inspection, actions and reports."""
from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import agents, ai, copilot, db, patterns, storage, vision
from ..deps import (User, actions_for, current_user, full_analysis, get_ds, get_session, insight_dict, inspection_dict,
                    iso, latest_insight, merged_for_ai, production_analysis)
from ..validation import read_table, validate

log = logging.getLogger("smartfactory")
router = APIRouter(prefix="/api")
DATA = Path(__file__).resolve().parent.parent.parent / "data"
SAMPLE = DATA / "sample_production.csv"
SAMPLE_AFTER = DATA / "sample_production_after.csv"


def dataset_payload(s: Session, ds: db.Dataset) -> dict:
    prod, plant = full_analysis(s, ds)
    return {"id": ds.id, "name": ds.name, "synthetic": ds.synthetic, "warnings": json.loads(ds.warnings_json),
            "uploaded_at": iso(ds.uploaded_at), "analysis": prod, "plant_findings": plant["findings"],
            "insights": insight_dict(latest_insight(s, ds.id))}


def save_dataset(s: Session, name: str, df, warnings: list[str], synthetic: bool, raw: bytes | None, source: str = "upload") -> db.Dataset:
    ds_id = uuid.uuid4().hex[:12]
    uri = storage.save(f"uploads/{ds_id}/{Path(name).name}", raw, "application/octet-stream") if raw is not None else None
    ds = db.Dataset(id=ds_id, name=name, synthetic=synthetic, warnings_json=json.dumps(warnings), file_uri=uri)
    s.add(ds)
    s.flush()
    s.execute(sa.insert(db.ProductionRecord), [{"dataset_id": ds_id, **r} for r in df.to_dict("records")])
    agents.audit(s, source, "system", "dataset_loaded", "dataset", ds_id, name)
    s.commit()
    return ds


@router.get("/sample-file")
def sample_file():
    return FileResponse(SAMPLE, media_type="text/csv", filename="sample_production.csv")


# ---------------- datasets ----------------

@router.get("/datasets")
def list_datasets(s: Session = Depends(get_session)):
    rows = s.execute(
        sa.select(db.Dataset.id, db.Dataset.name, db.Dataset.synthetic, db.Dataset.uploaded_at,
                  sa.func.count(db.ProductionRecord.id), sa.func.min(db.ProductionRecord.date), sa.func.max(db.ProductionRecord.date))
        .join(db.ProductionRecord, db.ProductionRecord.dataset_id == db.Dataset.id, isouter=True)
        .group_by(db.Dataset.id, db.Dataset.name, db.Dataset.synthetic, db.Dataset.uploaded_at)
        .order_by(db.Dataset.uploaded_at.desc())).all()
    return [{"id": r[0], "name": r[1], "synthetic": r[2], "uploaded_at": iso(r[3]), "records": r[4],
             "date_from": iso(r[5]), "date_to": iso(r[6])} for r in rows[:50]]


@router.post("/datasets")
async def upload(file: UploadFile = File(...), s: Session = Depends(get_session)):
    content = await file.read()
    result = validate(read_table(file.filename or "", content))
    return dataset_payload(s, save_dataset(s, file.filename or "upload", result.df, result.warnings, False, content))


@router.post("/datasets/sample")
def load_sample(s: Session = Depends(get_session)):
    result = validate(read_table(SAMPLE.name, SAMPLE.read_bytes()))
    return dataset_payload(s, save_dataset(s, "sample_production.csv (synthetic demo data)", result.df, result.warnings, True, None))


@router.get("/datasets/{ds_id}")
def get_dataset(ds_id: str, s: Session = Depends(get_session)):
    return dataset_payload(s, get_ds(s, ds_id))


@router.delete("/datasets/{ds_id}", status_code=204)
def delete_dataset(ds_id: str, s: Session = Depends(get_session)):
    ds = get_ds(s, ds_id)
    ids = [a for (a,) in s.execute(sa.select(db.Action.id).where(db.Action.dataset_id == ds_id)).all()]
    if ids:
        s.execute(sa.delete(db.Approval).where(db.Approval.action_id.in_(ids)))
    for model in (db.Action, db.InsightRun, db.Inspection, db.ProductionRecord):
        s.execute(sa.delete(model).where(model.dataset_id == ds_id))
    s.execute(sa.delete(db.WorkflowRun).where(db.WorkflowRun.dataset_id == ds_id))
    s.delete(ds)
    s.commit()
    return Response(status_code=204)


@router.get("/compare")
def compare(base: str, current: str, s: Session = Depends(get_session)):
    b, c = get_ds(s, base), get_ds(s, current)
    out = patterns.compare(production_analysis(s, b), production_analysis(s, c), b.name, c.name)
    # Actions decided in the base period, so the manager can relate changes to what was done.
    out["actions"] = [a for a in actions_for(s, base, include_plant=False) if a["status"] in ("approved", "in_progress", "completed")]
    return out


# ---------------- AI insights ----------------

class InsightRequest(BaseModel):
    question: str | None = Field(default=None, max_length=500)


@router.post("/datasets/{ds_id}/insights")
def insights(ds_id: str, body: InsightRequest | None = None, s: Session = Depends(get_session)):
    ds = get_ds(s, ds_id)
    prod, plant = full_analysis(s, ds)
    q = body.question if body else None
    result = ai.generate(merged_for_ai(prod, plant), q)
    run = db.InsightRun(dataset_id=ds_id, source=result["source"], model=result["model"], question=q,
                        note=result["note"], report_json=json.dumps(result["report"]))
    s.add(run)
    s.commit()
    return insight_dict(run)


# ---------------- copilot ----------------

class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    dataset_id: str | None = None


@router.post("/copilot")
def copilot_chat(body: ChatRequest, s: Session = Depends(get_session)):
    ds = get_ds(s, body.dataset_id) if body.dataset_id else None
    prod, plant = full_analysis(s, ds)
    try:
        return copilot.chat(prod, plant, actions_for(s, ds.id if ds else None), [h.model_dump() for h in body.history], body.message)
    except copilot.CopilotUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Copilot failed")
        raise HTTPException(502, f"Gemini request failed ({type(e).__name__}). Please try again.")


@router.post("/datasets/{ds_id}/copilot")
def copilot_chat_legacy(ds_id: str, body: ChatRequest, s: Session = Depends(get_session)):
    body.dataset_id = ds_id
    return copilot_chat(body, s)


# ---------------- visual inspection ----------------

@router.get("/datasets/{ds_id}/inspections")
def list_inspections(ds_id: str, s: Session = Depends(get_session)):
    get_ds(s, ds_id)
    rows = s.scalars(sa.select(db.Inspection).where(db.Inspection.dataset_id == ds_id).order_by(db.Inspection.seq.desc())).all()
    return [inspection_dict(i) for i in rows]


@router.post("/datasets/{ds_id}/inspections", status_code=201)
async def create_inspection(ds_id: str, image: UploadFile = File(...), line: str = Form(..., max_length=100),
                            part: str = Form("", max_length=200), notes: str = Form("", max_length=500),
                            s: Session = Depends(get_session)):
    get_ds(s, ds_id)
    mime = (image.content_type or "").lower()
    if mime not in vision.ALLOWED_MIME:
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image.")
    data = await image.read()
    if not data:
        raise HTTPException(422, "The image is empty.")
    if len(data) > vision.MAX_IMAGE_BYTES:
        raise HTTPException(422, "Image is larger than 8 MB.")
    try:
        result, model = vision.inspect(data, mime, line, part, notes)
    except vision.VisionUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Vision failed")
        raise HTTPException(502, f"Gemini image analysis failed ({type(e).__name__}). Please try again.")
    insp_id = uuid.uuid4().hex[:12]
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    uri = storage.save(f"inspections/{ds_id}/{insp_id}.{ext}", data, mime)
    seq = (s.scalar(sa.select(sa.func.max(db.Inspection.seq)).where(db.Inspection.dataset_id == ds_id)) or 0) + 1
    row = db.Inspection(id=insp_id, dataset_id=ds_id, seq=seq, line=line.strip(), part=part.strip(), notes=notes.strip(),
                        image_uri=uri, mime_type=mime, model=model, **result.model_dump())
    s.add(row)
    s.commit()
    return inspection_dict(row)


@router.get("/inspections/{insp_id}/image")
def inspection_image(insp_id: str, s: Session = Depends(get_session)):
    i = s.get(db.Inspection, insp_id)
    if not i:
        raise HTTPException(404, "Inspection not found")
    return Response(storage.load(i.image_uri), media_type=i.mime_type, headers={"Cache-Control": "private, max-age=3600"})


# ---------------- actions & approvals ----------------

class ActionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    owner_role: str = Field(default="", max_length=100)
    finding_ids: list[str] = Field(default_factory=list, max_length=20)
    source: Literal["gemini", "rules", "manual", "copilot", "vision", "agent"] = "manual"
    priority: Literal["high", "medium", "low"] = "medium"
    action_type: Literal["corrective", "maintenance_work_order", "quality_containment", "production_change"] = "corrective"


class ActionUpdate(BaseModel):
    status: Literal["in_progress", "completed"] | None = None
    note: str | None = Field(default=None, max_length=1000)


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=1000)


@router.get("/datasets/{ds_id}/actions")
def list_actions(ds_id: str, s: Session = Depends(get_session)):
    get_ds(s, ds_id)
    return actions_for(s, ds_id)


@router.get("/actions")
def list_plant_actions(s: Session = Depends(get_session)):
    return actions_for(s, None)


def _create_action(s: Session, ds_id: str | None, body: ActionCreate, user: User) -> dict:
    ds = get_ds(s, ds_id) if ds_id else None
    prod, plant = full_analysis(s, ds)
    valid = copilot.valid_ids(prod, plant)
    unknown = [i for i in body.finding_ids if i not in valid]
    if unknown:
        raise HTTPException(422, f"Unknown finding id(s): {', '.join(unknown)}")
    step = agents.PlanStep(title=body.title, action_type=body.action_type, owner_role=body.owner_role or "-",
                           priority=body.priority, due_in_days=3, expected_effect="", verification="")
    a = db.Action(id=uuid.uuid4().hex[:10], dataset_id=ds_id, title=body.title, owner_role=body.owner_role,
                  finding_ids=" ".join(body.finding_ids), source=body.source, priority=body.priority,
                  action_type=body.action_type, approval_levels=agents.approval_levels(step))
    s.add(a)
    s.flush()
    agents.audit(s, user.name or "Anonymous", user.role, "action_created", "action", a.id, body.title)
    s.commit()
    return actions_for_one(s, a.id)


def actions_for_one(s: Session, action_id: str) -> dict:
    a = s.get(db.Action, action_id)
    from ..deps import action_dict
    return action_dict(a, s.scalars(sa.select(db.Approval).where(db.Approval.action_id == a.id).order_by(db.Approval.id)).all())


@router.post("/datasets/{ds_id}/actions", status_code=201)
def create_action(ds_id: str, body: ActionCreate, s: Session = Depends(get_session), user: User = Depends(current_user)):
    return _create_action(s, ds_id, body, user)


@router.post("/actions", status_code=201)
def create_plant_action(body: ActionCreate, s: Session = Depends(get_session), user: User = Depends(current_user)):
    return _create_action(s, None, body, user)


@router.post("/actions/{action_id}/decision")
def decide(action_id: str, body: Decision, s: Session = Depends(get_session), user: User = Depends(current_user)):
    a = s.get(db.Action, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    try:
        agents.decide(s, a, user.role, user.name, body.decision, body.comment)
    except agents.ApprovalError as e:
        raise HTTPException(e.status, e.message)
    return actions_for_one(s, action_id)


@router.patch("/actions/{action_id}")
def update_action(action_id: str, body: ActionUpdate, s: Session = Depends(get_session), user: User = Depends(current_user)):
    a = s.get(db.Action, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    try:
        agents.set_progress(s, a, body.status or "", user.role, user.name, body.note)
    except agents.ApprovalError as e:
        raise HTTPException(e.status, e.message)
    return actions_for_one(s, action_id)


# ---------------- report ----------------

@router.get("/datasets/{ds_id}/report.csv")
def report_csv(ds_id: str, s: Session = Depends(get_session)):
    ds = get_ds(s, ds_id)
    prod, plant = full_analysis(s, ds)
    ins = insight_dict(latest_insight(s, ds_id))
    acts = actions_for(s, ds_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["SmartFactory AI report"])
    w.writerow(["Dataset", ds.name])
    if ds.synthetic:
        w.writerow(["Note", "SYNTHETIC DEMO DATA - not real factory results"])
    o = prod["overall"]
    w.writerow(["Period", f"{o['date_from']} to {o['date_to']}"])
    w.writerow([])
    w.writerow(["Line", "Target", "Actual", "Achievement %", "Variance", "Inspected", "Defective",
                "Defect rate %", "Downtime min", "Trend risk (3 days)"])
    risk = {f["line"]: f.get("risk_level", "n/a") for f in prod["forecasts"]}
    for r in prod["by_line"]:
        w.writerow([r["line"], r["target_output"], r["actual_output"], r["target_achievement_pct"], r["output_variance"],
                    r["inspected_units"], r["defective_units"], r["defect_rate_pct"], r["downtime_minutes"], risk.get(r["line"], "")])
    w.writerow(["PLANT", o["target_output"], o["actual_output"], o["target_achievement_pct"], o["output_variance"],
                o["inspected_units"], o["defective_units"], o["defect_rate_pct"], o["downtime_minutes"], ""])
    w.writerow([])
    w.writerow(["Evidence", "Severity", "Category", "Line", "Date", "Title", "Evidence"])
    for f in prod["findings"] + plant["findings"]:
        w.writerow([f["id"], f["severity"], f["category"], f["line"], f["date"] or "", f["title"], f["evidence"]])
    if ins:
        w.writerow([])
        w.writerow(["Insights source", ins["source"], ins.get("model") or ""])
        w.writerow(["Summary", ins["report"]["summary"]])
        w.writerow(["Recommendation", "Priority", "Owner", "Evidence", "Verify by"])
        for r in ins["report"]["recommendations"]:
            w.writerow([r["title"], r["priority"], r["owner_role"], " ".join(r["finding_ids"]), r["verify_by"]])
    if acts:
        w.writerow([])
        w.writerow(["Action", "Status", "Priority", "Type", "Owner", "Evidence", "Approvals", "Due", "Source", "Note", "Updated"])
        for a in acts:
            appr = "; ".join(f"L{p['level']} {p['decision']} by {p['by_name']} ({p['role']})" for p in a["approvals"])
            w.writerow([a["title"], a["status"], a["priority"], a["action_type"], a["owner_role"], " ".join(a["finding_ids"]),
                        appr, a["due_date"] or "", a["source"], a["note"], a["updated_at"]])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="smartfactory_report_{ds_id}.csv"'})
