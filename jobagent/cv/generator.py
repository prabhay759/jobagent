"""
JobAgent - CV Generator
AI-tailored CV → HTML → PDF via Playwright.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright

from jobagent.logging_config import get_logger
from jobagent.settings import CVSettings

if TYPE_CHECKING:
    from jobagent.agent.ai_client import AIClient

logger = get_logger(__name__)


class CVGenerator:
    def __init__(self, cfg: CVSettings, ai: AIClient) -> None:
        self.cfg = cfg
        self.ai = ai
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, job: dict, profile: dict) -> tuple[Path, dict]:
        """
        Generate a tailored PDF CV for a job.
        Returns (pdf_path, tailored_content_dict).
        """
        logger.info("Generating CV for %s @ %s…", job.get("title"), job.get("company"))

        analysis = job.get("ai_analysis") or {}
        if isinstance(analysis, str):
            try:
                analysis = json.loads(analysis)
            except json.JSONDecodeError:
                analysis = {}

        # AI tailoring
        tailored = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.ai.tailor_cv(job.get("description", ""), profile, analysis),
        )

        html = self._render(profile, tailored)
        pdf_path = await self._to_pdf(html, job)

        logger.info("CV saved: %s", pdf_path)
        return pdf_path, tailored

    def _render(self, profile: dict, tailored: dict) -> str:
        template_path = self.cfg.base_template
        template = (
            template_path.read_text()
            if template_path.exists()
            else self._builtin_template()
        )

        experience = tailored.get("experience") or profile.get("experience", [])
        exp_html = self._render_experience(experience)
        edu_html = self._render_education(profile.get("education", []))
        skills = " · ".join(
            tailored.get("skills_highlighted")
            or (
                profile.get("skills", {}).get("product", [])
                + profile.get("skills", {}).get("technical", [])
            )
        )
        achievements = "\n".join(
            f"<li>{a}</li>" for a in profile.get("achievements", [])
        )
        certs = " · ".join(profile.get("certifications", []))
        p = profile["personal"]

        for placeholder, value in {
            "{{NAME}}": p.get("name", ""),
            "{{EMAIL}}": p.get("email", ""),
            "{{PHONE}}": p.get("phone", ""),
            "{{LOCATION}}": p.get("location", ""),
            "{{LINKEDIN}}": p.get("linkedin", ""),
            "{{WEBSITE}}": p.get("website", ""),
            "{{SUMMARY}}": tailored.get("professional_summary") or p.get("summary", ""),
            "{{EXPERIENCE}}": exp_html,
            "{{EDUCATION}}": edu_html,
            "{{SKILLS}}": skills,
            "{{CERTIFICATIONS}}": certs,
            "{{ACHIEVEMENTS}}": achievements,
            "{{GENERATED_DATE}}": datetime.now().strftime("%B %Y"),
        }.items():
            template = template.replace(placeholder, str(value))

        return template

    @staticmethod
    def _render_experience(experience: list[dict]) -> str:
        html = ""
        for exp in experience:
            bullets = "\n".join(f"<li>{b}</li>" for b in exp.get("bullets", []))
            html += f"""
<div class="exp-item">
  <div class="exp-header">
    <div><div class="exp-role">{exp.get('role','')}</div>
    <div class="exp-company">{exp.get('company','')}</div></div>
    <div class="exp-meta"><div>{exp.get('location','')}</div>
    <div>{exp.get('start','')} – {exp.get('end','')}</div></div>
  </div>
  <ul class="bullets">{bullets}</ul>
</div>"""
        return html

    @staticmethod
    def _render_education(education: list[dict]) -> str:
        return "\n".join(
            f'<div class="edu-item"><strong>{e.get("institution","")}</strong>'
            f' — {e.get("degree","")} <span class="edu-year">{e.get("year","")}</span></div>'
            for e in education
        )

    async def _to_pdf(self, html: str, job: dict) -> Path:
        def safe(s: object) -> str:
            return "".join(c for c in str(s) if c.isalnum() or c in " ._-")[:30]
        filename = (
            f"CV_{safe(job.get('company', 'Company'))}_"
            f"{safe(job.get('title', 'Role'))}_"
            f"{datetime.now().strftime('%Y%m%d')}.pdf"
        )
        pdf_path = self.cfg.output_dir / filename

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                margin={"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"},
                print_background=True,
            )
            await browser.close()

        return pdf_path

    @staticmethod
    def _builtin_template() -> str:
        return """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Georgia,serif;font-size:11pt;color:#111;line-height:1.5}
.header{border-bottom:2px solid #111;padding-bottom:8px;margin-bottom:16px}
.name{font-size:22pt;font-weight:bold;letter-spacing:1px}
.contact{font-size:9pt;color:#555;margin-top:4px}
h2{font-size:10.5pt;text-transform:uppercase;letter-spacing:2px;border-bottom:1px solid #ccc;
   padding-bottom:2px;margin:14px 0 8px}
.summary{font-style:italic;color:#333;margin-bottom:4px}
.exp-item{margin-bottom:12px}
.exp-header{display:flex;justify-content:space-between}
.exp-role{font-weight:bold}
.exp-company{color:#444}
.exp-meta{text-align:right;font-size:9.5pt;color:#666}
.bullets{margin-left:16px;margin-top:4px}
.bullets li{margin-bottom:3px;font-size:10.5pt}
.edu-item{margin-bottom:6px}
.edu-year{color:#666}
.gen{font-size:7.5pt;color:#bbb;margin-top:16px}
</style></head><body>
<div class="header">
  <div class="name">{{NAME}}</div>
  <div class="contact">{{EMAIL}} · {{PHONE}} · {{LOCATION}} · {{LINKEDIN}}</div>
</div>
<div class="summary">{{SUMMARY}}</div>
<h2>Experience</h2>{{EXPERIENCE}}
<h2>Education</h2>{{EDUCATION}}
<h2>Skills</h2><p>{{SKILLS}}</p>
<h2>Certifications</h2><p>{{CERTIFICATIONS}}</p>
<h2>Achievements</h2><ul class="bullets">{{ACHIEVEMENTS}}</ul>
<div class="gen">Generated by JobAgent · {{GENERATED_DATE}}</div>
</body></html>"""
