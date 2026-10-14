"""Cost / quality knobs. Default is absolute minimum Anthropic spend."""

from __future__ import annotations

import os


def cost_mode() -> str:
    """`min` (default) = fewest API calls; `full` = original thorough pipeline."""
    mode = (os.getenv("COST_MODE") or "min").strip().lower()
    return mode if mode in {"min", "full"} else "min"


def is_min_cost() -> bool:
    return cost_mode() == "min"


def anthropic_model() -> str:
    # Haiku by default — much cheaper than Sonnet.
    return os.getenv("ANTHROPIC_MODEL") or "claude-3-5-haiku-20241022"


def max_gap_loops() -> int:
    if is_min_cost():
        return int(os.getenv("MAX_GAP_LOOPS", "0"))
    return int(os.getenv("MAX_GAP_LOOPS", "2"))


def max_sub_questions() -> int:
    if is_min_cost():
        return int(os.getenv("MAX_SUB_QUESTIONS", "1"))
    return int(os.getenv("MAX_SUB_QUESTIONS", "5"))


def max_sources_per_query() -> int:
    if is_min_cost():
        return int(os.getenv("MAX_SOURCES_PER_QUERY", "2"))
    return int(os.getenv("MAX_SOURCES_PER_QUERY", "3"))


def max_search_results() -> int:
    if is_min_cost():
        return int(os.getenv("MAX_SEARCH_RESULTS", "3"))
    return int(os.getenv("MAX_SEARCH_RESULTS", "5"))


def synthesize_max_tokens() -> int:
    if is_min_cost():
        return int(os.getenv("SYNTHESIZE_MAX_TOKENS", "1024"))
    return int(os.getenv("SYNTHESIZE_MAX_TOKENS", "4096"))


def page_chars_for_llm() -> int:
    """How much page text to send to Claude (full mode extract only)."""
    if is_min_cost():
        return 0
    return int(os.getenv("PAGE_CHARS_FOR_LLM", "4000"))
