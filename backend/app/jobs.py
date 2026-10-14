"""Tiny in-process background jobs for long tasks (demo loading, model training).

Used so a request through a proxy with a ~100 s limit (e.g. Cloudflare) returns immediately;
the browser then polls GET /api/jobs/{id}. Jobs live in memory on the instance that runs them,
which is fine for a single-instance deployment (Render, one Cloud Run instance).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Callable

log = logging.getLogger("smartfactory.jobs")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def inline_mode() -> bool:
    """Run jobs inside the request instead of a background thread.
    Default ON for Cloud Run (K_SERVICE is set there): with request-based billing the CPU is throttled
    between requests, so a background thread would stall. Override with JOBS_INLINE=true/false."""
    v = os.getenv("JOBS_INLINE")
    if v is not None:
        return v.strip().lower() in ("1", "true", "yes")
    return bool(os.getenv("K_SERVICE"))


def start(name: str, fn: Callable[[], Any]) -> dict:
    if inline_mode():
        job = {"id": uuid.uuid4().hex[:12], "name": name, "status": "running", "started": time.time(),
               "finished": None, "result": None, "error": None}
        _jobs[job["id"]] = job
        try:
            job["result"], job["status"] = fn(), "done"
        except Exception as e:  # noqa: BLE001
            log.exception("Job %s failed", name)
            job["status"], job["error"] = "failed", getattr(e, "detail", None) or f"{type(e).__name__}: {e}"
        job["finished"] = time.time()
        return job
    with _lock:
        running = next((j for j in _jobs.values() if j["name"] == name and j["status"] == "running"), None)
        if running:
            return running        # don't start the same long job twice
        job = {"id": uuid.uuid4().hex[:12], "name": name, "status": "running", "started": time.time(),
               "finished": None, "result": None, "error": None}
        _jobs[job["id"]] = job

    def runner():
        try:
            job["result"] = fn()
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("Job %s failed", name)
            job["status"], job["error"] = "failed", getattr(e, "detail", None) or f"{type(e).__name__}: {e}"
        finally:
            job["finished"] = time.time()

    threading.Thread(target=runner, name=f"job-{name}", daemon=True).start()
    return job


def get(job_id: str) -> dict | None:
    j = _jobs.get(job_id)
    if not j:
        return None
    return {**j, "elapsed_s": round((j["finished"] or time.time()) - j["started"], 1)}
