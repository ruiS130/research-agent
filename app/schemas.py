"""Pydantic request/response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentStatus = Literal[
    "planning",
    "searching",
    "extracting",
    "synthesizing",
    "checking",
    "done",
    "error",
    "pending",
    "running",
]


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=2000)
    use_past_research: bool = Field(
        default=True,
        description="Query ChromaDB for related past sessions before planning",
    )


class ResearchJobResponse(BaseModel):
    id: str
    topic: str
    status: AgentStatus
    message: str = "Research job accepted"


class ResearchStatusResponse(BaseModel):
    id: str
    topic: str
    status: AgentStatus
    report: str | None = None
    sources: list[dict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class HistoryItem(BaseModel):
    session_id: str
    topic: str
    snippet: str
    created_at: str | None = None
    relevance_score: float | None = None


class HistoryResponse(BaseModel):
    query: str | None = None
    sessions: list[HistoryItem]
