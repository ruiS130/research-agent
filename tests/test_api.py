"""API and graph tests with mocked Claude / search."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.graph import build_research_graph, route_after_gap_check
from app.agent.state import ResearchState


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["anthropic_configured"] is True
    assert body.get("cost_mode") == "min"


def test_research_not_found(client):
    res = client.get("/research/does-not-exist")
    assert res.status_code == 404


def test_history_session_not_found(client):
    res = client.get("/history/does-not-exist")
    assert res.status_code == 404


def test_demo_ui(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Research Agent" in res.text


@pytest.mark.asyncio
async def test_route_after_gap_check(monkeypatch: pytest.MonkeyPatch):
    # Default min cost: never re-search
    monkeypatch.setenv("COST_MODE", "min")
    monkeypatch.delenv("MAX_GAP_LOOPS", raising=False)
    assert (
        route_after_gap_check({"gaps": ["missing data"], "iteration": 0}) == "done"
    )

    # Full-quality loop budget
    monkeypatch.setenv("COST_MODE", "full")
    monkeypatch.setenv("MAX_GAP_LOOPS", "2")
    assert (
        route_after_gap_check({"gaps": ["missing data"], "iteration": 0}) == "search"
    )
    assert route_after_gap_check({"gaps": ["x"], "iteration": 2}) == "done"
    assert route_after_gap_check({"gaps": [], "iteration": 0}) == "done"


@pytest.mark.asyncio
async def test_graph_happy_path_no_gap_loop(chroma_tmp):
    plan_out = json.dumps(["What is topic X?"])
    extract_out = json.dumps(
        {"key_points": ["Finding A"], "relevance_score": 0.9}
    )
    report = "# Report\n\nSummary of topic X.\n"
    gap_out = json.dumps({"gaps": [], "refined_queries": []})

    async def fake_claude(system: str, user: str, max_tokens: int = 4096) -> str:
        lower = system.lower()
        if "planner" in lower:
            return plan_out
        if "extract key findings" in lower:
            return extract_out
        if "synthesizer" in lower or "research brief" in lower:
            return report
        if "gaps" in lower or "review the research" in lower:
            return gap_out
        return report

    async def fake_search(query: str, max_results: int = 5):
        return [
            {
                "query": query,
                "url": "https://example.com/a",
                "title": "Example",
                "snippet": "Snippet",
            }
        ]

    async def fake_fetch(url: str, max_chars: int = 12000) -> str:
        return "Example page content about topic X."

    with (
        patch("app.agent.nodes.call_claude", new=AsyncMock(side_effect=fake_claude)),
        patch("app.agent.nodes.web_search", new=AsyncMock(side_effect=fake_search)),
        patch("app.agent.nodes.fetch_page", new=AsyncMock(side_effect=fake_fetch)),
    ):
        graph = build_research_graph()
        state: ResearchState = {
            "session_id": "test-session-1",
            "topic": "topic X",
            "sub_questions": [],
            "search_results": [],
            "extracted_findings": [],
            "report": "",
            "gaps": [],
            "iteration": 0,
            "status": "planning",
            "refined_queries": [],
            "use_past_research": False,
        }
        final = await graph.ainvoke(state)

    assert final["status"] == "done"
    assert "Report" in (final.get("report") or "")


def test_research_job_lifecycle(client):
    plan_out = json.dumps(["Subquestion one?"])
    extract_out = json.dumps(
        {"key_points": ["Point"], "relevance_score": 0.8}
    )
    report = "## Executive summary\n\nDone.\n"

    async def fake_claude(system: str, user: str, max_tokens: int = 4096) -> str:
        lower = system.lower()
        if "planner" in lower:
            return plan_out
        if "extract key findings" in lower:
            return extract_out
        if "synthesizer" in lower or "research brief" in lower:
            return report
        return report

    async def fake_search(query: str, max_results: int = 5):
        return [
            {
                "query": query,
                "url": "https://example.com/b",
                "title": "B",
                "snippet": "s",
            }
        ]

    with (
        patch("app.agent.nodes.call_claude", new=AsyncMock(side_effect=fake_claude)),
        patch("app.agent.nodes.web_search", new=AsyncMock(side_effect=fake_search)),
        patch(
            "app.agent.nodes.fetch_page",
            new=AsyncMock(return_value="Page text for research."),
        ),
    ):
        start = client.post(
            "/research",
            json={"topic": "solid-state batteries", "use_past_research": False},
        )
        assert start.status_code == 200
        job_id = start.json()["id"]

        status = client.get(f"/research/{job_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["id"] == job_id
        assert body["status"] == "done"
        assert body["report"]
        assert body.get("last_node") == "done"
        assert "cost" in body
        assert "timing" in body


def test_sqlite_survives_without_memory_dict(client):
    """Jobs persist in SQLite — no in-memory _jobs registry."""
    report = "Recovered report body"

    async def fake_claude(system: str, user: str, max_tokens: int = 4096) -> str:
        return report

    with (
        patch("app.agent.nodes.call_claude", new=AsyncMock(side_effect=fake_claude)),
        patch(
            "app.agent.nodes.web_search",
            new=AsyncMock(
                return_value=[
                    {
                        "query": "q",
                        "url": "https://example.com/c",
                        "title": "C",
                        "snippet": "s",
                    }
                ]
            ),
        ),
        patch(
            "app.agent.nodes.fetch_page",
            new=AsyncMock(return_value="content"),
        ),
    ):
        start = client.post(
            "/research",
            json={"topic": "recovery topic", "use_past_research": False},
        )
        job_id = start.json()["id"]
        assert client.get(f"/research/{job_id}").json()["status"] == "done"

    from app.jobs.store import get_job

    row = get_job(job_id)
    assert row is not None
    assert row["status"] == "done"
    assert "Recovered report" in (row.get("report") or "")

    recovered = client.get(f"/research/{job_id}")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "done"
    assert "Recovered report" in recovered.json()["report"]

    detail = client.get(f"/history/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["topic"] == "recovery topic"


def test_no_in_memory_jobs_dict():
    from app.routers import research as research_router

    assert not hasattr(research_router, "_jobs")
