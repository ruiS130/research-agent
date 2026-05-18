"""Query retrieval with relevance scoring from ChromaDB."""

from app.rag.store import get_collection


def retrieve_relevant_sessions(
    query: str,
    n_results: int = 5,
    min_relevance: float = 0.0,
) -> list[dict]:
    """
    Query past research. Chroma returns distances (lower = more similar for cosine).
    We convert distance to a simple relevance score in [0, 1].
    """
    collection = get_collection()
    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    sessions: list[dict] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    seen_session_ids: set[str] = set()

    for doc_id, document, meta, distance in zip(
        ids, documents, metadatas, distances
    ):
        if not meta:
            continue
        session_id = meta.get("session_id", doc_id)
        # Deduplicate: prefer main session doc over source chunks
        if session_id in seen_session_ids and meta.get("chunk_type") == "source":
            continue
        if meta.get("chunk_type") == "source":
            session_id = meta.get("session_id", session_id)

        relevance = _distance_to_relevance(distance)
        if relevance < min_relevance:
            continue

        if session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)

        snippet = (document or "")[:400]
        sessions.append(
            {
                "session_id": session_id,
                "topic": meta.get("topic", ""),
                "snippet": snippet,
                "created_at": meta.get("created_at"),
                "relevance_score": round(relevance, 4),
            }
        )

    sessions.sort(key=lambda x: x["relevance_score"], reverse=True)
    return sessions[:n_results]


def _distance_to_relevance(distance: float | None) -> float:
    """Map cosine distance to a 0-1 relevance score."""
    if distance is None:
        return 0.0
    # Chroma cosine distance is in [0, 2]; 0 = identical
    return max(0.0, min(1.0, 1.0 - (distance / 2.0)))


def format_sources_for_response(findings: list[dict]) -> list[dict]:
    return [
        {
            "url": f.get("source_url", ""),
            "title": f.get("title", ""),
            "key_points": f.get("key_points", []),
            "relevance_score": f.get("relevance_score"),
        }
        for f in findings
    ]
