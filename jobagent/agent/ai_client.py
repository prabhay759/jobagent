"""
JobAgent - AI Client
All Claude-powered operations: analysis, CV tailoring, chat, cover letters.
Includes retry logic, cost tracking, and structured output validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from jobagent.logging_config import get_logger

logger = get_logger(__name__)

# Approximate cost per 1M tokens (Sonnet 4 pricing)
_INPUT_COST_PER_M = 3.0   # USD
_OUTPUT_COST_PER_M = 15.0  # USD


@dataclass
class UsageTracker:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * _INPUT_COST_PER_M
            + self.output_tokens / 1_000_000 * _OUTPUT_COST_PER_M
        )

    def record(self, usage: anthropic.types.Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.calls += 1

    def summary(self) -> str:
        return (
            f"API calls: {self.calls} | "
            f"Tokens: {self.input_tokens:,} in / {self.output_tokens:,} out | "
            f"Est. cost: ${self.estimated_cost_usd:.4f}"
        )


class AIClient:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.usage = UsageTracker()

    # ─── Core Call ─────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3),
    )
    def _call(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        messages: Optional[list[dict]] = None,
        max_tokens: int = 1024,
    ) -> str:
        if messages is None:
            messages = [{"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        self.usage.record(response.usage)
        return response.content[0].text.strip()

    def _call_json(self, prompt: str, **kwargs) -> dict:
        """Call Claude and parse the response as JSON."""
        text = self._call(prompt, **kwargs)
        # Strip markdown fences
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed, retrying with stricter prompt: %s", e)
            raise ValueError(f"Invalid JSON from model: {text[:200]}") from e

    # ─── Job Analysis ──────────────────────────────────────────

    def analyze_fit(self, job_description: str, profile: dict) -> dict:
        """
        Score job fit. Returns structured analysis dict.
        Schema: score, recommendation, summary, highlights, gaps,
                key_skills_matched, key_skills_missing, salary_estimate,
                red_flags, company_stage, role_level
        """
        logger.info("Analyzing job fit…")
        result = self._call_json(f"""You are an expert career coach. Analyze this job for the candidate.

JOB DESCRIPTION:
{job_description[:4000]}

CANDIDATE PROFILE (JSON):
{json.dumps(profile, indent=2)[:3000]}

Return ONLY valid JSON matching this exact schema (no markdown, no explanation):
{{
  "score": <integer 0-100>,
  "recommendation": "strong_apply|apply|consider|skip",
  "summary": "<one sentence>",
  "highlights": ["<up to 4 strengths>"],
  "gaps": ["<up to 3 gaps>"],
  "key_skills_matched": ["<skill>"],
  "key_skills_missing": ["<skill>"],
  "salary_estimate": "<range or null>",
  "red_flags": [],
  "company_stage": "startup|scaleup|enterprise|unknown",
  "role_level": "IC|lead|manager|director|VP|C-suite"
}}""", max_tokens=1024)
        logger.info(
            "Fit score: %d/100 (%s)", result.get("score", 0), result.get("recommendation")
        )
        return result

    # ─── CV Tailoring ──────────────────────────────────────────

    def tailor_cv(self, job_description: str, profile: dict, analysis: dict) -> dict:
        """Generate tailored CV content as structured JSON."""
        logger.info("Tailoring CV…")
        return self._call_json(
            f"""You are an expert ATS-optimized CV writer. Tailor this candidate's CV for the job.
Rules: reorder and reframe bullets to match JD keywords; do NOT fabricate experience.

JOB DESCRIPTION (first 3000 chars):
{job_description[:3000]}

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)[:3000]}

KEY GAPS TO ADDRESS: {analysis.get('gaps', [])}

Return ONLY valid JSON:
{{
  "professional_summary": "<2-3 sentence tailored summary>",
  "experience": [
    {{
      "company": "...", "role": "...", "start": "...", "end": "...",
      "location": "...", "bullets": ["<rewritten bullet>"]
    }}
  ],
  "skills_highlighted": ["<top skills for this role>"],
  "keywords_injected": ["<ATS keywords added>"]
}}""",
            max_tokens=2048,
        )

    # ─── Cover Letter ──────────────────────────────────────────

    def generate_cover_letter(
        self, job: dict, profile: dict, analysis: dict, tone: str = "confident and specific"
    ) -> str:
        """Generate a tailored cover letter."""
        logger.info("Writing cover letter…")
        return self._call(
            f"""Write a {tone} cover letter for:
Job: {job.get('title')} at {job.get('company')}
Description (excerpt): {job.get('description', '')[:2000]}

Candidate: {profile['personal']['name']}
Summary: {profile['personal']['summary']}
Key strengths for this role: {', '.join(analysis.get('highlights', [])[:3])}

Requirements:
- 3 paragraphs, max 250 words
- Opening: specific hook about this company/role (no generic "I am applying for")
- Middle: one quantified achievement most relevant to this JD
- Close: cultural fit + clear call to action
- No "Dear Hiring Manager" — address by role or team""",
            max_tokens=512,
        )

    # ─── Application Q&A ───────────────────────────────────────

    def answer_question(self, question: str, job: dict, profile: dict) -> str:
        """Answer a single application form field."""
        return self._call(
            f"""Fill out this job application field concisely and professionally.

JOB: {job.get('title')} at {job.get('company')}
FIELD: {question}
CANDIDATE: {json.dumps(profile, indent=2)[:2000]}

Reply with ONLY the field answer. If numeric (salary, years), answer with a number.""",
            max_tokens=200,
        )

    # ─── Job Chat ──────────────────────────────────────────────

    def chat(
        self,
        user_message: str,
        job: dict,
        profile: dict,
        history: list[dict],
    ) -> str:
        """Multi-turn chat about a job."""
        system = f"""You are a career advisor helping this candidate evaluate and prepare for a job.

JOB:
- Title: {job.get('title')}
- Company: {job.get('company')}
- Location: {job.get('location')}
- Description: {str(job.get('description', ''))[:3000]}
- Match Score: {job.get('match_score', 'N/A')}/100
- Analysis: {json.dumps(job.get('ai_analysis', {}), indent=2)}

CANDIDATE:
{json.dumps(profile, indent=2)[:2000]}

Help with: salary negotiation, interview prep, company research, culture fit,
compensation benchmarking, red flags, application strategy. Be specific and data-driven."""

        messages = history[-20:] + [{"role": "user", "content": user_message}]
        return self._call("", system=system, messages=messages, max_tokens=1024)

    # ─── WhatsApp Summary ──────────────────────────────────────

    def whatsapp_summary(self, job: dict, analysis: dict) -> str:
        """Generate concise WhatsApp approval message."""
        score = analysis.get("score", "?")
        rec = analysis.get("recommendation", "?").replace("_", " ").title()
        highlights = " · ".join(analysis.get("highlights", [])[:2])
        gap = analysis.get("gaps", [None])[0]
        salary = analysis.get("salary_estimate", "")

        lines = [
            "🤖 *JobAgent* — New match found!\n",
            f"*{job.get('title')}* at *{job.get('company')}*",
            f"📍 {job.get('location', 'N/A')}  |  "
            f"{'⚡ Easy Apply' if job.get('easy_apply') else '🌐 External Apply'}",
            f"🎯 Match: *{score}/100*  ({rec})\n",
            f"✅ *Strengths:* {highlights}",
        ]
        if gap:
            lines.append(f"⚠️ *Gap:* {gap}")
        if salary:
            lines.append(f"💰 *Est. Salary:* {salary}")
        lines += [
            f"\n🔗 {job.get('url', '')}",
            "\nReply *YES* to apply · *NO* to skip · *INFO* to ask questions first",
        ]
        return "\n".join(lines)
