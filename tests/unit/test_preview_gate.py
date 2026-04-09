"""Tests for preview gate in pipeline (mocked dependencies)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def make_job(job_id="abc123", easy_apply=True):
    return {
        "id": job_id,
        "title": "Senior PM",
        "company": "TestCo",
        "location": "Remote",
        "url": "https://linkedin.com/jobs/view/abc123",
        "description": "Great job",
        "easy_apply": easy_apply,
        "match_score": 85,
        "ai_analysis": {"score": 85, "recommendation": "apply", "highlights": [], "gaps": []},
    }


class TestPreviewGate:
    """
    Tests for the SEND / EDIT / SKIP preview flow.
    All external I/O is mocked.
    """

    def _make_notifier(self, preview_decision="SEND"):
        notifier = MagicMock()
        notifier.request_approval = AsyncMock(return_value="YES")
        notifier.request_preview_approval = AsyncMock(return_value=preview_decision)
        notifier.notify = AsyncMock()
        notifier.dashboard_base = "http://127.0.0.1:8080"
        return notifier

    def _make_pipeline(self, notifier, tracker=None, tmp_path=None):
        """Build a Pipeline with all dependencies mocked."""

        from jobagent.settings import (
            Settings,
        )

        settings = MagicMock(spec=Settings)
        settings.anthropic.api_key.get_secret_value.return_value = "sk-ant-test"
        settings.anthropic.model = "claude-sonnet-4-20250514"
        settings.search.min_match_score = 70
        settings.application.require_whatsapp_approval = True
        settings.application.auto_apply = True
        settings.application.cover_letter = True
        settings.application.preview_before_send = True
        settings.cv.output_dir = tmp_path or Path("/tmp")
        settings.database.path = Path("/tmp/test_preview.db")
        settings.dashboard.host = "127.0.0.1"
        settings.dashboard.port = 8080

        from jobagent.pipeline import Pipeline
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.settings = settings
        pipeline.profile = {
            "personal": {"name": "Test", "summary": "Test"},
            "cover_letter_tone": "confident",
        }

        pipeline.tracker = tracker or MagicMock()
        pipeline.tracker.get_job.return_value = make_job()
        pipeline.tracker.get_messages.return_value = []

        pipeline.ai = MagicMock()
        pipeline.ai.analyze_fit.return_value = {"score": 85, "recommendation": "apply",
                                                  "highlights": [], "gaps": []}
        pipeline.ai.generate_cover_letter.return_value = "Dear Hiring Manager, I am excited..."
        pipeline.ai.whatsapp_summary.return_value = "Job summary"
        pipeline.ai.usage.summary.return_value = "0 calls"

        pipeline.cv_gen = MagicMock()
        pipeline.cv_gen.generate = AsyncMock(return_value=(Path("/tmp/cv.pdf"), {}))

        pipeline.notifier = notifier
        pipeline.scanner = MagicMock()

        return pipeline

    def test_send_decision_triggers_apply(self, tmp_path):
        """SEND decision after preview should call _apply."""
        notifier = self._make_notifier("SEND")
        pipeline = self._make_pipeline(notifier, tmp_path=tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_called_once()

    def test_skip_decision_sets_skipped_status(self, tmp_path):
        """SKIP at preview gate should mark job as skipped."""
        notifier = self._make_notifier("SKIP")
        pipeline = self._make_pipeline(notifier, tmp_path=tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_not_called()
        pipeline.tracker.set_status.assert_any_call("abc123", "skipped",
                                                      "Preview rejected: SKIP")

    def test_edit_decision_sets_pending_edit(self, tmp_path):
        """EDIT at preview gate should mark job as pending_edit."""
        notifier = self._make_notifier("EDIT")
        pipeline = self._make_pipeline(notifier, tmp_path=tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_not_called()
        pipeline.tracker.set_status.assert_any_call("abc123", "pending_edit")
        # Should notify user with dashboard edit link
        notifier.notify.assert_called()
        call_msg = notifier.notify.call_args[0][0]
        assert "edit" in call_msg.lower() or "Edit" in call_msg

    def test_timeout_at_preview_skips(self, tmp_path):
        """Timeout during preview wait should skip the job."""
        notifier = self._make_notifier("TIMEOUT")
        pipeline = self._make_pipeline(notifier, tmp_path=tmp_path)
        pipeline._apply = AsyncMock()

        asyncio.run(pipeline.process_job(make_job()))

        pipeline._apply.assert_not_called()

    def test_low_score_skips_before_whatsapp(self, tmp_path):
        """Jobs below threshold should be skipped before WhatsApp is contacted."""
        notifier = self._make_notifier("SEND")
        pipeline = self._make_pipeline(notifier, tmp_path=tmp_path)
        pipeline.ai.analyze_fit.return_value = {
            "score": 30, "recommendation": "skip", "highlights": [], "gaps": []
        }

        asyncio.run(pipeline.process_job(make_job()))

        notifier.request_approval.assert_not_called()
        notifier.request_preview_approval.assert_not_called()
