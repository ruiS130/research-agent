# Research Agent

Multi-step AI research agent: **FastAPI** + **LangGraph** + **Claude** + **ChromaDB**.

## Architecture

```
plan → search → extract → synthesize → gap_check ─┬─→ search (max 2 loops)
                                                   └─→ done → ChromaDB
```

While a job runs, status also lives in memory (and a **partial** SQLite row on create). See [TODO / roadmap](#todo--roadmap).

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
| POST | `/research` | Start a research job |
| GET | `/research/{id}` | Poll status (memory → Chroma → SQLite) |
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
    index.html      # Demo UI
    do-next.html    # In-browser roadmap (optional; README is source of truth when undeployed)
  jobs/
    store.py        # SQLite job store (partial: create/get only)
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
- Job lookup order after restart: in-memory → **Chroma** (completed) → **SQLite** (create snapshot; may still say `pending` until live upserts land).
- SQLite path: `JOBS_DB_PATH` (default `./data/jobs.db`, gitignored).

## Recent changes (local, not requiring deploy)

- **Demo UI + SSE** — live step progress at `/` via `GET /research/{id}/stream`.
- **Chroma recovery** — completed jobs reload after restart; `GET /history/{session_id}` for full reports.
- **Search fallback** — optional Tavily/Serper when DDG fails (see `.env.example`).
- **Tests** — `pytest` with mocked Claude/search (`requirements-dev.txt`).
- **`/do-next` page** — in-app roadmap; this README section is the offline copy.
- **Partial durable jobs** — `app/jobs/store.py`: schema, `create_job` / `get_job`; new jobs written on `POST /research`. Mid-run status upserts and removing `_jobs` are still open (below).

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

### In progress — durable in-flight jobs (SQLite)

- [x] Schema + `init_db` / `create_job` / `get_job` (`app/jobs/store.py`)
- [x] Persist job on `POST /research`; resolve can read SQLite
- [ ] Upsert status / `last_node` / report on every graph node update
- [ ] Mark interrupted jobs on process start
- [ ] Drop in-memory `_jobs` dict (SQLite as source of truth while running)
- [ ] (Later) Resume a mid-pipeline LangGraph run after crash

### Next

- [ ] Deploy story (Dockerfile + short run-anywhere docs)
- [ ] Auth + rate limit (API key or basic login before public expose)
- [ ] Observability (structured logs with `job_id`, per-node timing, cost)
- [ ] UI polish (live sources/gaps, cancel, download markdown)
