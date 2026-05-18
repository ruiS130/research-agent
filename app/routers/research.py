"""POST /research and GET /research/{id}."""

import traceback
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.graph import research_graph
from app.agent.state import initial_state
from app.rag.retriever import format_sources_for_response
from app.schemas import ResearchJobResponse, ResearchRequest, ResearchStatusResponse

router = APIRouter(prefix="/research", tags=["research"])

# In-memory job registry (reports also persist in Chroma)
_jobs: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", response_model=ResearchJobResponse)
async def start_research(
    body: ResearchRequest,
    background_tasks: BackgroundTasks,
) -> ResearchJobResponse:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "id": job_id,
        "topic": body.topic,
        "status": "pending",
        "report": None,
        "sources": [],
        "gaps": [],
        "error": None,
        "created_at": _now(),
        "completed_at": None,
    }

    background_tasks.add_task(_run_research, job_id, body.topic, body.use_past_research)

    return ResearchJobResponse(
        id=job_id,
        topic=body.topic,
        status="pending",
        message="Research job started",
    )


@router.get("/{job_id}", response_model=ResearchStatusResponse)
async def get_research_status(job_id: str) -> ResearchStatusResponse:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")

    return ResearchStatusResponse(
        id=job["id"],
        topic=job["topic"],
        status=job["status"],
        report=job.get("report"),
        sources=job.get("sources") or [],
        gaps=job.get("gaps") or [],
        error=job.get("error"),
        created_at=job.get("created_at"),
        completed_at=job.get("completed_at"),
    )


async def _run_research(job_id: str, topic: str, use_past_research: bool) -> None:
    job = _jobs[job_id]
    job["status"] = "planning"

    state = initial_state(job_id, topic, use_past_research=use_past_research)
    final = dict(state)

    try:
        async for event in research_graph.astream(state, stream_mode="updates"):
            for _node_name, partial in event.items():
                final.update(partial)
                job["status"] = partial.get("status", job["status"])
                if partial.get("report"):
                    job["report"] = partial["report"]
                if partial.get("gaps") is not None:
                    job["gaps"] = partial["gaps"]
                if partial.get("extracted_findings"):
                    job["sources"] = format_sources_for_response(
                        partial["extracted_findings"]
                    )

        job["status"] = final.get("status", "done")
        job["report"] = final.get("report")
        job["gaps"] = final.get("gaps", [])
        job["sources"] = format_sources_for_response(
            final.get("extracted_findings") or []
        )
        job["completed_at"] = _now()
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["completed_at"] = _now()
        traceback.print_exc()
