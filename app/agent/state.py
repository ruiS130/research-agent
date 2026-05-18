"""Agent state schema for the LangGraph research pipeline."""

from typing import Literal, TypedDict

AgentStatus = Literal[
    "planning",
    "searching",
    "extracting",
    "synthesizing",
    "checking",
    "done",
    "error",
]


class ResearchState(TypedDict, total=False):
    """State passed between graph nodes."""

    session_id: str
    topic: str
    sub_questions: list[str]
    search_results: list[dict]  # {query, url, title, snippet}
    extracted_findings: list[dict]  # {source_url, key_points, relevance_score}
    report: str
    gaps: list[str]
    iteration: int
    status: AgentStatus
    error: str
    refined_queries: list[str]  # gap-driven follow-up searches
    use_past_research: bool


def initial_state(
    session_id: str,
    topic: str,
    use_past_research: bool = True,
) -> ResearchState:
    return ResearchState(
        session_id=session_id,
        topic=topic,
        sub_questions=[],
        search_results=[],
        extracted_findings=[],
        report="",
        gaps=[],
        iteration=0,
        status="planning",
        refined_queries=[],
        use_past_research=use_past_research,
    )
