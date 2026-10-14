"""Level 3 plant data: machine health (ML), capacity / bottlenecks, ERP work orders."""
from __future__ import annotations

import json
from typing import Literal

import pandas as pd
import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import capacity, db, evidence, jobs, machine_health
from ..agents import audit
from ..deps import User, current_user, get_session, iso
from ..validation import read_table

router = APIRouter(prefix="/api")


# ---------------- machine health ----------------

@router.get("/machines")
def machines_overview(s: Session = Depends(get_session)):
    plant = evidence.plant(s)
    mh = plant["machine_health"]
    counts = dict(s.execute(sa.select(db.SensorReading.machine_id, sa.func.count()).group_by(db.SensorReading.machine_id)).all())
    rng = s.execute(sa.select(sa.func.min(db.SensorReading.ts), sa.func.max(db.SensorReading.ts), sa.func.count())).one()
    ev = s.execute(sa.select(db.MachineEvent.event_type, sa.func.count()).group_by(db.MachineEvent.event_type)).all()
    synthetic = bool(s.scalar(sa.select(sa.func.count()).select_from(db.Machine).where(db.Machine.synthetic.is_(True))))
    fid = {f["id"]: f for f in plant["findings"]}
    machines = []
    for m in mh.get("machines", []):
        m = dict(m)
        m["readings"] = int(counts.get(m["machine_id"], 0))
        m["finding_id"] = f"M{m['machine_id']}" if f"M{m['machine_id']}" in fid else None
        machines.append(m)
    if not machines:   # machines without a model yet
        for m in s.scalars(sa.select(db.Machine).order_by(db.Machine.machine_code)).all():
            machines.append({"machine_id": m.id, "machine_code": m.machine_code, "line": m.line, "machine_type": m.machine_type,
                             "status": "no_model", "readings": int(counts.get(m.id, 0)), "finding_id": None})
    runs = s.scalars(sa.select(db.ModelRun).order_by(db.ModelRun.id.desc()).limit(10)).all()
    return {"model": mh.get("model"), "machines": machines, "synthetic": synthetic, "error": mh.get("error"),
            "readings": {"from": iso(rng[0]), "to": iso(rng[1]), "count": rng[2]},
            "events": {k: v for k, v in ev},
            "runs": [{"id": r.id, "created_at": iso(r.created_at), "threshold": r.threshold,
                      "metrics": {k: json.loads(r.metrics_json).get(k) for k in ("roc_auc", "pr_auc", "recall", "precision", "failures_caught", "failures_in_test")}}
                     for r in runs]}


@router.get("/machines/{machine_id}")
def machine_detail(machine_id: int, hours: int = 168, s: Session = Depends(get_session)):
    m = s.get(db.Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found")
    hours = max(24, min(hours, 720))
    pred = machine_health.predict(s, history_hours=hours) if machine_health.latest_run(s) else {"machines": []}
    rec = next((x for x in pred["machines"] if x["machine_id"] == machine_id), None)
    if rec is None or "history" not in rec:
        last = s.scalar(sa.select(sa.func.max(db.SensorReading.ts)).where(db.SensorReading.machine_id == machine_id))
        rows = pd.read_sql(sa.select(db.SensorReading.ts, *[getattr(db.SensorReading, c) for c in machine_health.SIGNALS])
                           .where(db.SensorReading.machine_id == machine_id, db.SensorReading.ts >= (last or pd.Timestamp.now()) - pd.Timedelta(hours=hours))
                           .order_by(db.SensorReading.ts), s.bind)
        rec = {"machine_id": m.id, "machine_code": m.machine_code, "line": m.line, "machine_type": m.machine_type, "status": "no_model",
               "history": {"ts": [str(t) for t in rows["ts"]], **{c: rows[c].round(2).tolist() for c in machine_health.SIGNALS}}}
    events = s.scalars(sa.select(db.MachineEvent).where(db.MachineEvent.machine_id == machine_id).order_by(db.MachineEvent.ts.desc()).limit(20)).all()
    rec["events"] = [{"ts": iso(e.ts), "event_type": e.event_type, "description": e.description, "source": e.source} for e in events]
    rec["finding_id"] = f"M{machine_id}" if any(f["id"] == f"M{machine_id}" for f in evidence.plant(s)["findings"]) else None
    return rec


@router.post("/machines/readings")
async def upload_readings(file: UploadFile = File(...), s: Session = Depends(get_session)):
    df = machine_health.normalise_sensor_frame(read_table(file.filename or "", await file.read()))
    n = machine_health.ingest_readings(s, df, "upload")
    evidence.invalidate()
    return {"rows": n, "machines": int(df["machine_code"].nunique())}


@router.post("/machines/events")
async def upload_events(file: UploadFile = File(...), s: Session = Depends(get_session)):
    df = machine_health.normalise_event_frame(read_table(file.filename or "", await file.read()))
    n = machine_health.ingest_events(s, df, "upload")
    evidence.invalidate()
    return {"rows": n}


class EventIn(BaseModel):
    event_type: Literal["failure", "maintenance"]
    description: str = Field(default="", max_length=500)


@router.post("/machines/{machine_id}/events", status_code=201)
def record_event(machine_id: int, body: EventIn, s: Session = Depends(get_session), user: User = Depends(current_user)):
    m = s.get(db.Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found")
    last = s.scalar(sa.select(sa.func.max(db.SensorReading.ts)).where(db.SensorReading.machine_id == machine_id))
    ts = max(db.utcnow(), last) if last else db.utcnow()   # never before the latest reading
    s.add(db.MachineEvent(machine_id=machine_id, ts=ts, event_type=body.event_type,
                          description=body.description or f"Recorded by {user.name or 'user'}", source="manual"))
    audit(s, user.name or "Anonymous", user.role, f"machine_{body.event_type}", "machine", str(machine_id), body.description)
    s.commit()
    evidence.invalidate()
    return {"ok": True, "ts": iso(ts)}


@router.post("/machines/train")
def train_model(background: bool = False, s: Session = Depends(get_session)):
    if background:
        def task():
            with db.SessionLocal() as s2:
                run = machine_health.train(s2)
                evidence.invalidate()
                return machine_health._run_dict(run)
        return {"job": jobs.start("train-model", task)}
    try:
        run = machine_health.train(s)
    except machine_health.NotEnoughData as e:
        raise HTTPException(422, str(e))
    evidence.invalidate()
    return machine_health._run_dict(run)


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found (it may have run on another instance or before a restart).")
    return j


# ---------------- capacity & bottlenecks ----------------

@router.get("/capacity")
def capacity_overview(s: Session = Depends(get_session)):
    plant = evidence.plant(s)
    synthetic = bool(s.scalar(sa.select(sa.func.count()).select_from(db.StationRecord).where(db.StationRecord.synthetic.is_(True))))
    return {**plant["capacity"], "work_orders": plant["work_orders"], "synthetic": synthetic}


@router.post("/capacity/stations")
async def upload_stations(file: UploadFile = File(...), s: Session = Depends(get_session)):
    df = capacity.normalise_stations(read_table(file.filename or "", await file.read()))
    ingest_stations(s, df, "upload")
    evidence.invalidate()
    return {"rows": len(df), "lines": int(df["line"].nunique()), "stations": int(df.groupby(["line", "station"]).ngroups)}


@router.post("/capacity/work-orders")
async def upload_orders(file: UploadFile = File(...), s: Session = Depends(get_session)):
    df = capacity.normalise_orders(read_table(file.filename or "", await file.read()))
    n = upsert_orders(s, df, "upload")
    evidence.invalidate()
    return {"rows": n}


@router.get("/work-orders")
def list_orders(s: Session = Depends(get_session)):
    rows = s.scalars(sa.select(db.WorkOrder).order_by(db.WorkOrder.due_date, db.WorkOrder.line).limit(500)).all()
    return [{"order_id": o.order_id, "product": o.product, "line": o.line, "quantity": o.quantity, "due_date": iso(o.due_date),
             "status": o.status, "customer": o.customer, "source": o.source} for o in rows]


def ingest_stations(s: Session, df: pd.DataFrame, source: str, synthetic: bool = False) -> None:
    # Replace existing rows for the same line/station/date (re-uploads correct data rather than duplicate it).
    keys = df[["line", "station", "date"]].drop_duplicates()
    for (line, station), g in keys.groupby(["line", "station"]):
        s.execute(sa.delete(db.StationRecord).where(db.StationRecord.line == line, db.StationRecord.station == station,
                                                    db.StationRecord.date.in_(list(g["date"]))))
    rows = [{**r, "source": source, "synthetic": synthetic} for r in df[capacity.STATION_COLS].to_dict("records")]
    for i in range(0, len(rows), 1000):
        s.execute(sa.insert(db.StationRecord), rows[i:i + 1000])
    s.commit()


def upsert_orders(s: Session, df: pd.DataFrame, source: str, synthetic: bool = False) -> int:
    n = 0
    for r in df.to_dict("records"):
        o = s.get(db.WorkOrder, r["order_id"]) or db.WorkOrder(order_id=r["order_id"])
        o.product, o.line, o.quantity, o.due_date = r.get("product", ""), r["line"], float(r["quantity"]), r["due_date"]
        o.status, o.customer, o.source, o.synthetic, o.updated_at = r.get("status", "planned"), r.get("customer", ""), source, synthetic, db.utcnow()
        s.add(o)
        n += 1
    s.commit()
    return n
