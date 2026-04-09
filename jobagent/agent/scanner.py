"""
JobAgent - LinkedIn Scanner
Playwright-based LinkedIn job scanner with stealth mode and rate limiting.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PWTimeoutError,
)

from jobagent.logging_config import get_logger
from jobagent.settings import LinkedInSettings, SearchSettings

logger = get_logger(__name__)

_LINKEDIN_BASE = "https://www.linkedin.com"
_JOBS_URL = f"{_LINKEDIN_BASE}/jobs/search/"

# Date filter codes
_DATE_FILTER = {
    "past_24h": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
    "any": "",
}

# Experience level codes
_EXP_FILTER = {
    "Internship": "1", "Entry level": "2", "Associate": "3",
    "Mid-Senior level": "4", "Director": "5", "Executive": "6",
}

# Job type codes
_JOB_TYPE_FILTER = {
    "Full-time": "F", "Part-time": "P", "Contract": "C",
    "Internship": "I", "Temporary": "T",
}


class LinkedInScanner:
    """Scans LinkedIn job listings using a real browser session."""

    def __init__(
        self,
        linkedin_cfg: LinkedInSettings,
        search_cfg: SearchSettings,
    ) -> None:
        self.linkedin = linkedin_cfg
        self.search = search_cfg

    async def scan(
        self,
        on_job_found: Callable[[dict], None] | None = None,
    ) -> list[dict]:
        """
        Run a full scan across all configured keywords × locations.
        Calls on_job_found(job) for each newly discovered job.
        Returns list of all discovered jobs.
        """
        all_jobs: list[dict] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.linkedin.headless,
                slow_mo=self.linkedin.slow_mo_ms,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await self._build_context(browser)
            page = await context.new_page()
            await self._apply_stealth(page)

            if not await self._ensure_logged_in(page, context):
                await browser.close()
                raise RuntimeError("LinkedIn login failed. Check credentials or refresh cookies.")

            for keyword in self.search.keywords:
                for location in self.search.locations:
                    logger.info("Scanning '%s' in '%s'…", keyword, location)
                    try:
                        jobs = await self._search(page, keyword, location)
                    except Exception as exc:
                        logger.warning("Search failed for '%s' / '%s': %s", keyword, location, exc)
                        continue

                    for job in jobs:
                        all_jobs.append(job)
                        if on_job_found:
                            await asyncio.coroutine(on_job_found)(job) \
                                if asyncio.iscoroutinefunction(on_job_found) \
                                else on_job_found(job)

                    await self._human_pause(3, 7)

            await browser.close()

        logger.info("Scan complete. Found %d jobs total.", len(all_jobs))
        return all_jobs

    async def get_details(self, url: str) -> dict:
        """Fetch full job details for a single URL."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.linkedin.headless)
            context = await self._build_context(browser)
            page = await context.new_page()
            details = await self._scrape_detail_page(page, url)
            await browser.close()
        return details

    # ─── Private ───────────────────────────────────────────────

    async def _build_context(self, browser: Browser) -> BrowserContext:
        cookies_file = self.linkedin.cookies_file
        if self.linkedin.use_cookies and Path(cookies_file).exists():
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            with open(cookies_file) as f:
                await ctx.add_cookies(json.load(f))
            return ctx
        return await browser.new_context()

    async def _apply_stealth(self, page: Page) -> None:
        """Minimal stealth patches."""
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)
        await page.set_viewport_size({"width": 1366, "height": 768})

    async def _ensure_logged_in(self, page: Page, context: BrowserContext) -> bool:
        try:
            await page.goto(f"{_LINKEDIN_BASE}/feed/", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            if "feed" in page.url:
                logger.info("LinkedIn session active (cookies)")
                return True
        except PWTimeoutError:
            pass

        # Fall back to password login
        if not self.linkedin.email or not self.linkedin.password.get_secret_value():
            logger.error("No LinkedIn credentials and no valid cookies.")
            return False

        logger.info("Logging into LinkedIn…")
        try:
            await page.goto(f"{_LINKEDIN_BASE}/login", wait_until="domcontentloaded")
            await page.fill("#username", self.linkedin.email)
            await asyncio.sleep(random.uniform(0.5, 1.2))
            await page.fill("#password", self.linkedin.password.get_secret_value())
            await asyncio.sleep(random.uniform(0.3, 0.8))
            await page.click('[data-litms-control-urn="login-submit"]')
            await page.wait_for_url("**/feed/**", timeout=30000)

            # Persist cookies
            cookies = await context.cookies()
            cookies_path = Path(self.linkedin.cookies_file)
            cookies_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cookies_path, "w") as f:
                json.dump(cookies, f)
            logger.info("Login successful. Cookies saved to %s", cookies_path)
            return True
        except Exception as exc:
            logger.error("Login failed: %s", exc)
            return False

    async def _search(self, page: Page, keyword: str, location: str) -> list[dict]:
        params: dict[str, str] = {
            "keywords": keyword,
            "location": location,
            "f_TPR": _DATE_FILTER.get(self.search.date_posted, "r604800"),
        }

        jt = ",".join(_JOB_TYPE_FILTER[t] for t in self.search.job_types if t in _JOB_TYPE_FILTER)
        if jt:
            params["f_JT"] = jt

        exp = ",".join(_EXP_FILTER[e] for e in self.search.experience_levels if e in _EXP_FILTER)
        if exp:
            params["f_E"] = exp

        if self.search.easy_apply_only:
            params["f_LF"] = "f_AL"

        url = _JOBS_URL + "?" + urlencode(params)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._human_pause(2, 4)

        jobs: list[dict] = []
        max_jobs = self.search.max_jobs_per_scan
        pages_to_scrape = min(max_jobs // 25 + 1, 4)

        for _ in range(pages_to_scrape):
            selector = ".job-card-container, .jobs-search-results__list-item"
            cards = await page.query_selector_all(selector)
            for card in cards:
                if len(jobs) >= max_jobs:
                    break
                job = await self._extract_card(card, page)
                if job and not any(j["url"] == job["url"] for j in jobs):
                    jobs.append(job)
            await self._human_scroll(page)
            await self._human_pause(1.5, 3)

        return jobs

    async def _extract_card(self, card, page: Page) -> dict | None:
        try:
            title = await self._safe_text(card, ".job-card-list__title, .job-card-container__link")
            company = await self._safe_text(
                card, ".job-card-container__primary-description, .artdeco-entity-lockup__subtitle"
            )
            location_text = await self._safe_text(card, ".job-card-container__metadata-item")
            link_el = await card.query_selector("a[href*='/jobs/view/']")
            easy_apply_el = await card.query_selector(".job-card-container__apply-method")

            href = await link_el.get_attribute("href") if link_el else ""
            url = re.sub(r"\?.*", "", href or "")
            if url and not url.startswith("http"):
                url = _LINKEDIN_BASE + url

            easy_apply_text = (
                await easy_apply_el.inner_text() if easy_apply_el else ""
            )
            description = await self._get_panel_description(card, page)

            if not title or not company or not url:
                return None

            return {
                "id": hashlib.sha1(url.encode()).hexdigest()[:12],
                "title": title.strip(),
                "company": company.strip(),
                "location": location_text.strip(),
                "url": url,
                "description": description,
                "easy_apply": "easy apply" in easy_apply_text.lower(),
                "source": "linkedin",
            }
        except Exception as exc:
            logger.debug("Card extraction failed: %s", exc)
            return None

    async def _get_panel_description(self, card, page: Page) -> str:
        try:
            await card.click()
            await asyncio.sleep(random.uniform(1.0, 2.0))
            el = await page.query_selector(".jobs-description__content, .jobs-box__html-content")
            return (await el.inner_text()).strip() if el else ""
        except Exception:
            return ""

    async def _scrape_detail_page(self, page: Page, url: str) -> dict:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        return {
            "id": hashlib.sha1(url.encode()).hexdigest()[:12],
            "title": await self._safe_text(page, "h1.topcard__title, h1.t-24"),
            "company": await self._safe_text(page, ".topcard__org-name-link, .topcard__flavor a"),
            "location": await self._safe_text(page, ".topcard__flavor--bullet"),
            "url": url,
            "description": await self._safe_text(page, ".description__text, .jobs-description"),
            "easy_apply": bool(await page.query_selector('button[aria-label*="Easy Apply"]')),
            "source": "linkedin",
        }

    @staticmethod
    async def _safe_text(root, selector: str) -> str:
        el = await root.query_selector(selector)
        return (await el.inner_text()).strip() if el else ""

    @staticmethod
    async def _human_scroll(page: Page) -> None:
        for _ in range(random.randint(2, 5)):
            await page.evaluate(f"window.scrollBy(0, {random.randint(200, 600)})")
            await asyncio.sleep(random.uniform(0.2, 0.6))

    @staticmethod
    async def _human_pause(lo: float, hi: float) -> None:
        await asyncio.sleep(random.uniform(lo, hi))
