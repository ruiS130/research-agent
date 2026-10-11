# Research Agent

Multi-step AI research agent: **FastAPI** + **LangGraph** + **Claude** + **ChromaDB**.

## Architecture

```
plan → search → extract → synthesize → gap_check ─┬─→ search (max 2 loops)
                                                   └─→ done → ChromaDB
```

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open the demo UI at http://localhost:8000/

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/` | Demo UI |
| GET | `/do-next` | Roadmap / next work |
| POST | `/research` | Start a research job |
| GET | `/research/{id}` | Poll status and result (falls back to Chroma after restart) |
| GET | `/research/{id}/stream` | SSE progress events |
| GET | `/history?q=...` | List or search past sessions |
| GET | `/history/{session_id}` | Full stored report for a session |

### Start research

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "Latest advances in solid-state batteries", "use_past_research": true}'
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
  main.py           # FastAPI app + static UI
  schemas.py        # Pydantic models
  static/
    index.html      # Demo UI
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

## Notes

- Web search defaults to DuckDuckGo HTML (no extra API key). Set `SEARCH_PROVIDER=tavily` or `serper` (with the matching API key) for a more reliable provider; if DuckDuckGo returns nothing or errors, Tavily/Serper are tried when keys are set.
- Claude model: `claude-sonnet-4-20250514` with 3 retries and exponential backoff.
- Research reports persist in Chroma under `CHROMA_PERSIST_DIR` (default `./chroma_data`).
- **Job id equals Chroma `session_id`.** In-memory job status is lost on restart; completed reports remain in Chroma and are served again via `GET /research/{id}` and `/history`.

## TODO

- [x] SSE progress: `GET /research/{id}/stream`
- [x] Minimal web UI (topic, live steps, report, history)
- [x] Recover completed jobs from Chroma after restart
- [x] `GET /history/{session_id}` full report
- [x] pytest suite with mocked Claude/search
- [x] Optional search provider (Tavily/Serper) fallback
- [~] Durable SQLite jobs (create/get only — open `/do-next` when the server is running)
