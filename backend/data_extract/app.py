"""
FastAPI service for FinSight (backend/data_extract/app.py).

Surfaces:
  - GET  /extract/{ticker}          -> extraction pipeline (ticker -> clean structured data)
  - GET  /ingest-status/{ticker}    -> poll RavenDB ingest progress for a filing
  - GET  /market/{ticker}           -> market snapshot + price history (yfinance)
  - GET  /search?q=<text>           -> company name/ticker search over the SEC registry
  - POST /api/chat                  -> RAG chat (RavenDB retrieval + Gemini generation)

Run from the repo root:
    uvicorn backend.data_extract.app:app --reload --port 8000
"""

import logging
import os
import threading
from pathlib import Path
from typing import Literal, Optional

# Load the env file (.env.python at backend/) BEFORE importing modules that read
# os.getenv at import time — embeddings.py captures the Gemini/Vertex and RavenDB
# settings on import, so this must run first.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.python")
except ImportError:
    pass

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .extractor import run
from .rag import router as chat_router
from .market import router as market_router
from .search import router as search_router
from .compare_metrics import router as compare_metrics_router

logger = logging.getLogger(__name__)

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

app = FastAPI(title="FinSight Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(market_router)
app.include_router(search_router)
app.include_router(compare_metrics_router)


# --- Ingest status registry --------------------------------------------------
# Keyed by "{TICKER}-{form}" e.g. "AAPL-10-K".
# Status lifecycle: indexing -> indexed | failed
# In-memory: sufficient for single-worker uvicorn; cleared on server restart.

_ingest_status: dict[str, dict] = {}
_status_lock = threading.Lock()


def _ingest_key(ticker: str, form: str) -> str:
    return f"{ticker.upper()}-{form}"


def _build_ingest_text(sections: dict) -> str:
    """Concatenate all extracted sections with headers for embedding."""
    parts = []
    for key, text in sections.items():
        if text and key != "header":
            label = key.replace("_", " ").title()
            parts.append(f"## {label}\n\n{text}")
    return "\n\n".join(parts)


def _run_ingest(ticker: str, form: str, sections: dict, source: str, key: str) -> None:
    """Background worker: chunk + embed + store in RavenDB. Updates _ingest_status."""
    try:
        from .embeddings import ingest
        text = _build_ingest_text(sections)
        if not text.strip():
            with _status_lock:
                _ingest_status[key] = {
                    "status": "failed", "chunks": 0,
                    "error": "No section text extracted to embed",
                }
            return
        n = ingest(ticker, form, text, source)
        with _status_lock:
            _ingest_status[key] = {"status": "indexed", "chunks": n, "error": None}
        logger.info("Ingest complete: %s %s -> %d chunks stored", ticker, form, n)
    except Exception as e:
        logger.exception("Ingest failed for %s %s: %s", ticker, form, e)
        with _status_lock:
            _ingest_status[key] = {"status": "failed", "chunks": 0, "error": str(e)}


# --- Health ------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- Extract + ingest --------------------------------------------------------

@app.get("/extract/{ticker}")
def extract(
    ticker: str,
    background_tasks: BackgroundTasks,
    form: Literal["10-K", "10-Q"] = "10-K",
) -> dict:
    """
    Run the full pipeline for a ticker and return structured JSON immediately.

    After returning, kicks off a background task that chunks the filing
    narrative into embeddings and stores them in RavenDB. Poll
    GET /ingest-status/{ticker}?form=<form> to track progress.
    """
    ticker = ticker.upper()
    key = _ingest_key(ticker, form)
    try:
        result = run(ticker, form)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Extraction failed for %s %s", ticker, form)
        raise HTTPException(status_code=502, detail=f"Extraction failed: {e}")

    sections = result.get("sections", {})
    source = result.get("source_url", f"{ticker}/{form}")

    with _status_lock:
        _ingest_status[key] = {"status": "indexing", "chunks": 0, "error": None}

    # BackgroundTasks runs sync functions in Starlette's thread pool via
    # run_in_threadpool, so the blocking Gemini + RavenDB calls don't stall
    # the event loop.
    background_tasks.add_task(_run_ingest, ticker, form, sections, source, key)

    return result


# --- Ingest status -----------------------------------------------------------

class IngestStatusResponse(BaseModel):
    status: Literal["indexing", "indexed", "failed", "unknown"]
    chunks: int
    error: Optional[str] = None


@app.get("/ingest-status/{ticker}", response_model=IngestStatusResponse)
def ingest_status(
    ticker: str,
    form: Literal["10-K", "10-Q"] = "10-K",
) -> IngestStatusResponse:
    """
    Returns the current ingest status for a (ticker, form) pair.
    - "indexing": background task is still running
    - "indexed":  chunks stored successfully; `chunks` = count stored
    - "failed":   embedding or RavenDB write failed; `error` has details
    - "unknown":  no ingest has been triggered (or server was restarted)
    """
    key = _ingest_key(ticker, form)
    with _status_lock:
        info = _ingest_status.get(key)
    if info is None:
        return IngestStatusResponse(status="unknown", chunks=0)
    return IngestStatusResponse(
        status=info["status"],
        chunks=info["chunks"],
        error=info.get("error"),
    )
