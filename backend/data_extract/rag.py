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

import logging
import os
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from google.genai import types

from .embeddings import search, get_genai_client, FilingChunk

logger = logging.getLogger(__name__)

GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-3.1-lite")

<<<<<<< HEAD
# Merged 2026-07-07: teammate's structured prompt (formerly in backend/services/
# gemini.js, now dead code there) + the original inline-citation rules.
SYSTEM_PROMPT = """You are FinSight, an expert financial statement analysis assistant.

Your responsibility is to answer the user's question accurately using the provided context from SEC filings.

Instructions:

- Use ONLY the provided context for all company-specific facts, figures, dates, financial metrics, events, and claims.
- Never invent, estimate, infer, or speculate about company-specific information that is not explicitly stated in the context.
- If the answer cannot be determined from the provided context, respond exactly with:
"I could not find sufficient information in the provided financial documents to answer this question."

- You MAY use general financial knowledge to explain standard financial concepts (such as revenue, net income, operating cash flow, gross margin, EPS, free cash flow, assets, liabilities, or cash flow), provided the explanation does NOT introduce any company-specific facts or assumptions.

- If the provided context contains conflicting or inconsistent information:
  - Do NOT choose one value over another.
  - Clearly state that the context contains conflicting information.
  - Present the conflicting values or statements.
  - Explain that the correct answer cannot be determined from the provided context alone.

- Quote financial figures exactly as they appear.
- Always include the fiscal year, reporting period, or date whenever discussing financial metrics.
- If multiple reporting periods are present, clearly distinguish between them.
- If the user asks for a comparison, compare ONLY information present in the provided context.
- Answer every part of a multi-part question whenever sufficient information exists.
- Ignore information in the context that is unrelated to the user's question.
- Do not repeat identical information across multiple sections of your response.
- Keep responses concise, professional, objective, and factual.
- Use Markdown formatting.

Citation rule: every sentence that states a specific fact or number MUST include an inline citation tag matching the block header where you found it. Use the exact format: [TICKER FORM #N]. Example: 'Apple's net sales were $391.0B in fiscal 2024 [AAPL 10-K #4].' If you draw on multiple chunks, cite each one inline, placing the tag immediately after the relevant sentence.

When appropriate, organize your response using the following structure:

## Answer
Provide a direct answer to the user's question, with inline citation tags.

## Supporting Evidence
List only the relevant facts, figures, or excerpts from the provided context that support your answer, each with its citation tag.

## Key Takeaways
Summarize the most important conclusions without repeating the Supporting Evidence section."""
=======
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
>>>>>>> cfd2a823066af4e8a727c06e2762e45bc35843ac

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


def answer_question(
    question: str,
    k: int = 5,
    ticker: Optional[str] = None,
    form: Optional[str] = None,
) -> tuple[str, list[FilingChunk]]:
    """Retrieve then generate. Returns (answer, source_chunks)."""
    chunks = search(question, k=k, ticker=ticker, form=form)
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
            req.question, k=req.k, ticker=ticker, form=req.form
        )
    except Exception as exc:
        logger.warning("GraphRAG router error, falling back to pure vector: %s", exc)
        answer, chunks = answer_question(req.question, k=req.k, ticker=ticker, form=req.form)
        path = "vector" if chunks else "none"
        if not chunks:
            answer = NO_CONTEXT_MESSAGE

    sources = [
        Source(ticker=c.ticker, form=c.form, chunk_index=c.chunk_index, source=c.source)
        for c in chunks
    ]
    return ChatResponse(answer=answer, sources=sources, retrieval_path=path)


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
