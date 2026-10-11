"""FastAPI entry point for the multi-step research agent."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import history, research

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required (see .env.example)")
    # Partial durable jobs: ensure SQLite schema exists (full cutover still TODO)
    from app.jobs.store import init_db

    init_db()
    yield


app = FastAPI(
    title="Research Agent",
    description="Multi-step AI research agent with LangGraph + Claude + ChromaDB",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(research.router)
app.include_router(history.router)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health():
    chroma_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
    return {
        "status": "ok",
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "chroma_persist_dir": chroma_dir,
        "search_provider": (os.getenv("SEARCH_PROVIDER") or "ddg").lower(),
    }


@app.get("/")
async def demo_ui():
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        return {"message": "Demo UI not found. See /docs for the API."}
    return FileResponse(index)


@app.get("/do-next")
async def do_next_page():
    page = STATIC_DIR / "do-next.html"
    if not page.is_file():
        return {"message": "Do-next page not found."}
    return FileResponse(page)
