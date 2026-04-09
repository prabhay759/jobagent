"""Tests for preview gate in pipeline (mocked dependencies)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def make_job(job_id: str = "abc123", easy_apply: bool = True) -> dict:
    return {
        "id": job_id,
        "title": "Senior PM",
        "company": "TestCo",
        "location": "Remote",
        "url": "https://linkedin.com/jobs/view/abc123",
        "description": "Great job",
        "easy_apply": easy_apply,
        "match_score": 85,
        "ai_analysis": {
            "score": 85,
            "recommendation": "apply",
            "highlights": [],
            "gaps": [],
        },
    }


def _make_notifier(preview_decision: str = "SEND") -> MagicMock:
    notifier = MagicMock()
    notifier.request_approval = AsyncMock(return_value="YES")
    notifier.request_preview_approval = AsyncMock(return_value=preview_decision)
    notifier.notify = AsyncMock()
    notifier.dashboard_base = "http://127.0.0.1:8080"
    return notifier


def _make_pipeline(notifier: MagicMock, tmp_path: Path) -> "Pipeline":  # noqa: F821
    """
    Build a Pipeline with every external dependency mocked.
    Uses plain MagicMock (no spec) for settings to avoid pydantic
    attribute restrictions on MagicMock(spec=Settings).
    """
    from jobagent.pipeline import Pipeline

    # ── Settings (plain mock — no spec, so nested attr access works) ──
    settings = MagicMock()
    settings.anthropic.api_key.get_secret_value.return_value = "sk-ant-test"
    settings.anthropic.model = "claude-sonnet-4-20250514"
    settings.search.min_match_score = 70
    settings.application.require_whatsapp_approval = True
    settings.application.auto_apply = True
    settings.application.cover_letter = True
    settings.application.preview_before_send = True
    settings.cv.output_dir = tmp_path
    settings.database.path = tmp_path / "test.db"
    settings.dashboard.host = "127.0.0.1"
    settings.dashboard.port = 8080

    pipeline = Pipeline.__new__(Pipeline)
    pipeline.settings = settings
    pipeline.profile = {
        "personal": {"name": "Test", "summary": "Test"},
        "cover_letter_tone": "confident",
    }

    pipeline.tracker = MagicMock()
    pipeline.tracker.get_job.return_value = make_job()
    pipeline.tracker.get_messages.return_value = []

    pipeline.ai = MagicMock()
    pipeline.ai.analyze_fit.return_value = {
        "score": 85,
        "recommendation": "apply",
        "highlights": [],
        "gaps": [],
    }
    pipeline.ai.generate_cover_letter.return_value = "Dear Hiring Manager…"
    pipeline.ai.whatsapp_summary.return_value = "Job summary"
    pipeline.ai.usage.summary.return_value = "0 calls"

    pipeline.cv_gen = MagicMock()
    pipeline.cv_gen.generate = AsyncMock(return_value=(tmp_path / "cv.pdf", {}))

    pipeline.notifier = notifier
    pipeline.scanner = MagicMock()

    return pipeline


class TestPreviewGate:
    def test_send_decision_triggers_apply(self, tmp_path: Path) -> None:
        """SEND after preview should call _apply."""
        pipeline = _make_pipeline(_make_notifier("SEND"), tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_called_once()

    def test_skip_decision_sets_skipped_status(self, tmp_path: Path) -> None:
        """SKIP at preview gate should mark job skipped without applying."""
        pipeline = _make_pipeline(_make_notifier("SKIP"), tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_not_called()
        pipeline.tracker.set_status.assert_any_call(
            "abc123", "skipped", "Preview rejected: SKIP"
        )

    def test_edit_decision_sets_pending_edit(self, tmp_path: Path) -> None:
        """EDIT at preview gate should mark job pending_edit and not apply."""
        pipeline = _make_pipeline(_make_notifier("EDIT"), tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_not_called()
        pipeline.tracker.set_status.assert_any_call("abc123", "pending_edit")
        pipeline.notifier.notify.assert_called()
        notify_msg: str = pipeline.notifier.notify.call_args[0][0]
        assert "edit" in notify_msg.lower() or "Edit" in notify_msg

    def test_timeout_at_preview_skips(self, tmp_path: Path) -> None:
        """Timeout during preview wait should skip without applying."""
        pipeline = _make_pipeline(_make_notifier("TIMEOUT"), tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_not_called()

    def test_low_score_skips_before_whatsapp(self, tmp_path: Path) -> None:
        """Jobs below threshold must be skipped before WhatsApp is contacted."""
        notifier = _make_notifier("SEND")
        pipeline = _make_pipeline(notifier, tmp_path)
        pipeline.ai.analyze_fit.return_value = {
            "score": 30,
            "recommendation": "skip",
            "highlights": [],
            "gaps": [],
        }

        asyncio.run(pipeline.process_job(make_job()))

        notifier.request_approval.assert_not_called()
        notifier.request_preview_approval.assert_not_called()
