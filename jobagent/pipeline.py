"""
JobAgent - Pipeline Orchestrator
Scan → Analyze → WhatsApp approval → Generate CV+CL → Preview → Apply
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from jobagent.agent.ai_client import AIClient
from jobagent.agent.easy_apply import EasyApplyHandler
from jobagent.agent.scanner import LinkedInScanner
from jobagent.cv.generator import CVGenerator
from jobagent.db.tracker import JobTracker
from jobagent.logging_config import get_logger
from jobagent.notifier.whatsapp import WhatsAppNotifier
from jobagent.settings import Settings

logger = get_logger(__name__)


class Pipeline:
    def __init__(self, settings: Settings, profile: dict) -> None:
        self.settings = settings
        self.profile = profile

        self.tracker = JobTracker(settings.database.path)
        self.ai = AIClient(
            api_key=settings.anthropic.api_key.get_secret_value(),
            model=settings.anthropic.model,
        )
        self.scanner = LinkedInScanner(settings.linkedin, settings.search)
        self.cv_gen = CVGenerator(settings.cv, self.ai)
        self.notifier = WhatsAppNotifier(
            settings.whatsapp,
            dashboard_host=settings.dashboard.host,
            dashboard_port=settings.dashboard.port,
        )

    # ── Full Scan ──────────────────────────────────────────────

    async def run(self) -> None:
        logger.info("Pipeline start | keywords=%s | locations=%s",
                    self.settings.search.keywords, self.settings.search.locations)
        scan_id = self.tracker.begin_scan()
        found = new_jobs = 0

        async def on_found(job: dict) -> None:
            nonlocal found, new_jobs
            found += 1
            if self.tracker.upsert_job(job):
                new_jobs += 1
                await self.process_job(job)

        try:
            await self.scanner.scan(on_job_found=on_found)
        finally:
            self.tracker.end_scan(scan_id, found, new_jobs)

        stats = self.tracker.get_stats()
        logger.info("Done | found=%d new=%d applied=%d | %s",
                    found, new_jobs, stats["applied"], self.ai.usage.summary())

    # ── Single Job ─────────────────────────────────────────────

    async def process_job(self, job: dict) -> None:
        """
        Full pipeline for one job:
          1. AI analysis + score gate
          2. WhatsApp: "Found a job — apply?" (YES/NO/INFO)
          3. Generate tailored CV + cover letter
          4. WhatsApp: "Here's your CV+CL — SEND/EDIT/SKIP"   ← NEW
          5. Apply (Easy Apply or external)
        """
        job_id = job["id"]
        app_cfg = self.settings.application

        # ── 1. Analysis ──────────────────────────────────────
        try:
            analysis = self.ai.analyze_fit(job.get("description", ""), self.profile)
        except Exception as exc:
            logger.error("Analysis failed: %s", exc)
            analysis = {"score": 0, "recommendation": "skip"}

        job["match_score"] = analysis.get("score", 0)
        job["ai_analysis"] = analysis
        self.tracker.save_analysis(job_id, analysis)
        self.tracker.set_status(job_id, "analyzed")

        score = analysis.get("score", 0)
        threshold = self.settings.search.min_match_score

        if score < threshold or analysis.get("recommendation") == "skip":
            logger.info("Skipping %s (score=%d < %d)", job.get("title"), score, threshold)
            self.tracker.set_status(job_id, "skipped", f"score={score}")
            return

        # ── 2. WhatsApp: Job Approval ────────────────────────
        if app_cfg.require_whatsapp_approval:
            self.tracker.set_status(job_id, "pending_approval")
            message = self.ai.whatsapp_summary(job, analysis)
            decision = await self.notifier.request_approval(job, message)

            if decision in ("NO", "TIMEOUT", "SKIP"):
                self.tracker.set_status(job_id, "skipped", f"WhatsApp job gate: {decision}")
                return

            if decision == "INFO":
                await self.notifier.notify(
                    f"ℹ️ Open the dashboard to chat about this job:\n"
                    f"{self.notifier.dashboard_base}/jobs/{job_id}\n\n"
                    f"Reply *YES* when ready to proceed, or *NO* to skip."
                )
                decision = await self.notifier.request_approval(
                    job, f"Ready to apply to {job['title']} @ {job['company']}? Reply YES or NO.")
                if decision != "YES":
                    self.tracker.set_status(job_id, "skipped", "Declined after INFO")
                    return

        if not app_cfg.auto_apply:
            self.tracker.set_status(job_id, "ready_to_apply")
            return

        # ── 3. Generate CV + Cover Letter ────────────────────
        logger.info("Generating CV + cover letter for %s @ %s…",
                    job.get("title"), job.get("company"))
        cv_path: Path | None = None
        cover_letter = ""

        try:
            path, _ = await self.cv_gen.generate(job, self.profile)
            cv_path = path
            self.tracker.update_job(job_id, cv_path=str(cv_path))
        except Exception as exc:
            logger.error("CV generation failed: %s", exc)

        if app_cfg.cover_letter:
            try:
                tone = self.profile.get("cover_letter_tone", "confident and specific")
                cover_letter = self.ai.generate_cover_letter(job, self.profile, analysis, tone)
                self.tracker.update_job(job_id, cover_letter=cover_letter)
            except Exception as exc:
                logger.error("Cover letter failed: %s", exc)

        # ── 4. WhatsApp: Preview Gate (CV + Cover Letter) ────
        if app_cfg.require_whatsapp_approval:
            self.tracker.set_status(job_id, "pending_preview")
            preview_decision = await self.notifier.request_preview_approval(
                job, cv_path, cover_letter
            )

            if preview_decision in ("SKIP", "NO", "TIMEOUT"):
                self.tracker.set_status(job_id, "skipped", f"Preview rejected: {preview_decision}")
                return

            if preview_decision == "EDIT":
                # Mark for manual revision — user edits in dashboard, re-triggers from there
                self.tracker.set_status(job_id, "pending_edit")
                await self.notifier.notify(
                    f"✏️ Revision mode opened for *{job['title']}*.\n"
                    f"Edit your CV and cover letter here:\n"
                    f"{self.notifier.dashboard_base}/jobs/{job_id}/edit\n\n"
                    f"When done, click *Submit Application* in the dashboard."
                )
                return  # Dashboard will re-trigger _apply() when user confirms

            # SEND — proceed to submission
            logger.info("Preview approved — submitting application")

        # ── 5. Apply ─────────────────────────────────────────
        await self._apply(job, cv_path, cover_letter)

    # ── Apply (reusable — called from dashboard too) ───────────

    async def _apply(self, job: dict, cv_path: Path | None, cover_letter: str) -> None:
        """Submit the application. Called after preview approval."""
        job_id = job["id"]
        applied = False

        if job.get("easy_apply"):
            applied = await self._easy_apply(job, cover_letter)
        else:
            applied = await self._external_apply(job, cover_letter)

        if applied:
            self.tracker.set_status(job_id, "applied")
            self.tracker.update_job(job_id, applied_at=datetime.utcnow().isoformat())
            await self.notifier.notify(
                f"✅ Applied to *{job['title']}* at *{job['company']}*!"
            )
        else:
            self.tracker.set_status(job_id, "apply_failed")
            await self.notifier.notify(
                f"⚠️ Auto-apply failed for *{job['title']}* @ *{job['company']}*.\n"
                f"Apply manually: {job.get('url', '')}"
            )

    # ── Dashboard APIs ─────────────────────────────────────────

    def chat(self, job_id: str, message: str) -> str:
        job = self.tracker.get_job(job_id)
        if not job:
            return "Job not found."
        history = self.tracker.get_messages(job_id)
        response = self.ai.chat(message, job, self.profile, history)
        self.tracker.add_message(job_id, "user", message)
        self.tracker.add_message(job_id, "assistant", response)
        return response

    async def regenerate_cv(self, job_id: str) -> Path | None:
        """Re-generate the CV for a job (called from dashboard edit flow)."""
        job = self.tracker.get_job(job_id)
        if not job:
            return None
        path, _ = await self.cv_gen.generate(job, self.profile)
        self.tracker.update_job(job_id, cv_path=str(path))
        return path

    async def regenerate_cover_letter(self, job_id: str, instructions: str = "") -> str:
        """Re-generate cover letter, optionally with revision instructions."""
        job = self.tracker.get_job(job_id)
        if not job:
            return ""
        analysis = job.get("ai_analysis") or {}
        if instructions:
            tone = f"confident and specific. Additional instructions: {instructions}"
        else:
            tone = self.profile.get("cover_letter_tone", "confident and specific")
        cl = self.ai.generate_cover_letter(job, self.profile, analysis, tone)
        self.tracker.update_job(job_id, cover_letter=cl)
        return cl

    async def submit_after_edit(self, job_id: str) -> bool:
        """Called from dashboard when user clicks Submit after editing."""
        job = self.tracker.get_job(job_id)
        if not job:
            return False
        cv_path = Path(job["cv_path"]) if job.get("cv_path") else None
        cover_letter = job.get("cover_letter", "")
        await self._apply(job, cv_path, cover_letter)
        return True

    # ── Private Apply Helpers ──────────────────────────────────

    async def _easy_apply(self, job: dict, cover_letter: str) -> bool:
        handler = EasyApplyHandler(self.ai, self.profile)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            page = await (await browser.new_context()).new_page()
            result = await handler.apply(page, job, cover_letter)
            await browser.close()
        return result

    async def _external_apply(self, job: dict, cover_letter: str) -> bool:
        logger.info("External apply: %s", job.get("url"))
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            page = await browser.new_page()
            try:
                await page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                for sel in ['a:text("Apply Now")', 'a:text("Apply")',
                            'button:text("Apply Now")', 'button:text("Apply")']:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(3)
                        break
                logger.info("External apply open — complete in browser window")
                await asyncio.sleep(60)
            finally:
                await browser.close()
        return False
