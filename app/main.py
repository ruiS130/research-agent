"""FastAPI entry point for the multi-step research agent."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.routers import history, research

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required (see .env.example)")
    yield


app = FastAPI(
    title="Research Agent",
    description="Multi-step AI research agent with LangGraph + Claude + ChromaDB",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(research.router)
app.include_router(history.router)


@app.get("/health")
async def health():
    chroma_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
    return {
        "status": "ok",
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "chroma_persist_dir": chroma_dir,
    }
