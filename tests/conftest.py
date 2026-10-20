"""Shared fixtures for API and graph tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Must set before importing app.main (lifespan checks key)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEARCH_PROVIDER", "ddg")
os.environ.setdefault("COST_MODE", "min")
os.environ.setdefault("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")


@pytest.fixture()
def chroma_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    persist = tmp_path / "chroma"
    persist.mkdir()
    jobs_db = tmp_path / "jobs.db"
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(persist))
    monkeypatch.setenv("JOBS_DB_PATH", str(jobs_db))
    from app.rag import store
    from app.jobs import store as job_store

    store.reset_chroma_client()
    job_store.reset_db_connection()
    yield persist
    store.reset_chroma_client()
    job_store.reset_db_connection()


@pytest.fixture()
def client(chroma_tmp, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    from app.main import app

    with TestClient(app) as c:
        yield c
