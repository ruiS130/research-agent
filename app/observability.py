"""Structured JSON logs + per-job token/cost tracking."""

from __future__ import annotations

import json
import logging
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

_current_job_id: ContextVar[str | None] = ContextVar("current_job_id", default=None)

# Rough USD per 1M tokens (override via env). Defaults approximate public list prices.
_DEFAULT_RATES: dict[str, tuple[float, float]] = {
    # (input_per_mtok, output_per_mtok)
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
}


@dataclass
class JobMetrics:
    job_id: str
    model: str = ""
    cost_mode: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0
    node_timings_ms: dict[str, float] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += max(0, input_tokens)
        self.output_tokens += max(0, output_tokens)
        self.api_calls += 1

    def record_node(self, node: str, elapsed_ms: float) -> None:
        prev = self.node_timings_ms.get(node, 0.0)
        self.node_timings_ms[node] = round(prev + elapsed_ms, 2)

    def estimated_usd(self) -> float:
        in_rate, out_rate = _rates_for_model(self.model)
        return (self.input_tokens / 1_000_000.0) * in_rate + (
            self.output_tokens / 1_000_000.0
        ) * out_rate

    def total_ms(self) -> float:
        return round((time.perf_counter() - self.started_at) * 1000.0, 2)

    def to_cost_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "cost_mode": self.cost_mode,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "api_calls": self.api_calls,
            "estimated_usd": round(self.estimated_usd(), 6),
            "total_ms": self.total_ms(),
        }

    def to_timing_dict(self) -> dict[str, Any]:
        return dict(self.node_timings_ms)


_metrics: dict[str, JobMetrics] = {}


def _rates_for_model(model: str) -> tuple[float, float]:
    if os.getenv("ANTHROPIC_INPUT_USD_PER_MTOK") and os.getenv(
        "ANTHROPIC_OUTPUT_USD_PER_MTOK"
    ):
        return (
            float(os.environ["ANTHROPIC_INPUT_USD_PER_MTOK"]),
            float(os.environ["ANTHROPIC_OUTPUT_USD_PER_MTOK"]),
        )
    if model in _DEFAULT_RATES:
        return _DEFAULT_RATES[model]
    # Conservative mid-tier default
    return (3.00, 15.00)


def configure_logging() -> None:
    root = logging.getLogger("research_agent")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    root.propagate = False


def log_event(event: str, **fields: Any) -> None:
    configure_logging()
    payload = {"event": event, **fields}
    job_id = fields.get("job_id") or _current_job_id.get()
    if job_id and "job_id" not in payload:
        payload["job_id"] = job_id
    logging.getLogger("research_agent").info(json.dumps(payload, default=str))


def begin_job_metrics(job_id: str, *, model: str, cost_mode: str) -> JobMetrics:
    m = JobMetrics(job_id=job_id, model=model, cost_mode=cost_mode)
    _metrics[job_id] = m
    _current_job_id.set(job_id)
    return m


def get_job_metrics(job_id: str) -> JobMetrics | None:
    return _metrics.get(job_id)


def end_job_metrics(job_id: str) -> JobMetrics | None:
    m = _metrics.pop(job_id, None)
    if _current_job_id.get() == job_id:
        _current_job_id.set(None)
    return m


def record_api_usage(input_tokens: int, output_tokens: int) -> None:
    job_id = _current_job_id.get()
    if not job_id:
        return
    m = _metrics.get(job_id)
    if m:
        m.add_usage(input_tokens, output_tokens)


def set_current_job(job_id: str | None) -> None:
    _current_job_id.set(job_id)
