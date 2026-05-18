"""Conversation/session memory: query past research for new sessions."""

from app.rag.retriever import retrieve_relevant_sessions


async def get_past_context_for_topic(topic: str, max_sessions: int = 3) -> str:
    """
    Pull related past research from Chroma so Claude can reference prior work.
    """
    sessions = retrieve_relevant_sessions(topic, n_results=max_sessions)
    if not sessions:
        return ""

    parts = []
    for i, session in enumerate(sessions, start=1):
        parts.append(
            f"[Past session {i}] topic={session['topic']!r} "
            f"(relevance={session['relevance_score']})\n"
            f"{session['snippet']}"
        )
    return "\n\n".join(parts)


async def list_session_history(query: str | None = None, limit: int = 20) -> list[dict]:
    """List past sessions; optional semantic query filter."""
    if query:
        return retrieve_relevant_sessions(query, n_results=limit)
    return _list_recent_sessions(limit)


def _list_recent_sessions(limit: int) -> list[dict]:
    from app.rag.store import get_collection

    collection = get_collection()
    total = collection.count()
    if total == 0:
        return []

    # Fetch all metadatas and dedupe by session_id (main docs only)
    data = collection.get(include=["metadatas", "documents"])
    sessions: dict[str, dict] = {}

    for doc_id, meta, document in zip(
        data["ids"],
        data["metadatas"],
        data["documents"],
    ):
        if not meta:
            continue
        if meta.get("chunk_type") == "source":
            continue
        sid = meta.get("session_id", doc_id)
        sessions[sid] = {
            "session_id": sid,
            "topic": meta.get("topic", ""),
            "snippet": (document or "")[:400],
            "created_at": meta.get("created_at"),
            "relevance_score": None,
        }

    ordered = sorted(
        sessions.values(),
        key=lambda x: x.get("created_at") or "",
        reverse=True,
    )
    return ordered[:limit]
