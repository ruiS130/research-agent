"""Tests for search provider selection and fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_web_search_uses_tavily_when_configured(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    fake = [
        {
            "query": "q",
            "url": "https://example.com/t",
            "title": "T",
            "snippet": "s",
        }
    ]

    with patch(
        "app.agent.tools._search_tavily", new=AsyncMock(return_value=fake)
    ) as tavily:
        from app.agent.tools import web_search

        out = await web_search("q", max_results=3)
        assert out == fake
        tavily.assert_awaited_once()


@pytest.mark.asyncio
async def test_ddg_empty_falls_back_to_tavily(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "ddg")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

    fallback = [
        {
            "query": "q",
            "url": "https://example.com/fb",
            "title": "FB",
            "snippet": "s",
        }
    ]

    with (
        patch("app.agent.tools._search_ddg", new=AsyncMock(return_value=[])),
        patch(
            "app.agent.tools._search_tavily", new=AsyncMock(return_value=fallback)
        ) as tavily,
    ):
        from app.agent.tools import web_search

        out = await web_search("q")
        assert out == fallback
        tavily.assert_awaited_once()
