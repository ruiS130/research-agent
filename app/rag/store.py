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
