"""
JobAgent - Dashboard API Server
FastAPI backend serving REST API + React dashboard.
"""

from __future__ import annotations

import asyncio
import json
import os
import webbrowser
from pathlib import Path
from threading import Thread
from typing import Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jobagent.db.tracker import JobTracker
from jobagent.logging_config import get_logger, setup_logging
from jobagent.pipeline import Pipeline
from jobagent.settings import Settings, load_settings

logger = get_logger(__name__)


# ─── App Factory ──────────────────────────────────────────────

def create_app(settings: Settings, profile: dict) -> FastAPI:
    app = FastAPI(
        title="JobAgent",
        version="1.0.0",
        description="AI-powered job application agent dashboard",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dashboard.cors_origins + ["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    tracker = JobTracker(settings.database.path)
    pipeline = Pipeline(settings, profile)
    state = {"scan_running": False}

    # ─── Jobs API ──────────────────────────────────────────────

    @app.get("/api/stats")
    def get_stats():
        return tracker.get_stats()

    @app.get("/api/jobs")
    def list_jobs(status: Optional[str] = None, limit: int = 200):
        return tracker.list_jobs(status=status, limit=limit)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = tracker.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    class StatusUpdate(BaseModel):
        status: str
        note: str = ""

    @app.patch("/api/jobs/{job_id}/status")
    def update_status(job_id: str, body: StatusUpdate):
        tracker.set_status(job_id, body.status, body.note)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/cv")
    def download_cv(job_id: str):
        job = tracker.get_job(job_id)
        if not job or not job.get("cv_path"):
            raise HTTPException(status_code=404, detail="CV not generated yet")
        cv_path = Path(job["cv_path"])
        if not cv_path.exists():
            raise HTTPException(status_code=404, detail="CV file not found on disk")
        return FileResponse(
            path=str(cv_path),
            media_type="application/pdf",
            filename=cv_path.name,
        )

    @app.get("/api/pending-approvals")
    def pending_approvals():
        return tracker.list_pending_approval()

    # ─── Chat API ──────────────────────────────────────────────

    class ChatRequest(BaseModel):
        message: str

    @app.post("/api/jobs/{job_id}/chat")
    def chat(job_id: str, body: ChatRequest):
        if not tracker.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")
        try:
            response = pipeline.chat(job_id, body.message)
            return {"response": response}
        except Exception as exc:
            logger.error("Chat error: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/jobs/{job_id}/chat/history")
    def chat_history(job_id: str):
        return tracker.get_messages(job_id)

    # ─── Scan API ──────────────────────────────────────────────

    @app.post("/api/scan/start")
    async def start_scan(background_tasks: BackgroundTasks):
        if state["scan_running"]:
            return JSONResponse({"ok": False, "message": "Scan already running"}, status_code=409)
        state["scan_running"] = True

        async def run():
            try:
                await pipeline.run()
            except Exception as exc:
                logger.error("Scan error: %s", exc)
            finally:
                state["scan_running"] = False

        background_tasks.add_task(run)
        return {"ok": True, "message": "Scan started"}

    @app.get("/api/scan/status")
    def scan_status():
        return {"running": state["scan_running"]}

    # ─── Static Files (Production React Build) ─────────────────

    static_dir = Path(__file__).parent.parent / "dashboard" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        @app.get("/")
        def root():
            return {"message": "JobAgent API running. Frontend not built yet — run: cd dashboard && npm run build"}

    return app


def run_server(
    config_path: str = "config/config.yaml",
    profile_path: str = "config/profile.yaml",
    open_browser: bool = True,
) -> None:
    import yaml

    setup_logging()
    settings = load_settings(config_path)

    with open(profile_path) as f:
        profile = yaml.safe_load(f)

    app = create_app(settings, profile)
    host = settings.dashboard.host
    port = settings.dashboard.port

    logger.info("Dashboard: http://%s:%d", host, port)

    if open_browser and settings.dashboard.auto_open_browser:
        def _open():
            import time; time.sleep(1.5)
            webbrowser.open(f"http://{host}:{port}")
        Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
