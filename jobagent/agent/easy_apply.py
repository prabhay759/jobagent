"""
JobAgent - Easy Apply Handler
Fills LinkedIn Easy Apply multi-step forms using AI.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeoutError

from jobagent.logging_config import get_logger

if TYPE_CHECKING:
    from jobagent.agent.ai_client import AIClient

logger = get_logger(__name__)


class EasyApplyHandler:
    MAX_STEPS = 12

    def __init__(self, ai: AIClient, profile: dict) -> None:
        self.ai = ai
        self.profile = profile

    async def apply(self, page: Page, job: dict, cover_letter: str) -> bool:
        """
        Attempt LinkedIn Easy Apply.
        Returns True if application was successfully submitted.
        """
        try:
            await page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(1.5, 2.5))

            btn = await page.query_selector('button[aria-label*="Easy Apply"]')
            if not btn:
                logger.warning("Easy Apply button not found on %s", job["url"])
                return False

            await btn.click()
            await asyncio.sleep(1.5)

            for step in range(self.MAX_STEPS):
                logger.debug("Easy Apply step %d", step + 1)
                await self._fill_visible_fields(page, job, cover_letter)
                await asyncio.sleep(0.5)

                if await self._click_if_exists(page, 'button[aria-label="Submit application"]'):
                    await asyncio.sleep(2)
                    logger.info("✅ Applied via Easy Apply: %s @ %s", job["title"], job["company"])
                    return True

                if await self._click_if_exists(page, 'button[aria-label="Continue to next step"]'):
                    await asyncio.sleep(1)
                    continue

                review_selector = 'button[aria-label="Review your application"]'
                if await self._click_if_exists(page, review_selector):
                    await asyncio.sleep(1)
                    continue

                # No known button found — might be at a captcha or unsupported step
                logger.warning("Easy Apply stuck at step %d — no known button", step + 1)
                return False

            return False

        except PWTimeoutError:
            logger.warning("Easy Apply timed out for %s", job["url"])
            return False
        except Exception as exc:
            logger.error("Easy Apply error: %s", exc)
            return False

    async def _fill_visible_fields(self, page: Page, job: dict, cover_letter: str) -> None:
        """Fill all visible form inputs on the current step."""
        # Text inputs and textareas
        inputs = await page.query_selector_all(
            "input[type='text'], input[type='email'], input[type='tel'], "
            "input[type='number'], textarea"
        )
        for inp in inputs:
            if await inp.input_value():
                continue  # Already filled
            label = await self._label_for(inp, page)
            value = self._quick_fill(label, cover_letter) or await self._ai_fill(
                label, job, cover_letter
            )
            if value:
                await inp.fill(value)
                await asyncio.sleep(random.uniform(0.2, 0.5))

        # Native selects
        selects = await page.query_selector_all("select")
        for sel in selects:
            label = await self._label_for(sel, page)
            options = [await o.inner_text() for o in await sel.query_selector_all("option")]
            non_empty = [o for o in options if o.strip() and not o.strip().startswith("-")]
            if not non_empty:
                continue
            best = self.ai.answer_question(
                f"Which option best answers '{label}'? Options: {non_empty}. "
                "Reply with ONLY the exact option text.",
                job,
                self.profile,
            )
            with contextlib.suppress(Exception):
                await sel.select_option(label=best.strip())

    def _quick_fill(self, label: str, cover_letter: str) -> str:
        """Fast rule-based field filling without calling the API."""
        label_lower = label.lower()
        p = self.profile.get("personal", {})
        prefs = self.profile.get("preferences", {})

        rules = {
            ("name", "full name"): p.get("name", ""),
            ("email",): p.get("email", ""),
            ("phone", "mobile"): p.get("phone", ""),
            ("linkedin",): p.get("linkedin", ""),
            ("website", "portfolio", "github"): p.get("website", "") or p.get("github", ""),
            ("cover letter", "motivation", "why apply", "why are you"): cover_letter,
            ("salary", "ctc", "compensation", "expected"): str(prefs.get("min_salary_inr", "")),
            ("notice", "join", "start date", "available from"):
                prefs.get("notice_period", "60 days"),
            ("city", "current location"): p.get("location", ""),
        }
        for keys, value in rules.items():
            if any(k in label_lower for k in keys) and value:
                return value
        return ""

    async def _ai_fill(self, label: str, job: dict, cover_letter: str) -> str:
        """Use AI to fill fields that don't match simple rules."""
        if not label:
            return ""
        try:
            return self.ai.answer_question(label, job, self.profile)
        except Exception as exc:
            logger.debug("AI fill failed for '%s': %s", label, exc)
            return ""

    @staticmethod
    async def _label_for(element, page: Page) -> str:
        """Try to find the human-readable label for a form element."""
        try:
            el_id = await element.get_attribute("id")
            if el_id:
                lbl = await page.query_selector(f'label[for="{el_id}"]')
                if lbl:
                    return (await lbl.inner_text()).strip()
            return (
                (await element.get_attribute("aria-label") or "")
                or (await element.get_attribute("placeholder") or "")
                or (await element.get_attribute("name") or "")
            )
        except Exception:
            return ""

    @staticmethod
    async def _click_if_exists(page: Page, selector: str) -> bool:
        el = await page.query_selector(selector)
        if el:
            await el.click()
            return True
        return False
