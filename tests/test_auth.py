"""Access key and research start rate limit."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _start(client, headers=None):
    return client.post(
        "/research",
        json={"topic": "solid-state batteries", "use_past_research": False},
        headers=headers or {},
    )


def test_health_reports_auth_off_by_default(client):
    body = client.get("/health").json()
    assert body["auth_required"] is False


def test_research_and_history_require_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "local-secret")
    assert client.get("/health").json()["auth_required"] is True
    assert client.get("/").status_code == 200

    open_post = _start(client)
    assert open_post.status_code == 401

    assert client.get("/history").status_code == 401
    assert client.get("/research/missing").status_code == 401

    denied = _start(client, {"X-API-Key": "nope"})
    assert denied.status_code == 401

    with patch("app.agent.nodes.call_claude", new=AsyncMock(return_value="Report")):
        with patch(
            "app.agent.nodes.web_search",
            new=AsyncMock(
                return_value=[
                    {
                        "query": "q",
                        "url": "https://example.com/a",
                        "title": "A",
                        "snippet": "s",
                    }
                ]
            ),
        ):
            ok = _start(client, {"Authorization": "Bearer local-secret"})
    assert ok.status_code == 200

    listed = client.get("/history", headers={"X-API-Key": "local-secret"})
    assert listed.status_code == 200

    client.cookies.set("research_access", "local-secret")
    via_cookie = client.get("/history")
    assert via_cookie.status_code == 200
    client.cookies.clear()


def test_research_start_is_rate_limited(client, monkeypatch):
    monkeypatch.setenv("RESEARCH_RATE_LIMIT", "2")
    monkeypatch.setenv("RESEARCH_RATE_WINDOW_SECONDS", "600")
    from app.security import reset_rate_limits

    reset_rate_limits()

    with patch("app.agent.nodes.call_claude", new=AsyncMock(return_value="Report")):
        with patch(
            "app.agent.nodes.web_search",
            new=AsyncMock(return_value=[]),
        ):
            first = _start(client)
            second = _start(client)
            third = _start(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers.get("retry-after")
    assert "Too many research jobs" in third.json()["detail"]


@pytest.mark.asyncio
async def test_failed_access_attempts_are_limited(client, monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "local-secret")
    monkeypatch.setenv("AUTH_FAIL_LIMIT", "2")
    monkeypatch.setenv("AUTH_FAIL_WINDOW_SECONDS", "60")
    from app.security import reset_rate_limits

    reset_rate_limits()

    assert _start(client, {"X-API-Key": "wrong"}).status_code == 401
    assert _start(client).status_code == 401
    blocked = _start(client, {"X-API-Key": "still-wrong"})
    assert blocked.status_code == 429
