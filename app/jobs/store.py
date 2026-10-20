"""SQLite durable job store — source of truth for research job status."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB = "./data/jobs.db"
_conn: sqlite3.Connection | None = None
_lock = threading.Lock()

_NON_TERMINAL = (
    "pending",
    "planning",
    "searching",
    "extracting",
    "synthesizing",
    "checking",
    "running",
)


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
    with _lock:
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
                completed_at TEXT,
                timing_json TEXT NOT NULL DEFAULT '{}',
                cost_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        _migrate(_conn)
        _conn.commit()
    return _conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "timing_json" not in cols:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN timing_json TEXT NOT NULL DEFAULT '{}'"
        )
    if "cost_json" not in cols:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN cost_json TEXT NOT NULL DEFAULT '{}'"
        )


def reset_db_connection() -> None:
    """For tests: close cached connection so a new path can be used."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_to_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def create_job(job: dict) -> None:
    """Insert a new job row."""
    conn = init_db()
    with _lock:
        conn.execute(
            """
            INSERT INTO jobs (
                id, topic, status, report, sources_json, gaps_json,
                error, last_node, event_seq, created_at, completed_at,
                timing_json, cost_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _dt_to_iso(job.get("created_at")) or _now_iso(),
                _dt_to_iso(job.get("completed_at")),
                json.dumps(job.get("timing") or {}),
                json.dumps(job.get("cost") or {}),
            ),
        )
        conn.commit()


def save_job(job: dict) -> None:
    """Upsert full job snapshot (called on every node / status change)."""
    conn = init_db()
    with _lock:
        conn.execute(
            """
            INSERT INTO jobs (
                id, topic, status, report, sources_json, gaps_json,
                error, last_node, event_seq, created_at, completed_at,
                timing_json, cost_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                topic=excluded.topic,
                status=excluded.status,
                report=excluded.report,
                sources_json=excluded.sources_json,
                gaps_json=excluded.gaps_json,
                error=excluded.error,
                last_node=excluded.last_node,
                event_seq=excluded.event_seq,
                created_at=COALESCE(jobs.created_at, excluded.created_at),
                completed_at=excluded.completed_at,
                timing_json=excluded.timing_json,
                cost_json=excluded.cost_json
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
                _dt_to_iso(job.get("created_at")) or _now_iso(),
                _dt_to_iso(job.get("completed_at")),
                json.dumps(job.get("timing") or {}),
                json.dumps(job.get("cost") or {}),
            ),
        )
        conn.commit()


def get_job(job_id: str) -> dict | None:
    """Load a job from SQLite, or None if missing."""
    conn = init_db()
    with _lock:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def mark_interrupted_jobs() -> int:
    """
    Mark non-terminal jobs as interrupted (call on process start).
    In-flight work cannot continue after a crash; status becomes visible.
    """
    conn = init_db()
    placeholders = ",".join("?" for _ in _NON_TERMINAL)
    now = _now_iso()
    with _lock:
        cur = conn.execute(
            f"""
            UPDATE jobs
            SET status = 'interrupted',
                last_node = COALESCE(last_node, 'interrupted'),
                error = COALESCE(error, 'Interrupted: process restarted before completion'),
                completed_at = ?,
                event_seq = event_seq + 1
            WHERE status IN ({placeholders})
            """,
            (now, *_NON_TERMINAL),
        )
        conn.commit()
        return cur.rowcount


def _row_to_job(row: sqlite3.Row) -> dict:
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    keys = row.keys()
    timing_raw = row["timing_json"] if "timing_json" in keys else "{}"
    cost_raw = row["cost_json"] if "cost_json" in keys else "{}"

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
        "timing": json.loads(timing_raw or "{}"),
        "cost": json.loads(cost_raw or "{}"),
    }
