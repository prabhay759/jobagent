"""
JobAgent - Pipeline Orchestrator
Coordinates the full job application lifecycle.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

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
        self.notifier = WhatsAppNotifier(settings.whatsapp)

    # ─── Full Scan Pipeline ────────────────────────────────────

    async def run(self) -> None:
        """Execute the full scan → analyze → notify → CV → apply loop."""
        logger.info(
            "Pipeline start | keywords=%s | locations=%s",
            self.settings.search.keywords,
            self.settings.search.locations,
        )

        scan_id = self.tracker.begin_scan()
        found = 0
        new_jobs = 0

        async def on_found(job: dict) -> None:
            nonlocal found, new_jobs
            found += 1
            is_new = self.tracker.upsert_job(job)
            if is_new:
                new_jobs += 1
                await self.process_job(job)

        try:
            await self.scanner.scan(on_job_found=on_found)
        finally:
            self.tracker.end_scan(scan_id, found, new_jobs)

        stats = self.tracker.get_stats()
        logger.info(
            "Pipeline done | found=%d new=%d | applied=%d | AI cost: %s",
            found, new_jobs, stats["applied"], self.ai.usage.summary(),
        )

    # ─── Single Job Pipeline ───────────────────────────────────

    async def process_job(self, job: dict) -> None:
        """Run the full pipeline for one job."""
        job_id = job["id"]
        app_cfg = self.settings.application

        # ── 1. AI Analysis ───────────────────────────────────
        try:
            analysis = self.ai.analyze_fit(job.get("description", ""), self.profile)
        except Exception as exc:
            logger.error("Analysis failed for %s: %s", job_id, exc)
            analysis = {"score": 0, "recommendation": "skip"}

        job["match_score"] = analysis.get("score", 0)
        job["ai_analysis"] = analysis
        self.tracker.save_analysis(job_id, analysis)
        self.tracker.set_status(job_id, "analyzed")

        score = analysis.get("score", 0)
        threshold = self.settings.search.min_match_score

        if score < threshold or analysis.get("recommendation") == "skip":
            logger.info(
                "Skipping %s @ %s (score=%d threshold=%d rec=%s)",
                job.get("title"), job.get("company"),
                score, threshold, analysis.get("recommendation"),
            )
            self.tracker.set_status(job_id, "skipped",
                f"score={score} threshold={threshold}")
            return

        # ── 2. WhatsApp Approval ─────────────────────────────
        if app_cfg.require_whatsapp_approval:
            self.tracker.set_status(job_id, "pending_approval")
            message = self.ai.whatsapp_summary(job, analysis)
            decision = await self.notifier.request_approval(job, message)

            if decision in ("NO", "TIMEOUT", "SKIP"):
                self.tracker.set_status(job_id, "skipped", f"WhatsApp: {decision}")
                return

            if decision == "INFO":
                # Let user ask questions, then re-confirm
                await self.notifier.notify(
                    f"ℹ️ You can ask questions about *{job['title']}* at *{job['company']}* "
                    f"in the dashboard chat.\n\nReply *YES* when ready to apply or *NO* to skip."
                )
                decision = await self.notifier.request_approval(
                    job, f"Apply to {job['title']} @ {job['company']}? Reply YES or NO."
                )
                if decision != "YES":
                    self.tracker.set_status(job_id, "skipped", "Declined after INFO")
                    return

        if not app_cfg.auto_apply:
            self.tracker.set_status(job_id, "ready_to_apply")
            logger.info("Auto-apply disabled — job queued for manual apply: %s", job_id)
            return

        # ── 3. Generate CV ────────────────────────────────────
        cv_path: Optional[str] = None
        try:
            path, _ = await self.cv_gen.generate(job, self.profile)
            cv_path = str(path)
            self.tracker.update_job(job_id, cv_path=cv_path)
        except Exception as exc:
            logger.error("CV generation failed: %s", exc)

        # ── 4. Cover Letter ───────────────────────────────────
        cover_letter = ""
        if app_cfg.cover_letter:
            try:
                tone = self.profile.get("cover_letter_tone", "confident and specific")
                cover_letter = self.ai.generate_cover_letter(
                    job, self.profile, analysis, tone
                )
                self.tracker.update_job(job_id, cover_letter=cover_letter)
            except Exception as exc:
                logger.error("Cover letter failed: %s", exc)

        # ── 5. Apply ─────────────────────────────────────────
        applied = False
        if job.get("easy_apply"):
            applied = await self._run_easy_apply(job, cover_letter)
        else:
            applied = await self._run_external_apply(job, cover_letter)

        if applied:
            self.tracker.set_status(job_id, "applied")
            self.tracker.update_job(job_id, applied_at=datetime.utcnow().isoformat())
            await self.notifier.notify(
                f"✅ Applied to *{job['title']}* at *{job['company']}*!"
            )
        else:
            self.tracker.set_status(job_id, "apply_failed")
            await self.notifier.notify(
                f"⚠️ Auto-apply failed for *{job['title']}* at *{job['company']}*.\n"
                f"Please apply manually: {job.get('url', '')}"
            )

    # ─── Chat (Dashboard) ──────────────────────────────────────

    def chat(self, job_id: str, message: str) -> str:
        """Handle a chat message about a job. Used by the dashboard API."""
        job = self.tracker.get_job(job_id)
        if not job:
            return "Job not found."
        history = self.tracker.get_messages(job_id)
        response = self.ai.chat(message, job, self.profile, history)
        self.tracker.add_message(job_id, "user", message)
        self.tracker.add_message(job_id, "assistant", response)
        return response

    # ─── Apply Helpers ─────────────────────────────────────────

    async def _run_easy_apply(self, job: dict, cover_letter: str) -> bool:
        handler = EasyApplyHandler(self.ai, self.profile)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)  # Visible for safety
            context = await browser.new_context()
            page = await context.new_page()
            result = await handler.apply(page, job, cover_letter)
            await browser.close()
        return result

    async def _run_external_apply(self, job: dict, cover_letter: str) -> bool:
        """
        Best-effort external form filler.
        Opens the page visibly so the user can intervene if needed.
        """
        logger.info("External apply: %s", job.get("url"))
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            page = await browser.new_page()
            try:
                await page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                for selector in [
                    'a:text("Apply Now")', 'a:text("Apply")',
                    'button:text("Apply Now")', 'button:text("Apply")',
                    '[class*="apply-btn"]',
                ]:
                    btn = await page.query_selector(selector)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(3)
                        break

                # External forms are too site-specific for fully automated filling.
                # We open the browser so the user can complete manually.
                logger.info(
                    "External apply opened — complete manually in the browser window"
                )
                await asyncio.sleep(60)  # Give user 60s to interact
            finally:
                await browser.close()

        return False  # Mark failed until confirmed by user
