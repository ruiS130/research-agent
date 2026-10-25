"""Structured JSON logs + per-job token/cost tracking.

Every Claude call logs ``usage.input_tokens`` and ``usage.output_tokens``
under the LangGraph node that made it. Job cost is the sum of those calls.
Haiku 5.5 bills the whole request at 5x when input tokens exceed 100K; calls
that could cross that line are flagged, and calls that do cross it are priced
with the surcharge.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

_current_job_id: ContextVar[str | None] = ContextVar("current_job_id", default=None)
_current_node: ContextVar[str | None] = ContextVar("current_llm_node", default=None)

# Rough USD per 1M tokens (override via env). Defaults approximate public list prices.
_DEFAULT_RATES: dict[str, tuple[float, float]] = {
    # (input_per_mtok, output_per_mtok) — approximate list prices
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
}

# Extra tokens added to the char heuristic so message framing is not ignored.
_ESTIMATE_OVERHEAD_TOKENS = 32


def long_context_input_threshold() -> int:
    """Input-token count above which Haiku 5.5 bills the whole request at 5x."""
    return _positive_int_env("HAIKU_LONG_CONTEXT_TOKENS", 100_000)


def long_context_multiplier() -> float:
    """Surcharge applied to the whole Haiku 5.5 request above the threshold."""
    return _positive_float_env("HAIKU_LONG_CONTEXT_MULTIPLIER", 5.0)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def estimate_input_tokens(system: str, user: str) -> int:
    """Conservative token estimate for a system + user prompt.

    English is often ~4 characters per token. JSON and dense source text run
    closer to 3, so this uses 3 to flag prompts that *could* cross 100K
    before the API bills them. A small overhead covers message framing.
    """
    chars = len(system or "") + len(user or "")
    return (chars + 2) // 3 + _ESTIMATE_OVERHEAD_TOKENS


def _is_haiku_55(model: str) -> bool:
    """True for Haiku 5 / 5.5 ids. Haiku 4.5 ids (``haiku-4-5``) do not match."""
    return "haiku-5" in (model or "").lower()


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


def price_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    threshold: int | None = None,
    multiplier: float | None = None,
) -> tuple[float, bool, float]:
    """Return ``(usd, surcharge_applied, multiplier_used)``.

    The surcharge multiplies both input and output, because Haiku 5.5 bills
    the whole request at 5x once input tokens are above the threshold.
    """
    limit = long_context_input_threshold() if threshold is None else threshold
    mult = long_context_multiplier() if multiplier is None else multiplier
    in_rate, out_rate = _rates_for_model(model)
    base = (max(0, input_tokens) / 1_000_000.0) * in_rate + (
        max(0, output_tokens) / 1_000_000.0
    ) * out_rate
    if _is_haiku_55(model) and input_tokens > limit:
        return base * mult, True, mult
    return base, False, 1.0


@dataclass
class LlmCall:
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_input_tokens: int
    estimated_usd: float
    surcharge: bool
    prompt_could_exceed: bool
    multiplier: float
    threshold: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    max_tokens: int | None = None


def _make_call(
    *,
    node: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    estimated_input_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    max_tokens: int | None = None,
) -> LlmCall:
    in_tok = max(0, input_tokens)
    out_tok = max(0, output_tokens)
    estimated = max(0, estimated_input_tokens)
    threshold = long_context_input_threshold()
    multiplier = long_context_multiplier()
    usd, surcharge, used = price_call(
        model, in_tok, out_tok, threshold=threshold, multiplier=multiplier
    )
    return LlmCall(
        node=node or "unknown",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_input_tokens=estimated,
        estimated_usd=usd,
        surcharge=surcharge,
        prompt_could_exceed=estimated >= threshold,
        multiplier=used,
        threshold=threshold,
        cache_read_input_tokens=max(0, cache_read_input_tokens),
        cache_creation_input_tokens=max(0, cache_creation_input_tokens),
        max_tokens=max_tokens,
    )


@dataclass
class JobMetrics:
    job_id: str
    model: str = ""
    cost_mode: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0
    node_timings_ms: dict[str, float] = field(default_factory=dict)
    calls: list[LlmCall] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        node: str = "unknown",
        model: str | None = None,
        estimated_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        max_tokens: int | None = None,
    ) -> LlmCall:
        call = _make_call(
            node=node,
            model=model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_input_tokens=estimated_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            max_tokens=max_tokens,
        )
        self.calls.append(call)
        self.input_tokens += call.input_tokens
        self.output_tokens += call.output_tokens
        self.api_calls += 1
        return call

    def record_node(self, node: str, elapsed_ms: float) -> None:
        prev = self.node_timings_ms.get(node, 0.0)
        self.node_timings_ms[node] = round(prev + elapsed_ms, 2)

    def estimated_usd(self) -> float:
        return sum(call.estimated_usd for call in self.calls)

    def total_ms(self) -> float:
        return round((time.perf_counter() - self.started_at) * 1000.0, 2)

    def nodes_ranked(self) -> list[dict[str, Any]]:
        """Per-node token and cost totals, highest cost first."""
        buckets: dict[str, dict[str, Any]] = {}
        for call in self.calls:
            bucket = buckets.get(call.node)
            if bucket is None:
                bucket = {
                    "node": call.node,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "api_calls": 0,
                    "estimated_usd": 0.0,
                    "max_input_tokens": 0,
                    "max_estimated_input_tokens": 0,
                    "long_context": False,
                }
                buckets[call.node] = bucket
            bucket["input_tokens"] += call.input_tokens
            bucket["output_tokens"] += call.output_tokens
            bucket["api_calls"] += 1
            bucket["estimated_usd"] += call.estimated_usd
            bucket["max_input_tokens"] = max(
                bucket["max_input_tokens"], call.input_tokens
            )
            bucket["max_estimated_input_tokens"] = max(
                bucket["max_estimated_input_tokens"], call.estimated_input_tokens
            )
            if call.prompt_could_exceed or call.surcharge:
                bucket["long_context"] = True
        total = self.estimated_usd()
        rows: list[dict[str, Any]] = []
        for bucket in buckets.values():
            usd = float(bucket["estimated_usd"])
            rows.append(
                {
                    **bucket,
                    "estimated_usd": round(usd, 6),
                    "share": round(usd / total, 4) if total else 0.0,
                }
            )
        rows.sort(
            key=lambda row: (-row["estimated_usd"], -row["input_tokens"], row["node"])
        )
        return rows

    def usage_for(self, node: str) -> dict[str, Any]:
        for row in self.nodes_ranked():
            if row["node"] == node:
                return row
        return {
            "node": node,
            "input_tokens": 0,
            "output_tokens": 0,
            "api_calls": 0,
            "estimated_usd": 0.0,
            "share": 0.0,
            "max_input_tokens": 0,
            "max_estimated_input_tokens": 0,
            "long_context": False,
        }

    def long_context_flags(self) -> list[dict[str, Any]]:
        flags: list[dict[str, Any]] = []
        for index, call in enumerate(self.calls):
            if call.prompt_could_exceed:
                flags.append(
                    {
                        "call_index": index,
                        "node": call.node,
                        "kind": "prompt_could_exceed_100k",
                        "estimated_input_tokens": call.estimated_input_tokens,
                        "input_tokens": call.input_tokens,
                        "threshold": call.threshold,
                    }
                )
            if call.surcharge:
                flags.append(
                    {
                        "call_index": index,
                        "node": call.node,
                        "kind": "billed_5x",
                        "input_tokens": call.input_tokens,
                        "output_tokens": call.output_tokens,
                        "threshold": call.threshold,
                        "multiplier": call.multiplier,
                    }
                )
        return flags

    def to_cost_dict(self) -> dict[str, Any]:
        nodes = self.nodes_ranked()
        return {
            "model": self.model,
            "cost_mode": self.cost_mode,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "api_calls": self.api_calls,
            "estimated_usd": round(self.estimated_usd(), 6),
            "total_ms": self.total_ms(),
            "dominant_node": nodes[0]["node"] if nodes else None,
            "nodes": nodes,
            "long_context_flags": self.long_context_flags(),
        }

    def to_timing_dict(self) -> dict[str, Any]:
        return dict(self.node_timings_ms)


_metrics: dict[str, JobMetrics] = {}


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


def current_llm_node() -> str:
    return _current_node.get() or "unknown"


@contextmanager
def bind_llm_node(node: str) -> Iterator[None]:
    """Attribute Claude calls inside this block to a LangGraph node."""
    token = _current_node.set(node)
    try:
        yield
    finally:
        _current_node.reset(token)


def _log_llm_call(job_id: str | None, call: LlmCall) -> None:
    fields: dict[str, Any] = {
        "node": call.node,
        "model": call.model,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "estimated_input_tokens": call.estimated_input_tokens,
        "cache_read_input_tokens": call.cache_read_input_tokens,
        "cache_creation_input_tokens": call.cache_creation_input_tokens,
        "max_tokens": call.max_tokens,
        "estimated_usd": round(call.estimated_usd, 6),
        "long_context_surcharge": call.surcharge,
        "prompt_could_exceed_100k": call.prompt_could_exceed,
    }
    if job_id:
        fields["job_id"] = job_id
    log_event("llm_usage", **fields)
    if call.surcharge:
        log_event(
            "llm_long_context",
            node=call.node,
            model=call.model,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            multiplier=call.multiplier,
            threshold=call.threshold,
            estimated_usd=round(call.estimated_usd, 6),
            detail=(
                "Haiku 5.5 bills this whole request at "
                f"{call.multiplier:g}x because input_tokens exceeded "
                f"{call.threshold}."
            ),
            **({"job_id": job_id} if job_id else {}),
        )


def record_api_usage(
    input_tokens: int,
    output_tokens: int,
    *,
    node: str | None = None,
    model: str | None = None,
    estimated_input_tokens: int = 0,
    max_tokens: int | None = None,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> None:
    """Record one Claude response's token usage and log it for its node."""
    node_name = node or current_llm_node()
    job_id = _current_job_id.get()
    metrics = _metrics.get(job_id) if job_id else None
    model_name = model or (
        metrics.model if metrics else os.getenv("ANTHROPIC_MODEL") or "claude-haiku-5-5"
    )
    call_kwargs = dict(
        node=node_name,
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_input_tokens=estimated_input_tokens,
        max_tokens=max_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
    )
    if metrics is not None:
        call = metrics.add_usage(**call_kwargs)
    else:
        call = _make_call(**call_kwargs)
    _log_llm_call(job_id, call)


def set_current_job(job_id: str | None) -> None:
    _current_job_id.set(job_id)
