"""Shared fixtures for API and graph tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Must set before importing app.main (lifespan checks key)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEARCH_PROVIDER", "ddg")


@pytest.fixture()
def chroma_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    persist = tmp_path / "chroma"
    persist.mkdir()
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(persist))
    from app.rag import store

    store.reset_chroma_client()
    yield persist
    store.reset_chroma_client()


@pytest.fixture()
def client(chroma_tmp, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    # Import after env is set; clear job registry between tests
    from app.routers import research as research_router

    research_router._jobs.clear()

    from app.main import app

    with TestClient(app) as c:
        yield c

    research_router._jobs.clear()
