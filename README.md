# Research Agent

Multi-step AI research agent: **FastAPI** + **LangGraph** + **Claude** + **ChromaDB**.

## Summary

Local research agent: topic in → web search → markdown report with sources → live SSE progress on `/` → finished work stored in **Chroma** (RAG/history). Orchestrated as a LangGraph pipeline (plan → search → extract → synthesize → gap_check → done). Default **`COST_MODE=min`** ≈ one Haiku call per job; set **`COST_MODE=full`** for the full agentic loop. **Job status is durable in SQLite** (upsert every node; in-flight jobs marked `interrupted` on restart). Structured logs include `job_id`, per-node timing, and estimated USD cost. Dedicated **`/report/{id}`** is still a stub (report shows inline on home).

**Next steps:** (1) auth + rate limits, (2) Docker / deploy, (3) evals for non-deterministic output, (4) finish shareable report page + UI polish. Full checklist: [TODO / roadmap](#todo--roadmap).

## Architecture

```
plan → search → extract → synthesize → gap_check ─┬─→ search (max 2 loops in full mode)
                                                   └─→ done → ChromaDB
```

Job status is stored in SQLite (`JOBS_DB_PATH`); Chroma holds completed reports for RAG/history.

## Setup

```bash
cd research-agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY
```

Optional (dev tests):

```bash
pip install -r requirements-dev.txt
pytest
```

## Run

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

| URL | What |
|-----|------|
| http://localhost:8000/ | Demo UI (topic, live SSE steps, report, history) |
| http://localhost:8000/do-next | Same roadmap as below (needs server running) |
| http://localhost:8000/docs | OpenAPI / Swagger |

If the browser shows `ERR_CONNECTION_REFUSED`, nothing is listening on that port — start uvicorn first.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/` | Demo UI |
| GET | `/do-next` | Roadmap page (mirror of README TODO) |
| GET | `/report/{id}` | Report page (**stub only** — not finished) |
| POST | `/research` | Start a research job |
| GET | `/research/{id}` | Poll status (SQLite → Chroma fallback) |
| GET | `/research/{id}/stream` | SSE progress events |
| GET | `/history?q=...` | List or search past sessions |
| GET | `/history/{session_id}` | Full stored report for a session |

### Start research

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "Latest advances in solid-state batteries", "use_past_research": false}'
```

### Poll result

```bash
curl http://localhost:8000/research/<job-id>
```

### Stream progress (SSE)

```bash
curl -N http://localhost:8000/research/<job-id>/stream
```

### Query past research

```bash
curl "http://localhost:8000/history?q=batteries&limit=10"
curl http://localhost:8000/history/<session-id>
```

## Project layout

```
app/
  main.py           # FastAPI app, / and /do-next, lifespan (Chroma + SQLite init)
  schemas.py        # Pydantic models
  static/
    index.html      # Demo UI (report still inline here)
    do-next.html    # In-browser roadmap (optional; README is source of truth when undeployed)
    report.html     # Dedicated report page stub (not finished)
  jobs/
    store.py        # Durable SQLite jobs (upsert + interrupt-on-boot)
  observability.py  # JSON logs, token/cost tracking
  agent/
    state.py        # TypedDict state
    graph.py        # LangGraph wiring
    nodes.py        # plan, search, extract, synthesize, gap_check, done
    tools.py        # web_search, fetch_page, store_to_rag
  rag/
    store.py        # ChromaDB persist + upsert + session lookup
    retriever.py    # Semantic retrieval + scoring
    memory.py       # Past-session context for new jobs
  routers/
    research.py     # Job endpoints + SSE
    history.py      # History endpoints
tests/              # pytest suite
```

## Cost mode (default: minimum API spend)

By default the agent uses **`COST_MODE=min`**: about **one** Anthropic call per research job.

| Setting | `min` (default) | `full` |
|---------|-----------------|--------|
| Model | Haiku (`ANTHROPIC_MODEL`) | Same env, or set Sonnet yourself |
| Plan | No LLM — search the topic as-is | Claude plans 1–N sub-questions |
| Extract | Snippets only (no page LLM) | Fetch pages + Claude per source |
| Synthesize | 1 short Haiku brief (~1k tokens max) | Longer report |
| Gap loop | Off (0 extra searches) | Up to 2 re-search loops |

```bash
# .env — thrifty (default)
COST_MODE=min
ANTHROPIC_MODEL=claude-3-5-haiku-20241022

# richer / more expensive
COST_MODE=full
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

`GET /health` reports `cost_mode` and `anthropic_model`.

## Notes

- Web search defaults to DuckDuckGo HTML (no extra API key). Set `SEARCH_PROVIDER=tavily` or `serper` (with the matching API key) for a more reliable provider; if DuckDuckGo returns nothing or errors, Tavily/Serper are tried when keys are set.
- Claude calls retry up to 3 times with exponential backoff.
- Research reports persist in Chroma under `CHROMA_PERSIST_DIR` (default `./chroma_data`).
- **Job id equals Chroma `session_id`.**
- Job lookup: **SQLite** first, then Chroma for older completed sessions.
- On startup, non-terminal SQLite jobs are marked **`interrupted`** (pipeline does not auto-resume).
- Observability: stdout JSON logs (`job_created`, `node_finished`, `job_completed`) with `job_id`, per-node `timing` (ms), and `cost` (`input_tokens`, `output_tokens`, `api_calls`, `estimated_usd`). Same fields on `GET /research/{id}`.
- SQLite path: `JOBS_DB_PATH` (default `./data/jobs.db`, gitignored).

## Recent changes (local, not requiring deploy)

- **Demo UI + SSE** — live step progress at `/` via `GET /research/{id}/stream`.
- **Chroma recovery** — completed jobs reload after restart; `GET /history/{session_id}` for full reports.
- **Search fallback** — optional Tavily/Serper when DDG fails (see `.env.example`).
- **Tests** — `pytest` with mocked Claude/search (`requirements-dev.txt`).
- **`/do-next` page** — in-app roadmap; this README section is the offline copy.
- **Durable SQLite jobs** — upsert on every node; no in-memory `_jobs`; interrupt non-terminal jobs on boot.
- **Observability** — structured logs + `timing` / `cost` on job status responses.
- **Report page stub** — `GET /report/{id}` serves a placeholder; full page not built yet (plan below).

## TODO / roadmap

Readable here without running the server. The `/do-next` page shows the same list when uvicorn is up.

### Shipped

- [x] SSE progress: `GET /research/{id}/stream`
- [x] Minimal web UI (topic, live steps, report, history)
- [x] Recover completed jobs from Chroma after restart
- [x] `GET /history/{session_id}` full report
- [x] pytest suite with mocked Claude/search
- [x] Optional search provider (Tavily/Serper) fallback
- [x] `/do-next` roadmap page (also documented in this README)
- [x] Min-cost mode (`COST_MODE=min`, ~1 Haiku call/job)

### Done — durable in-flight jobs (SQLite)

- [x] Schema + `init_db` / `create_job` / `get_job` / `save_job`
- [x] Upsert status / `last_node` / report / timing / cost on every graph node update
- [x] Mark interrupted jobs on process start
- [x] Drop in-memory `_jobs` dict (SQLite is source of truth)
- [ ] (Later) Resume a mid-pipeline LangGraph run after crash

### Done — observability

- [x] Structured JSON logs with `job_id`
- [x] Per-node timing (ms) on job status + logs
- [x] Per-job token usage + `estimated_usd` (model rate table / env overrides)

### Planned — separate report page (not finished)

**Why:** Demos need a shareable URL (“here’s the report”) instead of only the inline panel on `/`.

**Target URL:** `/report/{job_id}` (same id as Chroma `session_id`).

| Step | Status | Notes |
|------|--------|--------|
| Route + placeholder HTML | Done (stub) | `GET /report/{id}` → `static/report.html` |
| Fetch job/report JSON | Not done | Use existing `GET /research/{id}` and/or `GET /history/{id}` |
| Render markdown + sources | Not done | marked.js (or similar), sources list with links |
| Wire from home / history | Not done | “Open report” → `/report/{id}` after `done` |
| In-progress / missing job | Not done | Show “still running” or 404 / link back to `/` |
| Share extras | Not done | Copy link, download `.md` (optional) |

Until this ships, keep showing the report on the home UI.

### Next (priority order)

- [ ] Auth + rate limit (before any public URL)
- [ ] Deploy story (Dockerfile + short run-anywhere docs)
- [ ] Evals for non-deterministic output (source-count, URL checks, coverage)
- [ ] Finish report page + UI polish (shareable demo last)
