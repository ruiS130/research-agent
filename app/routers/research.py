"""POST /research, GET /research/{id}, GET /research/{id}/stream."""

import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.graph import research_graph
from app.agent.settings import anthropic_model, cost_mode
from app.agent.state import initial_state
from app.jobs.store import create_job, get_job, save_job
from app.observability import (
    begin_job_metrics,
    end_job_metrics,
    get_job_metrics,
    log_event,
    set_current_job,
)
from app.rag.retriever import format_sources_for_response
from app.rag.store import get_session_by_id
from app.schemas import ResearchJobResponse, ResearchRequest, ResearchStatusResponse

router = APIRouter(prefix="/research", tags=["research"])

_TERMINAL = frozenset({"done", "error", "interrupted"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_to_response(job: dict) -> ResearchStatusResponse:
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
        last_node=job.get("last_node"),
        timing=job.get("timing") or {},
        cost=job.get("cost") or {},
    )


def _session_to_job(session: dict) -> dict:
    created = session.get("created_at")
    created_at = None
    if created:
        try:
            created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            created_at = None
    return {
        "id": session["session_id"],
        "topic": session["topic"],
        "status": "done",
        "report": session.get("report"),
        "sources": session.get("sources") or [],
        "gaps": [],
        "error": None,
        "created_at": created_at,
        "completed_at": created_at,
        "last_node": "done",
        "event_seq": 0,
        "timing": {},
        "cost": {},
    }


def _resolve_job(job_id: str) -> dict | None:
    """SQLite is source of truth; Chroma fills in older completed sessions."""
    persisted = get_job(job_id)
    if persisted:
        return persisted
    session = get_session_by_id(job_id)
    if not session:
        return None
    recovered = _session_to_job(session)
    save_job(recovered)
    return recovered


def _persist(job: dict) -> None:
    save_job(job)


@router.post("", response_model=ResearchJobResponse)
async def start_research(
    body: ResearchRequest,
    background_tasks: BackgroundTasks,
) -> ResearchJobResponse:
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "topic": body.topic,
        "status": "pending",
        "report": None,
        "sources": [],
        "gaps": [],
        "error": None,
        "created_at": _now(),
        "completed_at": None,
        "last_node": None,
        "event_seq": 0,
        "timing": {},
        "cost": {},
    }
    create_job(job)
    log_event(
        "job_created",
        job_id=job_id,
        topic=body.topic,
        cost_mode=cost_mode(),
        model=anthropic_model(),
    )

    background_tasks.add_task(_run_research, job_id, body.topic, body.use_past_research)

    return ResearchJobResponse(
        id=job_id,
        topic=body.topic,
        status="pending",
        message="Research job started",
    )


@router.get("/{job_id}", response_model=ResearchStatusResponse)
async def get_research_status(job_id: str) -> ResearchStatusResponse:
    job = _resolve_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")
    return _job_to_response(job)


@router.get("/{job_id}/stream")
async def stream_research(job_id: str) -> StreamingResponse:
    """Server-Sent Events: status / node updates until done or error."""

    async def event_generator():
        last_seq = -1
        for _ in range(50):
            job = _resolve_job(job_id)
            if job:
                break
            await asyncio.sleep(0.1)
        else:
            payload = json.dumps({"error": "Research job not found"})
            yield f"event: error\ndata: {payload}\n\n"
            return

        while True:
            job = _resolve_job(job_id)
            if not job:
                payload = json.dumps({"error": "Research job not found"})
                yield f"event: error\ndata: {payload}\n\n"
                return

            seq = job.get("event_seq", 0)
            if seq != last_seq:
                last_seq = seq
                data = {
                    "id": job["id"],
                    "topic": job["topic"],
                    "status": job["status"],
                    "last_node": job.get("last_node"),
                    "gaps": job.get("gaps") or [],
                    "error": job.get("error"),
                    "report": job.get("report"),
                    "sources": job.get("sources") or [],
                    "timing": job.get("timing") or {},
                    "cost": job.get("cost") or {},
                }
                event_name = "done" if job["status"] in _TERMINAL else "progress"
                yield f"event: {event_name}\ndata: {json.dumps(data)}\n\n"
                if job["status"] in _TERMINAL:
                    return

            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _run_research(job_id: str, topic: str, use_past_research: bool) -> None:
    job = get_job(job_id)
    if not job:
        log_event("job_missing", job_id=job_id)
        return

    metrics = begin_job_metrics(
        job_id, model=anthropic_model(), cost_mode=cost_mode()
    )
    set_current_job(job_id)

    job["status"] = "planning"
    job["last_node"] = None
    job["event_seq"] = int(job.get("event_seq") or 0) + 1
    _persist(job)
    log_event("job_started", job_id=job_id, topic=topic, cost_mode=cost_mode())

    state = initial_state(job_id, topic, use_past_research=use_past_research)
    final = dict(state)

    try:
        # Wall time between astream yields ≈ per-node duration.
        prev_t = time.perf_counter()
        async for event in research_graph.astream(state, stream_mode="updates"):
            now_t = time.perf_counter()
            elapsed_ms = (now_t - prev_t) * 1000.0
            prev_t = now_t
            for node_name, partial in event.items():
                final.update(partial)
                metrics.record_node(node_name, elapsed_ms)

                job = get_job(job_id) or job
                job["last_node"] = node_name
                job["status"] = partial.get("status", job["status"])
                if partial.get("report"):
                    job["report"] = partial["report"]
                if partial.get("gaps") is not None:
                    job["gaps"] = partial["gaps"]
                if partial.get("extracted_findings"):
                    job["sources"] = format_sources_for_response(
                        partial["extracted_findings"]
                    )
                job["event_seq"] = int(job.get("event_seq") or 0) + 1
                job["timing"] = metrics.to_timing_dict()
                job["cost"] = metrics.to_cost_dict()
                _persist(job)
                log_event(
                    "node_finished",
                    job_id=job_id,
                    node=node_name,
                    status=job["status"],
                    elapsed_ms=round(elapsed_ms, 2),
                    api_calls=metrics.api_calls,
                    estimated_usd=metrics.to_cost_dict()["estimated_usd"],
                )

        job = get_job(job_id) or job
        job["status"] = final.get("status", "done")
        job["report"] = final.get("report")
        job["gaps"] = final.get("gaps", [])
        job["sources"] = format_sources_for_response(
            final.get("extracted_findings") or []
        )
        job["last_node"] = "done"
        job["completed_at"] = _now()
        job["event_seq"] = int(job.get("event_seq") or 0) + 1
        job["timing"] = metrics.to_timing_dict()
        job["cost"] = metrics.to_cost_dict()
        _persist(job)
        log_event(
            "job_completed",
            job_id=job_id,
            status=job["status"],
            **metrics.to_cost_dict(),
            timing=metrics.to_timing_dict(),
        )
    except Exception as exc:
        job = get_job(job_id) or job
        job["status"] = "error"
        job["error"] = str(exc)
        job["last_node"] = "error"
        job["completed_at"] = _now()
        job["event_seq"] = int(job.get("event_seq") or 0) + 1
        job["timing"] = metrics.to_timing_dict()
        job["cost"] = metrics.to_cost_dict()
        _persist(job)
        log_event(
            "job_failed",
            job_id=job_id,
            error=str(exc),
            **metrics.to_cost_dict(),
        )
        traceback.print_exc()
    finally:
        end_job_metrics(job_id)
        set_current_job(None)
