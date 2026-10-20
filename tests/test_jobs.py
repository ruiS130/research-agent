"""Durable SQLite job store tests."""

from __future__ import annotations

from app.jobs.store import create_job, get_job, init_db, mark_interrupted_jobs, save_job


def test_save_job_upserts_status(chroma_tmp):
    init_db()
    create_job(
        {
            "id": "j1",
            "topic": "t",
            "status": "pending",
            "event_seq": 0,
        }
    )
    job = get_job("j1")
    assert job is not None
    job["status"] = "searching"
    job["last_node"] = "search"
    job["event_seq"] = 2
    save_job(job)
    again = get_job("j1")
    assert again["status"] == "searching"
    assert again["last_node"] == "search"
    assert again["event_seq"] == 2


def test_mark_interrupted_jobs(chroma_tmp):
    init_db()
    create_job({"id": "a", "topic": "t", "status": "planning", "event_seq": 1})
    create_job({"id": "b", "topic": "t", "status": "done", "event_seq": 3})
    n = mark_interrupted_jobs()
    assert n == 1
    assert get_job("a")["status"] == "interrupted"
    assert get_job("b")["status"] == "done"
