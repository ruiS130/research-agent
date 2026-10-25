"""Score a report on facts, citation match, and coverage.

Citations score the fraction of inline markers whose URL is in the sources
the pipeline actually retrieved. A URL invented in the report does not count.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.eval.dataset import EVAL_CASES, EvalCase, Phrase

_CITE_RE = re.compile(r"\[(\d+)\]")
_URL_RE = re.compile(r"https?://[^\s\]\)>\"']+")
_SOURCES_HEADING = re.compile(r"(?im)^(?:#{1,6}[ \t]+)?sources[ \t]*:?[ \t]*$")

DIMENSIONS = ("factual", "citations", "coverage", "overall")


def _contains(text: str, phrase: str) -> bool:
    hay = text.lower()
    needle = phrase.lower()
    if len(needle) <= 4 and needle.isalnum():
        return (
            re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", hay)
            is not None
        )
    return needle in hay


def _hit(text: str, options: Phrase) -> bool:
    return any(_contains(text, option) for option in options)


def _label(options: Phrase) -> str:
    return " | ".join(options)


def _normalize_url(url: str) -> str:
    cleaned = url.strip().rstrip(".,;)")
    parsed = urlparse(cleaned)
    if not parsed.scheme or not parsed.hostname:
        return cleaned.lower()
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{path}"


def _split_sources(report: str) -> tuple[str, str]:
    match = _SOURCES_HEADING.search(report)
    if not match:
        return report, ""
    return report[: match.start()], report[match.end() :]


def _urls(text: str) -> list[str]:
    return [_normalize_url(url) for url in _URL_RE.findall(text)]


def _retrieved_urls(sources: list[dict]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for source in sources:
        raw = (source.get("url") or source.get("source_url") or "").strip()
        if not raw:
            continue
        url = _normalize_url(raw)
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
    return found


def score_citations(report: str, sources: list[dict]) -> tuple[float, dict[str, Any]]:
    """Fraction of citations that resolve to a retrieved source URL."""
    retrieved = _retrieved_urls(sources)
    retrieved_set = set(retrieved)
    body, sources_text = _split_sources(report)
    markers = [int(number) for number in _CITE_RE.findall(body)]
    listed = _urls(sources_text) if sources_text else _urls(body)
    details: dict[str, Any] = {
        "markers": len(markers),
        "listed_urls": listed,
        "retrieved_urls": retrieved,
    }
    if markers:
        matched = 0
        resolved: list[str] = []
        for number in markers:
            if 1 <= number <= len(listed):
                url = listed[number - 1]
                resolved.append(url)
                if url in retrieved_set:
                    matched += 1
            else:
                resolved.append("")
        details["resolved_urls"] = resolved
        details["matched"] = matched
        return matched / len(markers), details

    report_urls = _urls(report)
    details["report_urls"] = report_urls
    if not report_urls:
        details["matched"] = 0
        return 0.0, details
    matched = sum(1 for url in report_urls if url in retrieved_set)
    details["matched"] = matched
    return matched / len(report_urls), details


def _fraction(text: str, groups: tuple[Phrase, ...]) -> tuple[float, list[str], list[str]]:
    hit: list[str] = []
    missed: list[str] = []
    for group in groups:
        label = _label(group)
        if _hit(text, group):
            hit.append(label)
        else:
            missed.append(label)
    if not groups:
        return 1.0, hit, missed
    return len(hit) / len(groups), hit, missed


def score_case(case: EvalCase, report: str, sources: list[dict] | None = None) -> dict[str, Any]:
    """Score one report. Each dimension is in ``[0, 1]``."""
    sources = sources or []
    factual, facts_hit, facts_missed = _fraction(report, case.facts)
    coverage, aspects_hit, aspects_missed = _fraction(report, case.aspects)
    citations, citation_details = score_citations(report, sources)
    overall = (factual + citations + coverage) / 3
    source_count = len(citation_details["retrieved_urls"])
    return {
        "id": case.id,
        "topic": case.topic,
        "factual": round(factual, 4),
        "citations": round(citations, 4),
        "coverage": round(coverage, 4),
        "overall": round(overall, 4),
        "details": {
            "facts_hit": facts_hit,
            "facts_missed": facts_missed,
            "aspects_hit": aspects_hit,
            "aspects_missed": aspects_missed,
            "citations": citation_details,
            "source_count": source_count,
            "min_sources": case.min_sources,
            "sources_met": source_count >= case.min_sources,
        },
    }


def mean_scores(scores: list[dict[str, Any]]) -> dict[str, float]:
    if not scores:
        return {key: 0.0 for key in DIMENSIONS}
    return {
        key: round(sum(float(row[key]) for row in scores) / len(scores), 4)
        for key in DIMENSIONS
    }


def score_regressions(
    before: dict[str, Any],
    after: dict[str, Any],
    tol: float = 1e-6,
) -> list[str]:
    """Dimension names whose mean fell. Empty means the change held quality."""
    dropped: list[str] = []
    for key in DIMENSIONS:
        if float(after.get(key, 0)) + tol < float(before.get(key, 0)):
            dropped.append(key)
    return dropped


def case_by_id(case_id: str) -> EvalCase:
    for case in EVAL_CASES:
        if case.id == case_id:
            return case
    raise KeyError(case_id)
