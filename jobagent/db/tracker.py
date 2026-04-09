"""
JobAgent - Database Layer
SQLite-backed job tracker with connection pooling and migrations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from jobagent.logging_config import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1


class JobTracker:
    """Thread-safe SQLite job tracker."""

    def __init__(self, db_path: str | Path = "data/jobs.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._migrate()

    # ─── Connection Management ─────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._connect()
        yield self._local.conn

    def _migrate(self) -> None:
        """Run schema migrations."""
        with self._get_conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER PRIMARY KEY);

            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                company         TEXT NOT NULL,
                location        TEXT,
                url             TEXT UNIQUE,
                description     TEXT,
                salary_raw      TEXT,
                job_type        TEXT,
                experience      TEXT,
                easy_apply      INTEGER DEFAULT 0,
                source          TEXT DEFAULT 'linkedin',
                found_at        TEXT NOT NULL DEFAULT (datetime('now')),
                status          TEXT NOT NULL DEFAULT 'discovered',
                match_score     INTEGER,
                ai_analysis     TEXT,
                cv_path         TEXT,
                cover_letter    TEXT,
                applied_at      TEXT,
                whatsapp_sent_at TEXT,
                whatsapp_approved INTEGER,
                notes           TEXT,
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_found_at ON jobs(found_at DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);

            CREATE TABLE IF NOT EXISTS status_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                status      TEXT NOT NULL,
                changed_at  TEXT NOT NULL DEFAULT (datetime('now')),
                note        TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                role        TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS scan_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                jobs_found  INTEGER DEFAULT 0,
                jobs_new    INTEGER DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'running'
            );
            """)
            conn.commit()
        logger.debug("Database schema ready at %s", self.db_path)

    # ─── Jobs ──────────────────────────────────────────────────

    def upsert_job(self, job: dict) -> bool:
        """Insert job if URL not seen before. Returns True if new."""
        url = job.get("url", "")
        if url and self.get_job_by_url(url):
            return False

        job_id = job.get("id") or self._make_id(job)
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            try:
                conn.execute(
                    """INSERT INTO jobs
                       (id, title, company, location, url, description, salary_raw,
                        job_type, experience, easy_apply, source, match_score, found_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        job_id, job.get("title", "Unknown"),
                        job.get("company", "Unknown"), job.get("location"),
                        url, job.get("description"), job.get("salary"),
                        job.get("job_type"), job.get("experience"),
                        1 if job.get("easy_apply") else 0,
                        job.get("source", "linkedin"),
                        job.get("match_score"),
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO status_history (job_id, status) VALUES (?, 'discovered')",
                    (job_id,),
                )
                conn.commit()
                logger.info("New job: [bold]%s[/bold] @ %s", job.get("title"), job.get("company"))
                return True
            except sqlite3.IntegrityError:
                return False

    def update_job(self, job_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE id = ?",
                (*fields.values(), job_id),
            )
            conn.commit()

    def set_status(self, job_id: str, status: str, note: str = "") -> None:
        self.update_job(job_id, status=status)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO status_history (job_id, status, note) VALUES (?,?,?)",
                (job_id, status, note),
            )
            conn.commit()
        logger.debug("Job %s → %s", job_id, status)

    def save_analysis(self, job_id: str, analysis: dict) -> None:
        self.update_job(
            job_id,
            ai_analysis=json.dumps(analysis),
            match_score=analysis.get("score"),
        )

    def get_job(self, job_id: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._parse_row(row)

    def get_job_by_url(self, url: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
            return self._parse_row(row)

    def list_jobs(self, status: str | None = None, limit: int = 200) -> list[dict]:
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY found_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY found_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [j for r in rows if (j := self._parse_row(r)) is not None]

    def list_pending_approval(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM jobs
                   WHERE status = 'pending_approval' AND whatsapp_approved IS NULL
                   ORDER BY found_at DESC"""
            ).fetchall()
            return [j for r in rows if (j := self._parse_row(r)) is not None]

    def get_stats(self) -> dict:
        statuses = [
            "discovered", "analyzed", "pending_approval", "ready_to_apply",
            "applied", "interviewing", "offer", "rejected", "skipped", "apply_failed",
        ]
        with self._get_conn() as conn:
            stats = {
                s: conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status = ?", (s,)
                ).fetchone()[0]
                for s in statuses
            }
            stats["total"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            stats["easy_apply_count"] = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE easy_apply = 1"
            ).fetchone()[0]
            stats["avg_score"] = conn.execute(
                "SELECT ROUND(AVG(match_score), 1) FROM jobs WHERE match_score IS NOT NULL"
            ).fetchone()[0] or 0
        return stats

    # ─── Chat ──────────────────────────────────────────────────

    def add_message(self, job_id: str, role: str, content: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO chat_messages (job_id, role, content) VALUES (?,?,?)",
                (job_id, role, content),
            )
            conn.commit()

    def get_messages(self, job_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            ).fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows]

    # ─── Scan Runs ─────────────────────────────────────────────

    def begin_scan(self) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("INSERT INTO scan_runs (status) VALUES ('running')")
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def end_scan(self, scan_id: int, found: int, new: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE scan_runs
                   SET finished_at=?, jobs_found=?, jobs_new=?, status='done'
                   WHERE id=?""",
                (datetime.utcnow().isoformat(), found, new, scan_id),
            )
            conn.commit()

    # ─── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _make_id(job: dict) -> str:
        key = f"{job.get('company','')}-{job.get('title','')}-{job.get('url','')}"
        return hashlib.sha1(key.encode()).hexdigest()[:12]

    @staticmethod
    def _parse_row(row: sqlite3.Row | None) -> dict | None:  # noqa: UP007
        if row is None:
            return None
        d = dict(row)
        if d.get("ai_analysis"):
            try:
                d["ai_analysis"] = json.loads(d["ai_analysis"])
            except json.JSONDecodeError:
                d["ai_analysis"] = {}
        return d

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ── Cover Letter / CV Edit Helpers ─────────────────────────

    def get_cover_letter(self, job_id: str) -> str:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT cover_letter FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return row["cover_letter"] or "" if row else ""

    def save_cover_letter(self, job_id: str, text: str) -> None:
        self.update_job(job_id, cover_letter=text)

    def get_cv_path(self, job_id: str) -> str | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT cv_path FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return row["cv_path"] if row else None
