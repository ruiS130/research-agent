"""LangGraph state graph: plan -> search -> extract -> synthesize -> gap_check -> done."""

from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    done_node,
    extract_node,
    gap_check_node,
    plan_node,
    search_node,
    synthesize_node,
)
from app.agent.state import ResearchState

MAX_GAP_LOOPS = 2


def route_after_gap_check(state: ResearchState) -> str:
    """Route back to search if gaps remain and we have loop budget; else finish."""
    gaps = state.get("gaps") or []
    iteration = state.get("iteration", 0)

    if gaps and iteration < MAX_GAP_LOOPS:
        return "search"
    return "done"


def build_research_graph():
    graph = StateGraph(ResearchState)

    graph.add_node("plan", plan_node)
    graph.add_node("search", search_node)
    graph.add_node("extract", extract_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("gap_check", gap_check_node)
    graph.add_node("done", done_node)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "extract")
    graph.add_edge("extract", "synthesize")
    graph.add_edge("synthesize", "gap_check")
    graph.add_conditional_edges(
        "gap_check",
        route_after_gap_check,
        {"search": "search", "done": "done"},
    )
    graph.add_edge("done", END)

    return graph.compile()


research_graph = build_research_graph()
