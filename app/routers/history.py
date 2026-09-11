"""GET /history — past research sessions from RAG."""

from fastapi import APIRouter, HTTPException, Query

from app.rag.memory import list_session_history
from app.rag.store import get_session_by_id
from app.schemas import HistoryDetailResponse, HistoryItem, HistoryResponse

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=HistoryResponse)
async def get_history(
    q: str | None = Query(None, description="Semantic search over past research"),
    limit: int = Query(20, ge=1, le=100),
) -> HistoryResponse:
    sessions = await list_session_history(query=q, limit=limit)
    items = [
        HistoryItem(
            session_id=s["session_id"],
            topic=s["topic"],
            snippet=s["snippet"],
            created_at=s.get("created_at"),
            relevance_score=s.get("relevance_score"),
        )
        for s in sessions
    ]
    return HistoryResponse(query=q, sessions=items)


@router.get("/{session_id}", response_model=HistoryDetailResponse)
async def get_history_session(session_id: str) -> HistoryDetailResponse:
    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Research session not found")
    return HistoryDetailResponse(
        session_id=session["session_id"],
        topic=session["topic"],
        report=session.get("report") or "",
        sources=session.get("sources") or [],
        created_at=session.get("created_at"),
    )
