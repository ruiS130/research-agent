"""
SQLite job store — partial MVP.

Done now:
  - schema + init
  - create_job / get_job

Not done yet (see /do-next):
  - upsert on every status/node update during a run
  - mark interrupted jobs on process start
  - drop the in-memory _jobs dict entirely
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB = "./data/jobs.db"
_conn: sqlite3.Connection | None = None


def _db_path() -> Path:
    return Path(os.getenv("JOBS_DB_PATH", _DEFAULT_DB))


def init_db() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            status TEXT NOT NULL,
            report TEXT,
            sources_json TEXT NOT NULL DEFAULT '[]',
            gaps_json TEXT NOT NULL DEFAULT '[]',
            error TEXT,
            last_node TEXT,
            event_seq INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            completed_at TEXT
        )
        """
    )
    _conn.commit()
    return _conn


def reset_db_connection() -> None:
    """For tests: close cached connection so a new path can be used."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job: dict) -> None:
    """Insert a new job row (called when research starts)."""
    conn = init_db()
    created = job.get("created_at")
    if isinstance(created, datetime):
        created_at = created.isoformat()
    else:
        created_at = created or _now_iso()

    conn.execute(
        """
        INSERT OR REPLACE INTO jobs (
            id, topic, status, report, sources_json, gaps_json,
            error, last_node, event_seq, created_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job["id"],
            job["topic"],
            job.get("status") or "pending",
            job.get("report"),
            json.dumps(job.get("sources") or []),
            json.dumps(job.get("gaps") or []),
            job.get("error"),
            job.get("last_node"),
            int(job.get("event_seq") or 0),
            created_at,
            None,
        ),
    )
    conn.commit()


def get_job(job_id: str) -> dict | None:
    """Load a job from SQLite, or None if missing."""
    conn = init_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def _row_to_job(row: sqlite3.Row) -> dict:
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    return {
        "id": row["id"],
        "topic": row["topic"],
        "status": row["status"],
        "report": row["report"],
        "sources": json.loads(row["sources_json"] or "[]"),
        "gaps": json.loads(row["gaps_json"] or "[]"),
        "error": row["error"],
        "last_node": row["last_node"],
        "event_seq": row["event_seq"] or 0,
        "created_at": _parse_dt(row["created_at"]),
        "completed_at": _parse_dt(row["completed_at"]),
    }
