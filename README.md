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

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/research` | Start a research job |
| GET | `/research/{id}` | Poll status and result |
| GET | `/history?q=...` | List or search past sessions |

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

### Query past research

```bash
curl "http://localhost:8000/history?q=batteries&limit=10"
```

## Project layout

```
app/
  main.py           # FastAPI app
  schemas.py        # Pydantic models
  agent/
    state.py        # TypedDict state
    graph.py        # LangGraph wiring
    nodes.py        # plan, search, extract, synthesize, gap_check, done
    tools.py        # web_search, fetch_page, store_to_rag
  rag/
    store.py        # ChromaDB persist + upsert
    retriever.py    # Semantic retrieval + scoring
    memory.py       # Past-session context for new jobs
  routers/
    research.py     # Job endpoints
    history.py      # History endpoint
```

## Notes

- Web search uses DuckDuckGo HTML (no extra API key).
- Claude model: `claude-sonnet-4-20250514` with 3 retries and exponential backoff.
- Research reports persist in Chroma under `CHROMA_PERSIST_DIR` (default `./chroma_data`).
- In-memory job status is lost on restart; completed reports remain in Chroma and appear in `/history`.
