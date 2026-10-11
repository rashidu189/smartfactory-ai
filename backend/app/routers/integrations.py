"""IoT / Pub/Sub / ERP integration endpoints and management."""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import capacity, db, evidence, integrations, machine_health
from ..deps import User, current_user, get_session, iso
from ..validation import ValidationError, validate
from .plant import upsert_orders
from .production import save_dataset

router = APIRouter(prefix="/api/integrations")
MAX_BATCH = 5000


class Telemetry(BaseModel):
    machine_id: str = Field(min_length=1, max_length=64, description="Machine code, e.g. L03-PRS-01")
    ts: datetime | None = None
    line: str | None = Field(default=None, max_length=100)
    machine_type: str | None = Field(default=None, max_length=100)
    temperature_c: float | None = None
    vibration_mm_s: float | None = None
    current_a: float | None = None
    pressure_bar: float | None = None
    rpm: float | None = None


class MachineEventIn(BaseModel):
    machine_id: str = Field(min_length=1, max_length=64)
    ts: datetime | None = None
    event_type: str = Field(pattern="^(failure|maintenance)$")
    description: str = Field(default="", max_length=500)


class WorkOrderIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    line: str = Field(min_length=1, max_length=100)
    quantity: float = Field(ge=0)
    due_date: str
    product: str = ""
    status: str = "planned"
    customer: str = ""


class ProductionIn(BaseModel):
    name: str = Field(default="ERP production import", max_length=200)
    records: list[dict] = Field(min_length=1, max_length=50000)


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["iot", "erp"])


def _naive(ts: datetime | None) -> datetime:
    """UTC-naive timestamp (the database stores UTC without a zone)."""
    if ts is None:
        return db.utcnow()
    p = pd.Timestamp(ts)
    return (p.tz_convert("UTC").tz_localize(None) if p.tzinfo else p).to_pydatetime()


def _telemetry_frame(items: list[Telemetry]) -> pd.DataFrame:
    return pd.DataFrame([{"machine_code": t.machine_id, "ts": _naive(t.ts), "line": t.line, "machine_type": t.machine_type,
                          **{c: getattr(t, c) for c in machine_health.SIGNALS}} for t in items])


def _ingest_telemetry(s: Session, items: list[Telemetry], channel: str, key) -> dict:
    if not items:
        raise HTTPException(422, "No readings.")
    if len(items) > MAX_BATCH:
        raise HTTPException(413, f"Send at most {MAX_BATCH} readings per request.")
    if all(all(getattr(t, c) is None for c in machine_health.SIGNALS) for t in items):
        raise HTTPException(422, "Readings contain no sensor values.")
    n = machine_health.ingest_readings(s, _telemetry_frame(items), channel)
    integrations.log(s, channel, "ok", n, f"{n} reading(s) from {len({t.machine_id for t in items})} machine(s)", key)
    evidence.invalidate()
    return {"accepted": n}


def _ingest_events(s: Session, items: list[MachineEventIn], channel: str, key) -> dict:
    df = pd.DataFrame([{"machine_code": e.machine_id, "ts": _naive(e.ts), "event_type": e.event_type,
                        "description": e.description} for e in items])
    n = machine_health.ingest_events(s, df, channel)
    integrations.log(s, channel, "ok", n, f"{n} machine event(s)", key)
    evidence.invalidate()
    return {"accepted": n}


# ---------------- inbound: IoT ----------------

@router.post("/iot/telemetry")
def iot_telemetry(body: Telemetry | list[Telemetry], s: Session = Depends(get_session),
                  x_api_key: str | None = Depends(integrations.api_key_header)):
    key = integrations.verify_key(s, x_api_key, "iot")
    return _ingest_telemetry(s, body if isinstance(body, list) else [body], "iot-http", key)


@router.post("/iot/events")
def iot_events(body: MachineEventIn | list[MachineEventIn], s: Session = Depends(get_session),
               x_api_key: str | None = Depends(integrations.api_key_header)):
    key = integrations.verify_key(s, x_api_key, "iot")
    return _ingest_events(s, body if isinstance(body, list) else [body], "iot-events", key)


@router.post("/pubsub/push")
def pubsub_push(envelope: dict, token: str | None = None, s: Session = Depends(get_session)):
    """Target for a Pub/Sub push subscription. message.data = base64(JSON telemetry | [telemetry] | event).
    Set attribute type=event for failure/maintenance events. Returns 2xx so Pub/Sub acknowledges."""
    integrations.verify_pubsub_token(token)
    payload, attrs = integrations.decode_pubsub(envelope)
    items = payload if isinstance(payload, list) else [payload]
    try:
        if attrs.get("type") == "event":
            return _ingest_events(s, [MachineEventIn(**i) for i in items], "pubsub", None)
        return _ingest_telemetry(s, [Telemetry(**i) for i in items], "pubsub", None)
    except (ValueError, TypeError) as e:
        integrations.log(s, "pubsub", "error", 0, f"Bad message: {e}", None)
        # Acknowledge malformed messages (204) so Pub/Sub does not retry them forever; they are logged.
        return {"accepted": 0, "error": "malformed message logged"}


# ---------------- inbound: ERP ----------------

@router.post("/erp/work-orders")
def erp_orders(body: list[WorkOrderIn], s: Session = Depends(get_session),
               x_api_key: str | None = Depends(integrations.api_key_header)):
    key = integrations.verify_key(s, x_api_key, "erp")
    try:
        df = capacity.normalise_orders(pd.DataFrame([o.model_dump() for o in body]))
    except ValidationError as e:
        integrations.log(s, "erp-orders", "error", 0, e.message, key)
        raise
    n = upsert_orders(s, df, "erp")
    integrations.log(s, "erp-orders", "ok", n, f"{n} work order(s) upserted", key)
    evidence.invalidate()
    return {"upserted": n}


@router.post("/erp/production")
def erp_production(body: ProductionIn, s: Session = Depends(get_session),
                   x_api_key: str | None = Depends(integrations.api_key_header)):
    key = integrations.verify_key(s, x_api_key, "erp")
    try:
        result = validate(pd.DataFrame(body.records))
    except ValidationError as e:
        integrations.log(s, "erp-production", "error", 0, e.message, key)
        raise
    ds = save_dataset(s, body.name, result.df, result.warnings, False, None, source="erp")
    integrations.log(s, "erp-production", "ok", len(result.df), f"Dataset {ds.id} created", key)
    return {"dataset_id": ds.id, "records": len(result.df), "warnings": result.warnings}


# ---------------- management ----------------

def _require_manager(user: User) -> None:
    if user.role not in ("supervisor", "plant_manager"):
        raise HTTPException(403, "Only a Supervisor or Plant manager can manage integration keys.")


@router.get("")
def overview(s: Session = Depends(get_session)):
    keys = s.scalars(sa.select(db.ApiKey).order_by(db.ApiKey.id.desc())).all()
    logs = s.scalars(sa.select(db.IntegrationLog).order_by(db.IntegrationLog.id.desc()).limit(50)).all()
    stats = s.execute(sa.select(db.IntegrationLog.channel, sa.func.sum(db.IntegrationLog.records), sa.func.max(db.IntegrationLog.ts))
                      .where(db.IntegrationLog.status == "ok").group_by(db.IntegrationLog.channel)).all()
    return {
        "keys": [{"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes.split(), "created_at": iso(k.created_at),
                  "last_used_at": iso(k.last_used_at), "revoked": k.revoked} for k in keys],
        "log": [{"ts": iso(l.ts), "channel": l.channel, "status": l.status, "records": l.records, "message": l.message,
                 "key": l.api_key_prefix} for l in logs],
        "channels": [{"channel": c, "records": int(n or 0), "last_at": iso(t)} for c, n, t in stats],
        "pubsub_configured": bool(os.getenv("PUBSUB_VERIFICATION_TOKEN")),
        "env_key_configured": bool(os.getenv("INTEGRATION_API_KEY")),
    }


@router.post("/keys", status_code=201)
def create_key(body: KeyCreate, s: Session = Depends(get_session), user: User = Depends(current_user)):
    _require_manager(user)
    scopes = [x for x in body.scopes if x in ("iot", "erp")] or ["iot"]
    k, raw = integrations.create_key(s, body.name, " ".join(scopes))
    from ..agents import audit
    audit(s, user.name or "Anonymous", user.role, "api_key_created", "api_key", str(k.id), f"{k.name} ({' '.join(scopes)})")
    s.commit()
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": scopes, "key": raw,
            "note": "Copy this key now. Only its hash is stored; it cannot be shown again."}


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: int, s: Session = Depends(get_session), user: User = Depends(current_user)):
    _require_manager(user)
    k = s.get(db.ApiKey, key_id)
    if not k:
        raise HTTPException(404, "Key not found")
    k.revoked = True
    from ..agents import audit
    audit(s, user.name or "Anonymous", user.role, "api_key_revoked", "api_key", str(k.id), k.name)
    s.commit()
