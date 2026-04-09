"""Tests for JobTracker."""


import pytest

from jobagent.db.tracker import JobTracker


@pytest.fixture
def tracker(tmp_path):
    return JobTracker(db_path=tmp_path / "test.db")


def make_job(**kwargs):
    return {
        "id": "test123",
        "title": "Senior PM",
        "company": "TestCo",
        "location": "Remote",
        "url": "https://linkedin.com/jobs/view/123",
        "description": "Great job opportunity",
        "easy_apply": True,
        "source": "linkedin",
        **kwargs,
    }


class TestJobTracker:
    def test_upsert_new_job(self, tracker):
        job = make_job()
        assert tracker.upsert_job(job) is True

    def test_upsert_duplicate_url(self, tracker):
        job = make_job()
        tracker.upsert_job(job)
        assert tracker.upsert_job(make_job(id="other")) is False

    def test_get_job(self, tracker):
        tracker.upsert_job(make_job())
        job = tracker.get_job("test123")
        assert job is not None
        assert job["title"] == "Senior PM"
        assert job["company"] == "TestCo"

    def test_get_nonexistent_job(self, tracker):
        assert tracker.get_job("nonexistent") is None

    def test_set_status(self, tracker):
        tracker.upsert_job(make_job())
        tracker.set_status("test123", "applied", "easy apply")
        job = tracker.get_job("test123")
        assert job["status"] == "applied"

    def test_update_job(self, tracker):
        tracker.upsert_job(make_job())
        tracker.update_job("test123", match_score=85)
        job = tracker.get_job("test123")
        assert job["match_score"] == 85

    def test_save_analysis(self, tracker):
        tracker.upsert_job(make_job())
        analysis = {"score": 90, "recommendation": "strong_apply"}
        tracker.save_analysis("test123", analysis)
        job = tracker.get_job("test123")
        assert job["ai_analysis"]["score"] == 90

    def test_list_jobs(self, tracker):
        tracker.upsert_job(make_job(url="https://linkedin.com/jobs/view/1"))
        tracker.upsert_job(make_job(id="test456", url="https://linkedin.com/jobs/view/2"))
        jobs = tracker.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_by_status(self, tracker):
        tracker.upsert_job(make_job())
        tracker.set_status("test123", "applied")
        applied = tracker.list_jobs(status="applied")
        discovered = tracker.list_jobs(status="discovered")
        assert len(applied) == 1
        assert len(discovered) == 0

    def test_get_stats(self, tracker):
        tracker.upsert_job(make_job())
        stats = tracker.get_stats()
        assert stats["total"] == 1
        assert stats["discovered"] == 1

    def test_chat_messages(self, tracker):
        tracker.upsert_job(make_job())
        tracker.add_message("test123", "user", "Tell me about this company")
        tracker.add_message("test123", "assistant", "Great place to work!")
        msgs = tracker.get_messages("test123")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_scan_lifecycle(self, tracker):
        scan_id = tracker.begin_scan()
        assert scan_id > 0
        tracker.end_scan(scan_id, found=10, new=3)

    def test_make_id_deterministic(self, tracker):
        job = make_job(id=None)
        id1 = tracker._make_id(job)
        id2 = tracker._make_id(job)
        assert id1 == id2

    def test_close(self, tracker):
        tracker.close()  # Should not raise
