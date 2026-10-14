"""One-click SYNTHETIC demo data for every feature, and a built-in IoT stream simulator."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import capacity, db, demo_data, evidence, integrations, jobs, machine_health
from ..deps import get_session
from ..validation import read_table, validate
from .plant import ingest_stations, upsert_orders
from .production import save_dataset

router = APIRouter(prefix="/api/demo")
DATA = Path(__file__).resolve().parent.parent.parent / "data"


@router.post("/load-all")
def load_all(background: bool = False, s: Session = Depends(get_session)):
    """background=true returns a job immediately (poll GET /api/jobs/{id}); use behind proxies with time limits."""
    if background:
        def task():
            with db.SessionLocal() as s2:
                return _load_all(s2)
        return {"job": jobs.start("demo-load-all", task)}
    return _load_all(s)


def _load_all(s: Session) -> dict:
    out = {}
    # 1. Production: two periods (before / after corrective actions)
    ids = []
    for fname, label in (("sample_production.csv", "Period 1 · 28 Sep–11 Oct (synthetic demo)"),
                         ("sample_production_after.csv", "Period 2 · 12–25 Oct, after actions (synthetic demo)")):
        res = validate(read_table(fname, (DATA / fname).read_bytes()))
        ids.append(save_dataset(s, label, res.df, res.warnings, True, None, source="demo").id)
    out["datasets"] = ids
    # 2. Sensors + events (only once)
    has = s.scalar(sa.select(sa.func.count()).select_from(db.Machine).where(db.Machine.synthetic.is_(True)))
    if not has:
        m, r, e = demo_data.sensors()
        out["readings"] = machine_health.ingest_readings(s, r.merge(m, on="machine_code"), "demo", synthetic=True)
        out["events"] = machine_health.ingest_events(s, e, "demo", synthetic=True)
    # 3. Train the failure model if none exists
    if not machine_health.latest_run(s):
        run = machine_health.train(s)
        out["model"] = machine_health._run_dict(run)["metrics"]
    # 4. Stations + ERP work orders
    ingest_stations(s, capacity.normalise_stations(demo_data.stations()), "demo", synthetic=True)
    out["work_orders"] = upsert_orders(s, capacity.normalise_orders(demo_data.work_orders()), "demo", synthetic=True)
    evidence.invalidate()
    return out


@router.post("/simulate")
def simulate(hours: int = 6, s: Session = Depends(get_session)):
    """Generate the next `hours` of synthetic telemetry for the demo machines through the normal ingestion path."""
    if not s.scalar(sa.select(sa.func.count()).select_from(db.Machine).where(db.Machine.synthetic.is_(True))):
        raise HTTPException(409, "Load the demo data first.")
    hours = max(1, min(hours, 48))
    last = s.scalar(sa.select(sa.func.max(db.SensorReading.ts)))
    maint = s.execute(sa.select(db.Machine.machine_code, sa.func.max(db.MachineEvent.ts))
                      .join(db.MachineEvent, db.MachineEvent.machine_id == db.Machine.id)
                      .where(db.MachineEvent.event_type == "maintenance").group_by(db.Machine.machine_code)).all()
    df = demo_data.simulate_readings(last, hours, {c: t for c, t in maint})
    n = machine_health.ingest_readings(s, df, "simulator")
    integrations.log(s, "simulator", "ok", n, f"{hours} h of synthetic telemetry for {df['machine_code'].nunique()} machines", None)
    evidence.invalidate()
    return {"accepted": n, "until": str(df["ts"].max())}
