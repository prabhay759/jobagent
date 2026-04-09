"""
JobAgent - WhatsApp Notifier
Sends approval requests and tracks YES/NO replies.
Supports Twilio (recommended) and CallMeBot (free).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs

from jobagent.logging_config import get_logger
from jobagent.settings import WhatsAppSettings

logger = get_logger(__name__)

APPROVAL_YES = frozenset({"YES", "Y", "APPLY", "GO", "OK", "1"})
APPROVAL_NO = frozenset({"NO", "N", "SKIP", "PASS", "NOPE", "0"})
APPROVAL_INFO = frozenset({"INFO", "?", "DETAILS", "MORE", "TELL ME MORE"})


@dataclass
class PendingRequest:
    job_id: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str = "TIMEOUT"


class WhatsAppNotifier:
    def __init__(self, cfg: WhatsAppSettings) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()
        self._pending: dict[str, PendingRequest] = {}

        if cfg.provider == "twilio":
            self._start_webhook(cfg.webhook_port)

    # ─── Public API ─────────────────────────────────────────────

    async def request_approval(self, job: dict, message: str) -> str:
        """
        Send WhatsApp message and wait for user response.
        Returns: "YES" | "NO" | "INFO" | "TIMEOUT"
        """
        job_id = job["id"]
        req = PendingRequest(job_id=job_id)

        with self._lock:
            self._pending[job_id] = req

        sent = await self._send(message)
        if not sent:
            logger.warning("WhatsApp send failed — defaulting to skip")
            return "SKIP"

        logger.info(
            "Waiting for WhatsApp approval (timeout: %dm)…",
            self.cfg.approval_timeout_minutes,
        )

        try:
            await asyncio.wait_for(
                req.event.wait(),
                timeout=self.cfg.approval_timeout_minutes * 60,
            )
        except asyncio.TimeoutError:
            logger.warning("Approval timed out for job %s", job_id)

        with self._lock:
            decision = req.decision
            self._pending.pop(job_id, None)

        logger.info("Approval decision: %s", decision)
        return decision

    async def notify(self, message: str) -> None:
        """Send a plain notification message."""
        await self._send(message)

    def handle_reply(self, body: str) -> None:
        """Process an incoming WhatsApp reply (called by webhook)."""
        text = body.strip().upper()
        logger.info("WhatsApp reply received: '%s'", text)

        if text in APPROVAL_YES:
            decision = "YES"
        elif text in APPROVAL_NO:
            decision = "NO"
        elif text in APPROVAL_INFO:
            decision = "INFO"
        else:
            decision = text  # Pass through unknown replies

        with self._lock:
            if not self._pending:
                logger.debug("No pending approvals — ignoring reply")
                return
            # Resolve the most recent pending request
            req = next(iter(self._pending.values()))
            req.decision = decision
            req.event.set()

    # ─── Send Backends ──────────────────────────────────────────

    async def _send(self, message: str) -> bool:
        provider = self.cfg.provider
        if provider == "twilio":
            return await asyncio.get_event_loop().run_in_executor(
                None, self._send_twilio_sync, message
            )
        elif provider == "callmebot":
            return await self._send_callmebot(message)
        else:
            logger.info("[MOCK WhatsApp]\n%s", message)
            return True

    def _send_twilio_sync(self, message: str) -> bool:
        try:
            from twilio.rest import Client

            t = self.cfg.twilio
            client = Client(t.account_sid, t.auth_token.get_secret_value())
            client.messages.create(
                from_=t.from_number, to=t.to_number, body=message
            )
            logger.info("WhatsApp message sent via Twilio")
            return True
        except ImportError:
            logger.error("twilio not installed: pip install twilio")
            return False
        except Exception as exc:
            logger.error("Twilio send failed: %s", exc)
            return False

    async def _send_callmebot(self, message: str) -> bool:
        try:
            import urllib.request, urllib.parse

            cb = self.cfg.callmebot  # type: ignore[attr-defined]
            encoded = urllib.parse.quote(message)
            url = f"https://api.callmebot.com/whatsapp.php?phone={cb.phone}&text={encoded}&apikey={cb.apikey}"
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: urllib.request.urlopen(url, timeout=10)
            )
            return True
        except Exception as exc:
            logger.error("CallMeBot send failed: %s", exc)
            return False

    # ─── Webhook Server ─────────────────────────────────────────

    def _start_webhook(self, port: int) -> None:
        notifier = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                params = parse_qs(body)
                reply_body = params.get("Body", [""])[0]
                notifier.handle_reply(reply_body)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        def _run():
            try:
                srv = HTTPServer(("0.0.0.0", port), Handler)
                logger.info("Twilio webhook listening on port %d", port)
                srv.serve_forever()
            except OSError as exc:
                logger.warning("Could not start webhook server: %s", exc)

        threading.Thread(target=_run, daemon=True, name="whatsapp-webhook").start()
