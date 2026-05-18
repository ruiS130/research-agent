"""LangGraph node functions for each research pipeline step."""

import json
import os
import re
from typing import Any

import anthropic
from anthropic import APIConnectionError, APIStatusError, RateLimitError

from app.agent.state import ResearchState
from app.agent.tools import fetch_page, store_to_rag, web_search
from app.rag.memory import get_past_context_for_topic
from app.rag.retriever import format_sources_for_response

MODEL = "claude-sonnet-4-20250514"
MAX_SOURCES_PER_QUERY = 3


def _client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


async def call_claude(
    system: str,
    user: str,
    max_tokens: int = 4096,
) -> str:
    """Claude call with 3 retries and exponential backoff."""
    client = _client()
    delays = [1.0, 2.0, 4.0]
    last_error: Exception | None = None

    for attempt, delay in enumerate(delays, start=1):
        try:
            message = await client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            parts = [
                block.text
                for block in message.content
                if block.type == "text"
            ]
            return "".join(parts).strip()
        except (RateLimitError, APIConnectionError, APIStatusError) as exc:
            last_error = exc
            if attempt == len(delays):
                break
            import asyncio

            await asyncio.sleep(delay)

    raise RuntimeError(f"Claude API failed after retries: {last_error}")


def _parse_json_array(text: str) -> list[str]:
    """Extract a JSON string array from model output."""
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        data = json.loads(match.group())
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


def _parse_json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        data = json.loads(match.group())
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


async def plan_node(state: ResearchState) -> ResearchState:
    topic = state["topic"]
    past_context = ""
    if state.get("use_past_research", True):
        past_context = await get_past_context_for_topic(topic)

    system = (
        "You are a research planner. Decompose the user's topic into 3-5 "
        "focused sub-questions that together cover the topic thoroughly. "
        "Return ONLY a JSON array of strings, no other text."
    )
    user = f"Topic: {topic}\n"
    if past_context:
        user += f"\nRelevant past research:\n{past_context}\n"
    user += "\nOutput a JSON array of 3-5 sub-questions."

    raw = await call_claude(system, user, max_tokens=1024)
    sub_questions = _parse_json_array(raw)
    if not sub_questions:
        sub_questions = [topic]

    return {
        **state,
        "sub_questions": sub_questions[:5],
        "status": "searching",
    }


async def search_node(state: ResearchState) -> ResearchState:
    queries = list(state.get("sub_questions") or [])
    refined = state.get("refined_queries") or []
    if refined:
        queries = refined

    all_results: list[dict] = list(state.get("search_results") or [])
    seen_urls = {r["url"] for r in all_results if r.get("url")}

    for query in queries:
        hits = await web_search(query, max_results=5)
        for hit in hits:
            if hit["url"] not in seen_urls:
                seen_urls.add(hit["url"])
                all_results.append(hit)

    return {
        **state,
        "search_results": all_results,
        "refined_queries": [],
        "status": "extracting",
    }


async def extract_node(state: ResearchState) -> ResearchState:
    results = state.get("search_results") or []
    topic = state["topic"]
    findings: list[dict] = list(state.get("extracted_findings") or [])
    seen_urls = {f["source_url"] for f in findings}

    # Group by query, take top N unique URLs
    by_query: dict[str, list[dict]] = {}
    for row in results:
        by_query.setdefault(row["query"], []).append(row)

    for _query, rows in by_query.items():
        count = 0
        for row in rows:
            if count >= MAX_SOURCES_PER_QUERY:
                break
            url = row["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            try:
                page_text = await fetch_page(url)
            except Exception:
                page_text = row.get("snippet", "")

            if not page_text.strip():
                continue

            system = (
                "Extract key findings from the source for the research topic. "
                "Respond with JSON only: "
                '{"key_points": ["..."], "relevance_score": 0.0-1.0}'
            )
            user = (
                f"Topic: {topic}\n"
                f"Source title: {row.get('title', '')}\n"
                f"URL: {url}\n\n"
                f"Content:\n{page_text[:8000]}"
            )
            raw = await call_claude(system, user, max_tokens=2048)
            parsed = _parse_json_object(raw)
            key_points = parsed.get("key_points") or []
            if isinstance(key_points, str):
                key_points = [key_points]
            score = float(parsed.get("relevance_score", 0.5))

            findings.append(
                {
                    "source_url": url,
                    "title": row.get("title", ""),
                    "key_points": key_points,
                    "relevance_score": score,
                }
            )
            count += 1

    return {
        **state,
        "extracted_findings": findings,
        "status": "synthesizing",
    }


async def synthesize_node(state: ResearchState) -> ResearchState:
    topic = state["topic"]
    findings = state.get("extracted_findings") or []

    findings_text = json.dumps(findings, indent=2)
    system = (
        "You are a research synthesizer. Merge the extracted findings into a "
        "clear, structured markdown report with inline citations [1], [2] "
        "mapping to source URLs listed at the end. Include an executive "
        "summary, key findings, and open questions."
    )
    user = f"Topic: {topic}\n\nFindings:\n{findings_text}"

    report = await call_claude(system, user, max_tokens=8192)

    return {
        **state,
        "report": report,
        "status": "checking",
    }


async def gap_check_node(state: ResearchState) -> ResearchState:
    topic = state["topic"]
    report = state.get("report") or ""

    system = (
        "Review the research report for gaps, contradictions, or weak evidence. "
        "If significant gaps remain, return JSON: "
        '{"gaps": ["gap description"], "refined_queries": ["search query"]} '
        "with 1-3 refined search queries to fill gaps. "
        "If the report is solid, return: "
        '{"gaps": [], "refined_queries": []}'
    )
    user = f"Topic: {topic}\n\nReport:\n{report}"

    raw = await call_claude(system, user, max_tokens=2048)
    parsed = _parse_json_object(raw)
    gaps = parsed.get("gaps") or []
    refined = parsed.get("refined_queries") or []
    if isinstance(gaps, str):
        gaps = [gaps]
    if isinstance(refined, str):
        refined = [refined]

    iteration = state.get("iteration", 0)
    if gaps and iteration < 2:
        return {
            **state,
            "gaps": gaps,
            "refined_queries": refined,
            "iteration": iteration + 1,
            "status": "searching",
        }

    return {
        **state,
        "gaps": gaps,
        "refined_queries": [],
        "status": "done",
    }


async def done_node(state: ResearchState) -> ResearchState:
    session_id = state["session_id"]
    topic = state["topic"]
    report = state.get("report") or ""
    sources = format_sources_for_response(state.get("extracted_findings") or [])

    await store_to_rag(session_id, topic, report, sources)

    return {
        **state,
        "status": "done",
    }
