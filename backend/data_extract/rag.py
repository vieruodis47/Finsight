"""
backend/data_extract/rag.py

RAG answer generation for FinSight.

Flow: retrieve filing context from RavenDB vector search (embeddings.search)
-> generate a grounded answer with Gemini. Generation lives here in the
Python/FastAPI service using a Gemini API key, alongside retrieval, so the
frontend sends only a question.

Mount in app.py:
    from .rag import router as chat_router
    app.include_router(chat_router)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Iterator, Literal, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from google.genai import types

from .embeddings import search, get_genai_client, FilingChunk

logger = logging.getLogger(__name__)

GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-3.1-flash-lite")

SYSTEM_PROMPT = (
    "You are FinSight, an expert financial research assistant.\n"
    "Answer ONLY using the provided context from SEC filings.\n"
    'If the answer cannot be determined from the provided context, respond exactly with: '
    '"I could not find sufficient information in the provided financial documents to answer this question."\n'
    "\n"
    "You MAY use general financial knowledge to explain standard financial concepts (such as revenue, "
    "net income, operating cash flow, gross margin, EPS, free cash flow, assets, liabilities, or cash flow), "
    "provided the explanation does NOT introduce any company-specific facts or assumptions.\n"
    "\n"
    "If the provided context contains conflicting or inconsistent information:\n"
    "- Do NOT choose one value over another.\n"
    "- Clearly state that the context contains conflicting information.\n"
    "- Present the conflicting values or statements.\n"
    "- Explain that the correct answer cannot be determined from the provided context alone.\n"
    "\n"
    "Citation rule: every sentence that states a specific fact or number MUST include an inline "
    "citation tag matching the block header where you found it. Use the exact format: [TICKER FORM #N]. "
    "Example: 'Apple's net sales were $391.0B in fiscal 2024 [AAPL 10-K #4].'\n"
    "If you draw on multiple chunks, cite each one inline. Place the tag immediately after the "
    "relevant sentence, before the period or at end of clause."
)

NO_CONTEXT_MESSAGE = (
    "I couldn't find anything relevant in the indexed filings to answer that. "
    "Try rephrasing, or check that the relevant filing has been ingested."
)


# --- Core ------------------------------------------------------------------

def _format_context(chunks: list[FilingChunk]) -> str:
    """Tag each chunk with its source so the model can ground and cite.

    Ordering: rank-0 (most relevant) first, rank-1 (second-most relevant) last,
    ranks 2..k-1 in the middle. The two best chunks bookend the context so both
    sit in the high-attention zones at either end of the contents string,
    reducing the "lost in the middle" attention drop for the second-best passage.
    """
    if len(chunks) > 2:
        ordered = [chunks[0]] + chunks[2:] + [chunks[1]]
    else:
        ordered = chunks
    blocks = []
    for c in ordered:
        tag = f"[{c.ticker} {c.form} #{c.chunk_index} | {c.source}]"
        blocks.append(f"{tag}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


def generate_answer(question: str, chunks: list[FilingChunk]) -> str:
    """Generate a grounded answer from retrieved context via Gemini."""
    context = _format_context(chunks)
    client = get_genai_client()
    resp = client.models.generate_content(
        model=GEN_MODEL,
        contents=f"Context:\n{context}\n\nQuestion:\n{question}",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
        ),
    )
    return (resp.text or "").strip()


def generate_stream(system: str, prompt: str, temperature: float) -> Iterator[str]:
    """
    Stream a Gemini generation token-by-token. Yields text deltas as they arrive
    (google-genai generate_content_stream). Used by the /chat/stream endpoint so
    the browser renders words as they're produced rather than waiting for the
    whole answer. Raising propagates to the endpoint, which emits an error event.
    """
    client = get_genai_client()
    for chunk in client.models.generate_content_stream(
        model=GEN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
        ),
    ):
        delta = getattr(chunk, "text", None)
        if delta:
            yield delta


def answer_question(
    question: str,
    k: int = 5,
    ticker: Optional[str] = None,
    tickers: Optional[list[str]] = None,
    form: Optional[str] = None,
) -> tuple[str, list[FilingChunk]]:
    """
    Retrieve then generate. Returns (answer, source_chunks).

    `tickers` scopes the vector search to a set of companies (see search()).
    route_question passes the companies the question names so an unscoped
    question can't retrieve a different company's filing text.
    """
    chunks = search(question, k=k, ticker=ticker, tickers=tickers, form=form)
    if not chunks:
        logger.info("No context retrieved for question: %s", question[:80])
        return "", []
    answer = generate_answer(question, chunks)
    return answer, chunks


# --- API -------------------------------------------------------------------

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)
    ticker: Optional[str] = None
    # Explicit vector-search scope. The compare-view FinChat strip always sends
    # [anchor, peer] so a pair question that names no company ("which has better
    # margins?") is still confined to the two companies on screen. Additive and
    # optional: a request that omits it (e.g. ChatInterface) behaves exactly as
    # before. Takes precedence over `ticker` and over name-based resolution
    # inside route_question.
    tickers: Optional[list[str]] = None
    form: Optional[Literal["10-K"]] = None


class Source(BaseModel):
    ticker: str
    form: str
    chunk_index: int
    source: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    retrieval_path: str = "vector"   # "graph" | "vector" | "both" | "none"


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # sync def -> FastAPI runs it in a threadpool, so the blocking
    # google-genai / RavenDB calls don't stall the event loop.
    ticker = req.ticker.strip().upper() if req.ticker else None
    try:
        from backend.graph.router import route_question
        answer, chunks, path = route_question(
            req.question, k=req.k, ticker=ticker, tickers=req.tickers, form=req.form
        )
    except Exception as exc:
        logger.warning("GraphRAG router error, falling back to pure vector: %s", exc)
        # Keep the same scope on the fallback path so a router failure can't
        # widen a pair question back out to a global search.
        answer, chunks = answer_question(
            req.question, k=req.k, ticker=ticker, tickers=req.tickers, form=req.form
        )
        path = "vector" if chunks else "none"
        if not chunks:
            answer = NO_CONTEXT_MESSAGE

    sources = [
        Source(ticker=c.ticker, form=c.form, chunk_index=c.chunk_index, source=c.source)
        for c in chunks
    ]
    return ChatResponse(answer=answer, sources=sources, retrieval_path=path)


# --- Streaming chat --------------------------------------------------------
# Real end-to-end token streaming. Transport: newline-delimited JSON (NDJSON)
# over a chunked HTTP response. The request is a POST with a body, which rules
# out native EventSource/SSE (GET only); the client reads the response body as a
# stream and parses one JSON event per line:
#   {"type": "token", "text": "..."}                        -- an answer delta
#   {"type": "done",  "sources": [...], "retrieval_path": "..."}  -- final meta
#   {"type": "error", "message": "..."}                     -- mid-stream failure
#
# Retrieval (keyword routing + graph/vector lookup) runs FIRST — the client shows
# the "retrieving" bird until the first token event — then generation streams.

def _chat_event_stream(
    question: str,
    k: int,
    ticker: Optional[str],
    tickers: Optional[list[str]],
    form: Optional[str],
) -> Iterator[str]:
    def _line(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False) + "\n"

    # --- Pre-generation: route + retrieve (the "bird" phase) -----------------
    try:
        from backend.graph.router import prepare_chat_stream
        segments, chunks, path = prepare_chat_stream(
            question, k=k, ticker=ticker, tickers=tickers, form=form
        )
    except Exception as exc:
        logger.warning("Stream router error, falling back to pure vector: %s", exc)
        try:
            chunks = search(question, k=k, ticker=ticker, tickers=tickers, form=form)
        except Exception:
            chunks = []
        if chunks:
            prompt = f"Context:\n{_format_context(chunks)}\n\nQuestion:\n{question}"
            segments = [{"kind": "llm", "system": SYSTEM_PROMPT, "prompt": prompt, "temperature": 0.2}]
            path = "vector"
        else:
            segments = [{"kind": "text", "text": NO_CONTEXT_MESSAGE}]
            chunks = []
            path = "none"

    sources = [
        {"ticker": c.ticker, "form": c.form, "chunk_index": c.chunk_index, "source": c.source}
        for c in chunks
    ]

    # --- Generation: stream each segment -------------------------------------
    try:
        for seg in segments:
            if seg["kind"] == "text":
                if seg["text"]:
                    yield _line({"type": "token", "text": seg["text"]})
            else:
                for delta in generate_stream(seg["system"], seg["prompt"], seg["temperature"]):
                    if delta:
                        yield _line({"type": "token", "text": delta})
        yield _line({"type": "done", "sources": sources, "retrieval_path": path})
    except Exception as exc:
        # Mid-stream failure: emit an error event. The client keeps whatever
        # partial text already arrived (it never blanks the bubble).
        logger.warning("Stream generation error: %s", exc)
        yield _line({"type": "error", "message": "The response was interrupted. Please try again."})


@router.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    ticker = req.ticker.strip().upper() if req.ticker else None
    stream = _chat_event_stream(req.question, req.k, ticker, req.tickers, req.form)
    return StreamingResponse(
        stream,
        media_type="application/x-ndjson",
        headers={
            # Defeat any intermediary buffering (nginx / Cloud Run) so chunks
            # reach the browser incrementally.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# --- Summary & comparison (generation over provided text, no retrieval) -----

SUMMARY_PROMPT = (
    "You are FinSight, an expert financial research assistant.\n"
    "Produce a structured summary of the SEC filing text provided.\n"
    "Use markdown: ## headings, bullet points (- ), and **bold** for key figures.\n"
    "Cover business overview, financial highlights, risk factors, and outlook.\n"
    "Base everything strictly on the provided text; do not invent figures."
)

COMPARE_PROMPT = (
    "You are FinSight, an expert financial research assistant.\n"
    "Compare the two SEC filings provided (Document A vs Document B).\n"
    "Use markdown: ## headings, bullet points (- ), and **bold** for key figures.\n"
    "Highlight differences in financial performance, risk factors, strategy, and "
    "guidance. Base everything strictly on the provided text; do not invent figures."
)


def generate_summary(content: str) -> str:
    client = get_genai_client()
    resp = client.models.generate_content(
        model=GEN_MODEL,
        contents=f"Filing text:\n{content}",
        config=types.GenerateContentConfig(
            system_instruction=SUMMARY_PROMPT,
            temperature=0.3,
        ),
    )
    return (resp.text or "").strip()


def compare_documents(name_a: str, content_a: str, name_b: str, content_b: str) -> str:
    client = get_genai_client()
    prompt = (
        f"Document A — {name_a}:\n{content_a}\n\n"
        f"Document B — {name_b}:\n{content_b}"
    )
    resp = client.models.generate_content(
        model=GEN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=COMPARE_PROMPT,
            temperature=0.3,
        ),
    )
    return (resp.text or "").strip()


class SummaryRequest(BaseModel):
    content: str = Field(min_length=1)


class SummaryResponse(BaseModel):
    summary: str


class CompareRequest(BaseModel):
    name_a: str
    content_a: str = Field(min_length=1)
    name_b: str
    content_b: str = Field(min_length=1)


class CompareResponse(BaseModel):
    comparison: str


@router.post("/summary", response_model=SummaryResponse)
def summary(req: SummaryRequest) -> SummaryResponse:
    return SummaryResponse(summary=generate_summary(req.content))


@router.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    return CompareResponse(
        comparison=compare_documents(req.name_a, req.content_a, req.name_b, req.content_b)
    )
