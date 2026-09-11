"""ChromaDB client, collection setup, embed + upsert."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import chromadb
from chromadb.config import Settings

COLLECTION_NAME = "research_sessions"
_chroma_client: chromadb.PersistentClient | None = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
        os.makedirs(persist_dir, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


async def upsert_research_session(
    session_id: str,
    topic: str,
    report: str,
    sources: list[dict],
) -> None:
    """Store report + metadata; document text is topic + report for retrieval."""
    collection = get_collection()
    now = datetime.now(timezone.utc).isoformat()
    document = f"Topic: {topic}\n\n{report}"
    metadata = {
        "session_id": session_id,
        "topic": topic,
        "created_at": now,
        "source_count": len(sources),
    }

    collection.upsert(
        ids=[session_id],
        documents=[document],
        metadatas=[metadata],
    )

    # Store individual sources as separate chunks for finer retrieval
    if sources:
        source_ids = [f"{session_id}_src_{i}" for i in range(len(sources))]
        source_docs = []
        source_metas = []
        for i, src in enumerate(sources):
            url = src.get("url") or src.get("source_url", "")
            title = src.get("title", "")
            points = src.get("key_points", [])
            if isinstance(points, list):
                points_text = "\n".join(f"- {p}" for p in points)
            else:
                points_text = str(points)
            source_docs.append(f"{title}\n{url}\n{points_text}")
            source_metas.append(
                {
                    "session_id": session_id,
                    "topic": topic,
                    "source_url": url,
                    "created_at": now,
                    "chunk_type": "source",
                }
            )
        collection.upsert(
            ids=source_ids,
            documents=source_docs,
            metadatas=source_metas,
        )


def reset_chroma_client() -> None:
    """Drop the cached client (used in tests with a temp persist dir)."""
    global _chroma_client
    _chroma_client = None


def get_session_by_id(session_id: str) -> dict | None:
    """
    Load a completed research session from Chroma by id.
    Returns {session_id, topic, report, sources, created_at} or None.
    """
    collection = get_collection()
    try:
        main = collection.get(ids=[session_id], include=["documents", "metadatas"])
    except Exception:
        return None

    if not main.get("ids"):
        return None

    meta = (main.get("metadatas") or [None])[0] or {}
    document = (main.get("documents") or [""])[0] or ""
    topic = meta.get("topic", "")
    report = document
    prefix = f"Topic: {topic}\n\n"
    if topic and document.startswith(prefix):
        report = document[len(prefix) :]

    sources: list[dict] = []
    try:
        all_data = collection.get(include=["documents", "metadatas"])
        for doc_id, src_meta, src_doc in zip(
            all_data.get("ids") or [],
            all_data.get("metadatas") or [],
            all_data.get("documents") or [],
        ):
            if not src_meta or src_meta.get("session_id") != session_id:
                continue
            if src_meta.get("chunk_type") != "source":
                continue
            lines = (src_doc or "").split("\n", 2)
            title = lines[0] if lines else ""
            url = src_meta.get("source_url") or (lines[1] if len(lines) > 1 else "")
            points_text = lines[2] if len(lines) > 2 else ""
            key_points = [
                p[2:].strip() if p.startswith("- ") else p.strip()
                for p in points_text.split("\n")
                if p.strip()
            ]
            sources.append(
                {
                    "url": url,
                    "title": title,
                    "key_points": key_points,
                    "relevance_score": None,
                }
            )
    except Exception:
        sources = []

    return {
        "session_id": session_id,
        "topic": topic,
        "report": report,
        "sources": sources,
        "created_at": meta.get("created_at"),
    }
