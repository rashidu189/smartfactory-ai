"""SmartFactory AI - FastAPI application (REST API + Angular frontend hosting)."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, db, kpis, storage
from .routers import demo, integrations, plant, production, workflows
from .validation import OPTIONAL_COLUMNS, REQUIRED_COLUMNS, ValidationError

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("smartfactory")

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = Path(os.getenv("FRONTEND_DIR", ROOT.parent / "frontend" / "dist" / "smartfactory-ui"))


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    log.info("Database: %s | Storage: %s | Gemini configured: %s", db.backend_name(), storage.backend_name(), ai.is_configured())
    yield


app = FastAPI(title="SmartFactory AI", version="0.3.0", lifespan=lifespan,
              description="Intelligent manufacturing assistant: KPIs, anomalies, ML failure prediction, bottleneck "
                          "forecasting, Gemini insights / copilot / agents, approvals and IoT/ERP integrations.")


@app.exception_handler(ValidationError)
async def _validation_handler(_, exc: ValidationError):
    return JSONResponse(status_code=422, content={"error": exc.message, "details": exc.details})


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    return {"gemini_configured": ai.is_configured(), "model": ai.model_name() if ai.is_configured() else None,
            "vertex_ai": os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true"),
            "database": db.backend_name(), "storage": storage.backend_name(),
            "required_columns": REQUIRED_COLUMNS, "optional_columns": OPTIONAL_COLUMNS,
            "thresholds": kpis.asdict(kpis.Thresholds()),
            "roles": [{"id": "operator", "label": "Operator"}, {"id": "engineer", "label": "Engineer"},
                      {"id": "supervisor", "label": "Supervisor"}, {"id": "plant_manager", "label": "Plant manager"}]}


for r in (production.router, plant.router, workflows.router, integrations.router, demo.router):
    app.include_router(r)


# ---------------- Angular frontend ----------------

if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets", check_dir=False), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (FRONTEND / path).resolve()
        if path and f.is_file() and FRONTEND.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(FRONTEND / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return {"message": "API running. Build the Angular app (frontend/) or open /docs for the API."}
