"""File storage for uploads, inspection photos and trained models.

STORAGE_BACKEND / GCS_BUCKET select where files go:
  * GCS_BUCKET set            -> Google Cloud Storage            (gs://bucket/path)
  * STORAGE_BACKEND=db        -> inside the database (stored_files table, db://path)
                                 use on hosts whose disk is wiped on restart (e.g. Render free tier)
  * otherwise                 -> local folder LOCAL_STORAGE_DIR   (local://path)
"""
from __future__ import annotations

import os
from pathlib import Path

_BUCKET = os.getenv("GCS_BUCKET")
_BACKEND = "gcs" if _BUCKET else os.getenv("STORAGE_BACKEND", "local").strip().lower()
_LOCAL = Path(os.getenv("LOCAL_STORAGE_DIR", "local_storage"))
_client = None


def _gcs():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client


def save(path: str, data: bytes, content_type: str) -> str:
    if _BACKEND == "gcs":
        _gcs().bucket(_BUCKET).blob(path).upload_from_string(data, content_type=content_type)
        return f"gs://{_BUCKET}/{path}"
    if _BACKEND == "db":
        from . import db
        with db.SessionLocal() as s:
            row = s.get(db.StoredFile, path) or db.StoredFile(path=path)
            row.content_type, row.data = content_type, data
            s.add(row)
            s.commit()
        return f"db://{path}"
    target = _LOCAL / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return f"local://{path}"


def load(uri: str) -> bytes:
    if uri.startswith("gs://"):
        bucket, _, path = uri[5:].partition("/")
        return _gcs().bucket(bucket).blob(path).download_as_bytes()
    if uri.startswith("db://"):
        from . import db
        with db.SessionLocal() as s:
            row = s.get(db.StoredFile, uri[5:])
            if row is None:
                raise FileNotFoundError(uri)
            return bytes(row.data)
    if uri.startswith("local://"):
        p = (_LOCAL / uri[8:]).resolve()
        if _LOCAL.resolve() not in p.parents:
            raise ValueError("Invalid path")
        return p.read_bytes()
    raise ValueError("Unknown storage URI")


def backend_name() -> str:
    return f"gcs:{_BUCKET}" if _BACKEND == "gcs" else _BACKEND
