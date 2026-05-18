"""GET /history — past research sessions from RAG."""

from fastapi import APIRouter, Query

from app.rag.memory import list_session_history
from app.schemas import HistoryItem, HistoryResponse

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
