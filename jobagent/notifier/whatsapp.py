"""
JobAgent - WhatsApp Notifier
Sends approval requests, document previews, and tracks replies.
Supports Twilio (recommended) and CallMeBot (free).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs

from jobagent.logging_config import get_logger
from jobagent.settings import WhatsAppSettings

logger = get_logger(__name__)

APPROVAL_YES   = frozenset({"YES", "Y", "APPLY", "GO", "OK", "1"})
APPROVAL_NO    = frozenset({"NO", "N", "SKIP", "PASS", "NOPE", "0"})
APPROVAL_INFO  = frozenset({"INFO", "?", "DETAILS", "MORE"})
APPROVAL_SEND  = frozenset({"SEND", "SUBMIT", "PROCEED", "S"})
APPROVAL_EDIT  = frozenset({"EDIT", "REVISE", "CHANGE", "E", "TWEAK"})


@dataclass
class PendingRequest:
    job_id: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str = "TIMEOUT"


class WhatsAppNotifier:
    def __init__(self, cfg: WhatsAppSettings, dashboard_host: str = "127.0.0.1",
                 dashboard_port: int = 8080) -> None:
        self.cfg = cfg
        self.dashboard_base = f"http://{dashboard_host}:{dashboard_port}"
        self._lock = threading.Lock()
        self._pending: dict[str, PendingRequest] = {}

        if cfg.provider == "twilio":
            self._start_webhook(cfg.webhook_port)

    # ── Public API ─────────────────────────────────────────────

    async def request_approval(self, job: dict, message: str) -> str:
        """Job found gate: YES / NO / INFO."""
        return await self._send_and_wait(job["id"], message)

    async def request_preview_approval(self, job: dict, cv_path: Optional[Path],
                                        cover_letter: str) -> str:
        """
        Preview gate: show CV + cover letter, ask SEND / EDIT / SKIP.
        Called after generation, before submission.
        Returns: 'SEND' | 'EDIT' | 'SKIP' | 'TIMEOUT'
        """
        job_id = job["id"]
        dashboard_url = f"{self.dashboard_base}/jobs/{job_id}"

        cl_preview = cover_letter[:500].strip()
        if len(cover_letter) > 500:
            cl_preview += "…"

        msg = (
            f"📄 *Preview — {job.get('title')} @ {job.get('company')}*\n\n"
            f"*Cover Letter:*\n_{cl_preview}_\n\n"
            f"📎 *CV PDF:* {dashboard_url}/cv\n"
            f"🔍 *Full preview + edit:* {dashboard_url}\n\n"
            f"Reply:\n"
            f"  *SEND* — looks good, submit now\n"
            f"  *EDIT* — revise in dashboard first\n"
            f"  *SKIP* — don't apply to this job"
        )

        # Send CV as MMS attachment if using Twilio
        if cv_path and cv_path.exists() and self.cfg.provider == "twilio":
            await self._send_with_media(
                body=f"📄 Your tailored CV for {job.get('title')} @ {job.get('company')}",
                media_path=cv_path,
            )

        return await self._send_and_wait(job_id, msg)

    async def notify(self, message: str) -> None:
        """Plain notification, no reply needed."""
        await self._send(message)

    def handle_reply(self, body: str) -> None:
        """Called by webhook when a WhatsApp reply arrives."""
        text = body.strip().upper()
        logger.info("WhatsApp reply: '%s'", text)

        if text in APPROVAL_YES:
            decision = "YES"
        elif text in APPROVAL_NO or text == "SKIP":
            decision = "NO"
        elif text in APPROVAL_INFO:
            decision = "INFO"
        elif text in APPROVAL_SEND:
            decision = "SEND"
        elif text in APPROVAL_EDIT:
            decision = "EDIT"
        else:
            decision = text

        with self._lock:
            if not self._pending:
                logger.debug("No pending requests, ignoring reply")
                return
            req = next(iter(self._pending.values()))
            req.decision = decision
            req.event.set()

    # ── Internal ───────────────────────────────────────────────

    async def _send_and_wait(self, job_id: str, message: str) -> str:
        req = PendingRequest(job_id=job_id)
        with self._lock:
            self._pending[job_id] = req

        sent = await self._send(message)
        if not sent:
            logger.warning("Send failed — skipping")
            with self._lock:
                self._pending.pop(job_id, None)
            return "SKIP"

        logger.info("Waiting up to %dm for reply…", self.cfg.approval_timeout_minutes)
        try:
            await asyncio.wait_for(req.event.wait(),
                                    timeout=self.cfg.approval_timeout_minutes * 60)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for reply (job %s)", job_id)

        with self._lock:
            decision = req.decision
            self._pending.pop(job_id, None)

        logger.info("Decision: %s", decision)
        return decision

    async def _send(self, message: str) -> bool:
        if self.cfg.provider == "twilio":
            return await asyncio.get_event_loop().run_in_executor(
                None, self._twilio_sync, message, None)
        elif self.cfg.provider == "callmebot":
            return await self._callmebot(message)
        else:
            logger.info("[MOCK WhatsApp]\n%s", message)
            return True

    async def _send_with_media(self, body: str, media_path: Path) -> bool:
        """Attach CV PDF as MMS via Twilio. Requires publicly reachable dashboard URL."""
        if self.cfg.provider != "twilio":
            logger.info("[MOCK] Would send media: %s", media_path.name)
            return True
        media_url = f"{self.dashboard_base}/api/files/{media_path.name}"
        return await asyncio.get_event_loop().run_in_executor(
            None, self._twilio_sync, body, media_url)

    def _twilio_sync(self, body: str, media_url: Optional[str] = None) -> bool:
        try:
            from twilio.rest import Client
            t = self.cfg.twilio
            client = Client(t.account_sid, t.auth_token.get_secret_value())
            kwargs: dict = dict(from_=t.from_number, to=t.to_number, body=body)
            if media_url:
                kwargs["media_url"] = [media_url]
            client.messages.create(**kwargs)
            return True
        except ImportError:
            logger.error("pip install twilio")
            return False
        except Exception as exc:
            logger.error("Twilio error: %s", exc)
            return False

    async def _callmebot(self, message: str) -> bool:
        try:
            import urllib.parse, urllib.request
            cb = self.cfg.callmebot  # type: ignore
            url = (f"https://api.callmebot.com/whatsapp.php"
                   f"?phone={cb.phone}&text={urllib.parse.quote(message)}&apikey={cb.apikey}")
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: urllib.request.urlopen(url, timeout=10))
            return True
        except Exception as exc:
            logger.error("CallMeBot error: %s", exc)
            return False

    def _start_webhook(self, port: int) -> None:
        notifier = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                notifier.handle_reply(parse_qs(body).get("Body", [""])[0])
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        def _run():
            try:
                HTTPServer(("0.0.0.0", port), Handler).serve_forever()
            except OSError as exc:
                logger.warning("Webhook error: %s", exc)

        threading.Thread(target=_run, daemon=True, name="wa-webhook").start()
        logger.info("Twilio webhook on port %d", port)
