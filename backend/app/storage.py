"""File storage: Google Cloud Storage when GCS_BUCKET is set, otherwise a local folder."""
from __future__ import annotations

import os
from pathlib import Path

_BUCKET = os.getenv("GCS_BUCKET")
_LOCAL = Path(os.getenv("LOCAL_STORAGE_DIR", "local_storage"))
_client = None


def _bucket():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client.bucket(_BUCKET)


def save(path: str, data: bytes, content_type: str) -> str:
    if _BUCKET:
        blob = _bucket().blob(path)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{_BUCKET}/{path}"
    target = _LOCAL / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return f"local://{path}"


def load(uri: str) -> bytes:
    if uri.startswith("gs://"):
        bucket, _, path = uri[5:].partition("/")
        from google.cloud import storage
        global _client
        if _client is None:
            _client = storage.Client()
        return _client.bucket(bucket).blob(path).download_as_bytes()
    if uri.startswith("local://"):
        p = (_LOCAL / uri[8:]).resolve()
        if _LOCAL.resolve() not in p.parents:
            raise ValueError("Invalid path")
        return p.read_bytes()
    raise ValueError("Unknown storage URI")


def backend_name() -> str:
    return f"gcs:{_BUCKET}" if _BUCKET else "local"
