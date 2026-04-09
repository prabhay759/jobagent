"""
JobAgent - Dashboard API Server
FastAPI serving REST API + static file serving for CV PDFs.
"""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from threading import Thread
from typing import Optional

import uvicorn
import yaml
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


def create_app(settings: Settings, profile: dict) -> FastAPI:
    app = FastAPI(title="JobAgent", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    tracker = JobTracker(settings.database.path)
    pipeline = Pipeline(settings, profile)
    state = {"scan_running": False}

    # ── Jobs ───────────────────────────────────────────────────

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
            raise HTTPException(404, "Job not found")
        return job

    class StatusUpdate(BaseModel):
        status: str
        note: str = ""

    @app.patch("/api/jobs/{job_id}/status")
    def update_status(job_id: str, body: StatusUpdate):
        tracker.set_status(job_id, body.status, body.note)
        return {"ok": True}

    # ── CV & Cover Letter ──────────────────────────────────────

    @app.get("/api/jobs/{job_id}/cv")
    def download_cv(job_id: str):
        job = tracker.get_job(job_id)
        if not job or not job.get("cv_path"):
            raise HTTPException(404, "CV not generated yet")
        p = Path(job["cv_path"])
        if not p.exists():
            raise HTTPException(404, "CV file missing from disk")
        return FileResponse(str(p), media_type="application/pdf", filename=p.name)

    @app.get("/api/jobs/{job_id}/cover-letter")
    def get_cover_letter(job_id: str):
        return {"cover_letter": tracker.get_cover_letter(job_id)}

    class CoverLetterUpdate(BaseModel):
        cover_letter: str

    @app.put("/api/jobs/{job_id}/cover-letter")
    def save_cover_letter(job_id: str, body: CoverLetterUpdate):
        """Save manually edited cover letter."""
        tracker.save_cover_letter(job_id, body.cover_letter)
        return {"ok": True}

    class RegenerateRequest(BaseModel):
        instructions: str = ""

    @app.post("/api/jobs/{job_id}/cover-letter/regenerate")
    async def regenerate_cover_letter(job_id: str, body: RegenerateRequest):
        """Ask AI to rewrite cover letter, optionally with instructions."""
        if not tracker.get_job(job_id):
            raise HTTPException(404, "Job not found")
        try:
            new_cl = await pipeline.regenerate_cover_letter(job_id, body.instructions)
            return {"cover_letter": new_cl}
        except Exception as exc:
            raise HTTPException(500, str(exc))

    @app.post("/api/jobs/{job_id}/cv/regenerate")
    async def regenerate_cv(job_id: str):
        """Re-generate CV PDF for a job."""
        if not tracker.get_job(job_id):
            raise HTTPException(404, "Job not found")
        try:
            path = await pipeline.regenerate_cv(job_id)
            return {"cv_path": str(path)}
        except Exception as exc:
            raise HTTPException(500, str(exc))

    # ── Submit after Edit ──────────────────────────────────────

    @app.post("/api/jobs/{job_id}/submit")
    async def submit_after_edit(job_id: str):
        """Called from dashboard when user approves and clicks Submit."""
        if not tracker.get_job(job_id):
            raise HTTPException(404, "Job not found")
        ok = await pipeline.submit_after_edit(job_id)
        return {"ok": ok}

    # ── File Serving (for Twilio MMS) ──────────────────────────

    @app.get("/api/files/{filename}")
    def serve_file(filename: str):
        """Serve generated output files (CV PDFs) — used by Twilio MMS."""
        # Security: only serve files from output/cvs
        output_dir = settings.cv.output_dir
        file_path = output_dir / filename
        if not file_path.exists() or not file_path.is_relative_to(output_dir):
            raise HTTPException(404, "File not found")
        return FileResponse(str(file_path), media_type="application/pdf")

    # ── Pending Approvals ──────────────────────────────────────

    @app.get("/api/pending-approvals")
    def pending_approvals():
        return tracker.list_pending_approval()

    # ── Chat ───────────────────────────────────────────────────

    class ChatRequest(BaseModel):
        message: str

    @app.post("/api/jobs/{job_id}/chat")
    def chat(job_id: str, body: ChatRequest):
        if not tracker.get_job(job_id):
            raise HTTPException(404, "Job not found")
        try:
            return {"response": pipeline.chat(job_id, body.message)}
        except Exception as exc:
            raise HTTPException(500, str(exc))

    @app.get("/api/jobs/{job_id}/chat/history")
    def chat_history(job_id: str):
        return tracker.get_messages(job_id)

    # ── Scan ───────────────────────────────────────────────────

    @app.post("/api/scan/start")
    async def start_scan(background_tasks: BackgroundTasks):
        if state["scan_running"]:
            return JSONResponse({"ok": False, "message": "Scan already running"}, status_code=409)
        state["scan_running"] = True

        async def _run():
            try:
                await pipeline.run()
            except Exception as exc:
                logger.error("Scan error: %s", exc)
            finally:
                state["scan_running"] = False

        background_tasks.add_task(_run)
        return {"ok": True}

    @app.get("/api/scan/status")
    def scan_status():
        return {"running": state["scan_running"]}

    # ── Static (React build) ───────────────────────────────────

    static_dir = Path(__file__).parent.parent.parent / "dashboard" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        @app.get("/")
        def root():
            return {"message": "JobAgent API — run: cd dashboard && npm run build"}

    return app


def run_server(config_path: str = "config/config.yaml",
               profile_path: str = "config/profile.yaml",
               open_browser: bool = True) -> None:
    setup_logging()
    settings = load_settings(config_path)
    with open(profile_path) as f:
        profile = yaml.safe_load(f)

    app = create_app(settings, profile)
    host, port = settings.dashboard.host, settings.dashboard.port
    logger.info("Dashboard: http://%s:%d", host, port)

    if open_browser and settings.dashboard.auto_open_browser:
        def _open():
            import time; time.sleep(1.5)
            webbrowser.open(f"http://{host}:{port}")
        Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
