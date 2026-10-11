"""IoT / ERP integration helpers: API keys, Pub/Sub envelopes, ingestion logging.

Endpoints (see routers/integrations.py):
  POST /api/integrations/iot/telemetry       X-API-Key   one reading or a list of readings
  POST /api/integrations/iot/events          X-API-Key   failure / maintenance events
  POST /api/integrations/pubsub/push?token=  Pub/Sub push subscription (telemetry or events in message.data)
  POST /api/integrations/erp/work-orders     X-API-Key   upsert work orders
  POST /api/integrations/erp/production      X-API-Key   production records -> new dataset
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

import sqlalchemy as sa
from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from . import db


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(s: Session, name: str, scopes: str = "iot erp") -> tuple[db.ApiKey, str]:
    raw = "sfk_" + secrets.token_urlsafe(32)
    k = db.ApiKey(name=name, prefix=raw[:12], key_hash=_hash(raw), scopes=scopes)
    s.add(k)
    s.commit()
    return k, raw


def verify_key(s: Session, raw: str | None, scope: str) -> db.ApiKey | str:
    """Accepts a DB-managed key, or the INTEGRATION_API_KEY environment variable (bootstrap key)."""
    if not raw:
        raise HTTPException(401, "Missing X-API-Key header.")
    env_key = os.getenv("INTEGRATION_API_KEY")
    if env_key and hmac.compare_digest(raw, env_key):
        return "env"
    k = s.scalars(sa.select(db.ApiKey).where(db.ApiKey.key_hash == _hash(raw))).first()
    if not k or k.revoked:
        raise HTTPException(401, "Invalid or revoked API key.")
    if scope not in k.scopes.split():
        raise HTTPException(403, f"API key does not have the '{scope}' scope.")
    k.last_used_at = db.utcnow()
    return k


def log(s: Session, channel: str, status: str, records: int, message: str, key: db.ApiKey | str | None) -> None:
    prefix = key.prefix if isinstance(key, db.ApiKey) else key
    s.add(db.IntegrationLog(channel=channel, status=status, records=records, message=message[:500], api_key_prefix=prefix))
    s.commit()


def verify_pubsub_token(token: str | None) -> None:
    expected = os.getenv("PUBSUB_VERIFICATION_TOKEN")
    if not expected:
        raise HTTPException(503, "Pub/Sub push is not configured (set PUBSUB_VERIFICATION_TOKEN).")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "Invalid Pub/Sub verification token.")


def decode_pubsub(envelope: dict) -> tuple[dict | list, dict]:
    msg = (envelope or {}).get("message") or {}
    data = msg.get("data")
    if not data:
        raise HTTPException(400, "Pub/Sub message has no data.")
    try:
        payload = json.loads(base64.b64decode(data).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Pub/Sub data is not base64 JSON ({type(e).__name__}).")
    return payload, msg.get("attributes") or {}


def api_key_header(x_api_key: str | None = Header(default=None)) -> str | None:
    return x_api_key
