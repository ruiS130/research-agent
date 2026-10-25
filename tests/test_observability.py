"""Cost / metrics helpers and per-node LLM usage logs."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.nodes import call_claude
from app.agent.state import ResearchState
from app.observability import (
    JobMetrics,
    begin_job_metrics,
    bind_llm_node,
    end_job_metrics,
    estimate_input_tokens,
    long_context_input_threshold,
    record_api_usage,
)


def test_estimated_usd_haiku_below_long_context():
    m = JobMetrics(job_id="x", model="claude-haiku-5-5", cost_mode="min")
    # Exactly 100K input is not above the threshold, so list price applies.
    m.add_usage(input_tokens=100_000, output_tokens=100_000, node="synthesize")
    # 0.01 + 0.05 = 0.06
    assert abs(m.estimated_usd() - 0.06) < 1e-9
    assert m.to_cost_dict()["long_context_flags"] == []


def test_haiku_55_bills_whole_request_at_5x_above_100k():
    m = JobMetrics(job_id="x", model="claude-haiku-5-5", cost_mode="full")
    m.add_usage(input_tokens=100_001, output_tokens=1_000, node="synthesize")
    base = (100_001 / 1_000_000) * 0.10 + (1_000 / 1_000_000) * 0.50
    assert abs(m.estimated_usd() - 5 * base) < 1e-9
    flags = m.to_cost_dict()["long_context_flags"]
    assert [f["kind"] for f in flags] == ["billed_5x"]
    assert flags[0]["node"] == "synthesize"
    assert flags[0]["multiplier"] == 5


def test_long_context_surcharge_is_per_request_not_per_job():
    m = JobMetrics(job_id="x", model="claude-haiku-5-5", cost_mode="full")
    m.add_usage(60_000, 1_000, node="extract")
    m.add_usage(60_000, 1_000, node="extract")
    base = 2 * ((60_000 / 1_000_000) * 0.10 + (1_000 / 1_000_000) * 0.50)
    assert abs(m.estimated_usd() - base) < 1e-9
    assert m.to_cost_dict()["long_context_flags"] == []


def test_sonnet_and_older_haiku_do_not_get_the_5x_flag():
    sonnet = JobMetrics(job_id="s", model="claude-sonnet-5-5", cost_mode="full")
    sonnet.add_usage(200_000, 1_000, node="synthesize")
    expected = (200_000 / 1_000_000) * 2.0 + (1_000 / 1_000_000) * 10.0
    assert abs(sonnet.estimated_usd() - expected) < 1e-9

    haiku4 = JobMetrics(job_id="h", model="claude-haiku-4-5-20251001", cost_mode="full")
    haiku4.add_usage(200_000, 1_000, node="synthesize")
    expected4 = (200_000 / 1_000_000) * 1.0 + (1_000 / 1_000_000) * 5.0
    assert abs(haiku4.estimated_usd() - expected4) < 1e-9


def test_nodes_ranked_by_cost():
    m = JobMetrics(job_id="x", model="claude-haiku-5-5", cost_mode="full")
    m.add_usage(100, 10, node="plan")
    m.add_usage(1_000, 100, node="extract")
    m.add_usage(5_000, 2_000, node="synthesize")
    report = m.to_cost_dict()
    assert report["dominant_node"] == "synthesize"
    assert [row["node"] for row in report["nodes"]] == [
        "synthesize",
        "extract",
        "plan",
    ]
    assert report["nodes"][0]["share"] > report["nodes"][1]["share"]
    assert report["input_tokens"] == 6_100
    assert report["output_tokens"] == 2_110
    assert report["api_calls"] == 3


def test_record_api_usage_via_context():
    begin_job_metrics("job-obs", model="claude-haiku-5-5", cost_mode="min")
    with bind_llm_node("gap_check"):
        record_api_usage(100, 50)
    m = end_job_metrics("job-obs")
    assert m is not None
    assert m.api_calls == 1
    assert m.input_tokens == 100
    assert m.output_tokens == 50
    assert m.to_cost_dict()["dominant_node"] == "gap_check"


def test_estimate_flags_prompts_that_could_exceed_100k():
    assert long_context_input_threshold() == 100_000
    assert estimate_input_tokens("short", "prompt") < 100_000
    assert estimate_input_tokens("x" * 400_000, "") >= 100_000


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class _Message:
    def __init__(self, text: str, input_tokens: int, output_tokens: int) -> None:
        self.content = [_Block(text)]
        self.usage = _Usage(input_tokens, output_tokens)


class _Client:
    def __init__(self, text: str, input_tokens: int, output_tokens: int) -> None:
        self._message = _Message(text, input_tokens, output_tokens)
        self.messages = self

    async def create(self, **kwargs):
        system = kwargs["system"].lower()
        if "planner" in system:
            return _Message('["What is topic X?"]', 100, 20)
        if "extract key findings" in system:
            return _Message(
                '{"key_points": ["Finding A"], "relevance_score": 0.9}',
                400,
                40,
            )
        if "synthesizer" in system or "research brief" in system:
            return _Message("# Report\n\nSummary.\n", 800, 200)
        if "gaps" in system or "review the research" in system:
            return _Message('{"gaps": [], "refined_queries": []}', 300, 30)
        return self._message


@pytest.mark.asyncio
async def test_call_claude_logs_usage_and_long_context_risk(monkeypatch):
    monkeypatch.setenv("HAIKU_LONG_CONTEXT_TOKENS", "50")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    events: list[tuple[str, dict]] = []

    def capture(event: str, **fields):
        events.append((event, fields))

    begin_job_metrics("job-long", model="claude-haiku-5-5", cost_mode="full")
    try:
        with (
            patch("app.agent.nodes._client", return_value=_Client("ok", 40, 5)),
            patch("app.observability.log_event", side_effect=capture),
            bind_llm_node("extract"),
        ):
            text = await call_claude("s" * 100, "u" * 100, max_tokens=16)
        assert text == "ok"
    finally:
        metrics = end_job_metrics("job-long")

    kinds = [event for event, _fields in events]
    assert "llm_long_context_risk" in kinds
    assert "llm_long_context" not in kinds
    usage = next(fields for event, fields in events if event == "llm_usage")
    assert usage["node"] == "extract"
    assert usage["input_tokens"] == 40
    assert usage["output_tokens"] == 5
    assert usage["prompt_could_exceed_100k"] is True
    assert usage["long_context_surcharge"] is False
    assert metrics is not None
    assert metrics.usage_for("extract")["input_tokens"] == 40
    assert metrics.to_cost_dict()["long_context_flags"][0]["kind"] == (
        "prompt_could_exceed_100k"
    )


@pytest.mark.asyncio
async def test_call_claude_prices_actual_input_over_100k(monkeypatch):
    monkeypatch.setenv("HAIKU_LONG_CONTEXT_TOKENS", "100")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    events: list[str] = []

    def capture(event: str, **fields):
        events.append(event)

    begin_job_metrics("job-billed", model="claude-haiku-5-5", cost_mode="full")
    try:
        with (
            patch("app.agent.nodes._client", return_value=_Client("ok", 101, 10)),
            patch("app.observability.log_event", side_effect=capture),
            bind_llm_node("synthesize"),
        ):
            await call_claude("hi", "there", max_tokens=32)
    finally:
        metrics = end_job_metrics("job-billed")

    assert "llm_long_context_risk" not in events
    assert "llm_long_context" in events
    assert metrics is not None
    base = (101 / 1_000_000) * 0.10 + (10 / 1_000_000) * 0.50
    assert abs(metrics.estimated_usd() - 5 * base) < 1e-12
    assert metrics.to_cost_dict()["dominant_node"] == "synthesize"


@pytest.mark.asyncio
async def test_full_graph_attributes_tokens_to_nodes(chroma_tmp, monkeypatch):
    monkeypatch.setenv("COST_MODE", "full")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("MAX_SUB_QUESTIONS", "1")
    monkeypatch.setenv("MAX_SOURCES_PER_QUERY", "1")
    monkeypatch.setenv("MAX_SEARCH_RESULTS", "1")
    monkeypatch.setenv("MAX_GAP_LOOPS", "1")

    async def fake_search(query: str, max_results: int = 5):
        return [
            {
                "query": query,
                "url": "https://example.com/a",
                "title": "Example",
                "snippet": "Snippet",
            }
        ]

    from app.agent.graph import build_research_graph

    begin_job_metrics("job-graph", model="claude-haiku-5-5", cost_mode="full")
    try:
        with (
            patch("app.agent.nodes._client", return_value=_Client("ok", 1, 1)),
            patch("app.agent.nodes.web_search", new=AsyncMock(side_effect=fake_search)),
            patch(
                "app.agent.nodes.fetch_page",
                new=AsyncMock(return_value="Page about topic X."),
            ),
        ):
            graph = build_research_graph()
            state: ResearchState = {
                "session_id": "usage-session",
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
    finally:
        metrics = end_job_metrics("job-graph")

    assert final["status"] == "done"
    assert metrics is not None
    assert metrics.input_tokens == 100 + 400 + 800 + 300
    assert metrics.output_tokens == 20 + 40 + 200 + 30
    report = metrics.to_cost_dict()
    assert report["dominant_node"] == "synthesize"
    assert [row["node"] for row in report["nodes"]] == [
        "synthesize",
        "extract",
        "gap_check",
        "plan",
    ]
    assert report["api_calls"] == 4
    assert report["long_context_flags"] == []
