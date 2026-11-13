"""Access key and per-IP limit for routes that can spend the Anthropic key.

Unset ``APP_API_KEY`` leaves local use open. Set it before the app is reachable
anywhere other than your own machine. The limit is in-memory and applies to
this process only.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def app_api_key() -> str:
    return (os.getenv("APP_API_KEY") or "").strip()


def auth_required() -> bool:
    return bool(app_api_key())


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def client_ip(request: Request) -> str:
    """Direct client, or the first X-Forwarded-For hop when TRUST_PROXY is set."""
    trust = (os.getenv("TRUST_PROXY") or "").strip().lower()
    if trust in {"1", "true", "yes"}:
        forwarded = request.headers.get("x-forwarded-for") or ""
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _presented_key(request: Request) -> str:
    header = (request.headers.get("x-api-key") or "").strip()
    if header:
        return header
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.cookies.get("research_access") or "").strip()


def _keys_match(presented: str, expected: str) -> bool:
    # Compare digests so a length mismatch cannot raise or short-circuit.
    left = hashlib.sha256(presented.encode()).digest()
    right = hashlib.sha256(expected.encode()).digest()
    return hmac.compare_digest(left, right)


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value


def _allow(bucket: str, limit: int, window_s: float) -> tuple[bool, int]:
    if limit <= 0:
        return True, 0
    now = time.monotonic()
    with _lock:
        recent = [stamp for stamp in _hits.get(bucket, []) if now - stamp < window_s]
        if len(recent) >= limit:
            _hits[bucket] = recent
            retry = max(1, int(window_s - (now - recent[0])) + 1)
            return False, retry
        recent.append(now)
        _hits[bucket] = recent
        return True, 0


def _too_many(retry_after: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


def require_access(request: Request) -> None:
    """Reject the request when an access key is configured and not presented."""
    expected = app_api_key()
    if not expected:
        return
    presented = _presented_key(request)
    if presented and _keys_match(presented, expected):
        return
    limit = _positive_int("AUTH_FAIL_LIMIT", 30)
    window = _positive_float("AUTH_FAIL_WINDOW_SECONDS", 60)
    allowed, retry_after = _allow(f"auth:{client_ip(request)}", limit, window)
    if not allowed:
        raise _too_many(retry_after, "Too many failed access attempts.")
    raise HTTPException(
        status_code=401,
        detail="Missing or invalid access key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def enforce_research_rate_limit(request: Request) -> None:
    """Cap how often one IP can start a research job."""
    limit = _positive_int("RESEARCH_RATE_LIMIT", 10)
    window = _positive_float("RESEARCH_RATE_WINDOW_SECONDS", 600)
    allowed, retry_after = _allow(f"research:{client_ip(request)}", limit, window)
    if not allowed:
        raise _too_many(
            retry_after,
            f"Too many research jobs from this address. Try again in {retry_after} seconds.",
        )
