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
import re
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
    "Citation rule: the context is a NUMBERED list of source passages, each beginning with a "
    "marker like [1], [2], [3]. Every sentence that states a specific fact or figure MUST end with "
    "the bracketed number(s) of the passage(s) that actually support it. "
    "Example: 'Apple's net sales were $391.0B in fiscal 2024 [2].'\n"
    "Use ONLY the numbers shown in the context. NEVER invent a number that is not in the list, and "
    "NEVER attach a citation to a passage that does not support the claim. If you draw on more than "
    "one passage, cite each, e.g. [1][3]. If a statement is general financial background rather than "
    "a fact from the filings, do not attach any citation."
)

NO_CONTEXT_MESSAGE = (
    "I couldn't find anything relevant in the indexed filings to answer that. "
    "Try rephrasing, or check that the relevant filing has been ingested."
)


# --- Core ------------------------------------------------------------------

def _format_context(chunks: list[FilingChunk]) -> str:
    """Tag each chunk with a STABLE citation number [n] so the model can cite it.

    The citation number is the chunk's 1-based position in the retrieval-ranked
    `chunks` list (n=1 is rank-0, the most relevant). That number is what the
    reference list (build_references) and the validator (validate_citations) both
    key on, so the [n] the model emits maps deterministically back to a real
    retrieved chunk — the model never chooses or invents the numbering.

    Ordering: the two best chunks still bookend the physical text (rank-0 first,
    rank-1 last, the rest between) to reduce the "lost in the middle" attention
    drop — but each block keeps its own [n] header, so physical order and
    citation number are independent.
    """
    numbered = list(enumerate(chunks, start=1))  # (n, chunk) in retrieval order
    if len(numbered) > 2:
        ordered = [numbered[0]] + numbered[2:] + [numbered[1]]
    else:
        ordered = numbered
    blocks = []
    for n, c in ordered:
        loc = f" — {c.source}" if c.source else ""
        tag = f"[{n}] {c.ticker} {c.form}{loc}"
        blocks.append(f"{tag}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


# --- Deterministic reference list + anti-fabrication citation validation ------
# The reference list is built from the ACTUAL retrieved chunks — never from the
# model. The model only emits inline [n] markers; validate_citations() then keeps
# a marker only if n is in range AND (for numeric claims) the cited chunk really
# contains the figure. A hallucinated citation looks verified, so we prefer to
# drop a marker than render a misleading link.

def _preview(text: str, limit: int = 240) -> str:
    """Collapse whitespace and cap to a short, single-line snippet for the UI."""
    t = " ".join((text or "").split())
    return t[:limit] + ("…" if len(t) > limit else "")


# Ingest concatenates sections as "## {Label}\n\n{text}" (see app._build_ingest_text),
# so the section a chunk belongs to is the "## " heading at/near its start. Chunks
# in the middle of a long section carry no heading — those get a blank section and
# the UI simply shows "{Company} · {form}".
_SECTION_RE = re.compile(r"^\s*##\s+(.+?)\s*$", re.MULTILINE)


def _section_from_text(text: str) -> str:
    m = _SECTION_RE.search(text or "")
    if not m:
        return ""
    label = m.group(1).strip()
    # Headings sometimes run straight into body ("Business Item 1. Business …");
    # keep just the leading title-ish part so the row label stays short.
    label = re.split(r"\s+Item\s+\d", label, maxsplit=1)[0].strip()
    return label[:60]


_LEADING_HEADING_RE = re.compile(r"^\s*##\s+.*?(?:\n+|$)")


def _strip_leading_heading(text: str) -> str:
    """Drop a leading '## Heading' line — it's surfaced as the row's section label,
    so it would be redundant/raw in the snippet and the passage body."""
    return _LEADING_HEADING_RE.sub("", text or "", count=1).lstrip()


def build_references(chunks: list[FilingChunk]) -> list[dict]:
    """Numbered reference list [1..N] from the actual retrieved chunks.

    Numbering matches _format_context (retrieval rank order), so an inline [n]
    resolves to references[n-1]. Each entry carries enough to show readable filing
    context (resolved company name, form, best-effort section) and to let the user
    inspect the exact source passage (full `text`) and open the filing (`url`).

    `company` is resolved from the SEC registry so the row shows "Gap Inc." rather
    than the bare/cryptic registry ticker ("GAP", "S"). `url` (the SEC source) is
    carried for the "View on SEC EDGAR" href only — never as visible text.
    """
    try:
        from .sec_client import company_name_for_ticker
    except Exception:
        company_name_for_ticker = lambda _t: None  # noqa: E731 — fail soft to ticker

    refs: list[dict] = []
    for i, c in enumerate(chunks, start=1):
        url = c.source if (c.source or "").startswith("http") else ""
        body = _strip_leading_heading(c.text)
        refs.append({
            "number": i,
            "ticker": c.ticker,
            "company": company_name_for_ticker(c.ticker) or c.ticker,
            "form": c.form,
            "accession_number": c.accession_number,
            "section": _section_from_text(c.text),
            "url": url,
            "source": c.source,            # back-compat; the UI never renders this
            "chunk_index": c.chunk_index,
            "filing_date": c.filing_date,
            "preview": _preview(body),
            "text": body[:6000],
        })
    return refs


def _assemble_sources(chunks: list[FilingChunk], graph_sources: Optional[list[dict]]) -> list[dict]:
    """One reference list across retrieval paths: vector passages first (numbered
    1..V, the numbers inline [n] markers resolve to), then graph/XBRL fact cards
    (V+1..). Both are the SAME shape, so the UI renders one consistent component
    regardless of path — a graph answer is never given a lesser treatment."""
    refs = build_references(chunks)
    n = len(refs)
    for j, gs in enumerate(graph_sources or [], start=1):
        refs.append({**gs, "number": n + j})
    return refs


# A grounded answer that turns out to be "I can't find/identify this" must NOT
# carry a citation list — dangling passages for a non-answer read as misleading
# evidence. These are the exact refusal sentinels the prompts/router emit.
_REFUSAL_SIGNS = (
    "could not find sufficient information",
    "couldn't find anything relevant",
    "could not find anything relevant",
)


def _looks_like_refusal(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in _REFUSAL_SIGNS)


_CITATION_RE = re.compile(r"\[(\d{1,3})\]")

# "Financial-looking" numbers (has a decimal, a $/%, or is 3+ digits); bare small
# integers and 4-digit years are labels, not claims. Mirrors the graph-path
# grounding check so numeric support is judged the same way across both paths.
_NUM_RE = re.compile(r"\$?\s?-?\d[\d,]*\.?\d*\s?%?")


def _financial_numbers(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group()
        core = raw.replace("$", "").replace("%", "").replace(",", "").replace(" ", "").strip("-").rstrip(".")
        if not core or core == ".":
            continue
        if re.fullmatch(r"(19|20)\d{2}", core):
            continue
        if "." not in core and "%" not in raw and "$" not in raw and len(core) < 3:
            continue
        out.add(core)
    return out


# A sentence break is a terminator FOLLOWED BY whitespace, or a newline — so the
# decimal point in "$391.04" (followed by a digit) is NOT treated as a boundary
# and the figure stays inside the claim it belongs to.
_SENT_BREAK = re.compile(r"[.;:](?=\s)|\n")


def _claim_before(answer: str, idx: int) -> str:
    """The clause/sentence immediately preceding a citation marker at `idx` —
    from the previous sentence break up to the marker."""
    last = 0
    for m in _SENT_BREAK.finditer(answer[:idx]):
        last = m.end()
    return answer[last:idx]


def validate_citations(answer: str, chunks: list[FilingChunk]) -> list[int]:
    """Return the sorted set of citation numbers in `answer` that are BOTH in
    range [1..N] AND supported by the cited chunk.

    Support rule: if the claim preceding the marker contains financial figures,
    at least one must appear in the cited chunk's text (prefix-tolerant, so a
    figure cited at coarser precision — 391 vs 391.04 — still matches). Purely
    qualitative claims pass the existence check (n is a real chunk). Any marker
    that fails is dropped by the caller — never rendered as a link.
    """
    n = len(chunks)
    valid: set[int] = set()
    for m in _CITATION_RE.finditer(answer or ""):
        num = int(m.group(1))
        if not (1 <= num <= n):
            continue
        if num in valid:
            continue
        claim_nums = _financial_numbers(_claim_before(answer, m.start()))
        if not claim_nums:
            valid.add(num)
            continue
        chunk_nums = _financial_numbers(chunks[num - 1].text or "")
        if any(any(a == b or b.startswith(a) or a.startswith(b) for b in chunk_nums) for a in claim_nums):
            valid.add(num)
        # else: a numeric claim the cited chunk does not contain — drop it.
    return sorted(valid)


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
    # Deterministic reference-list entry (see build_references). `number` is the
    # 1-based citation number an inline [n] marker resolves to.
    number: int = 0
    ticker: str
    company: str = ""          # resolved readable name ("Gap Inc."), not the ticker
    form: str
    chunk_index: int
    source: str
    section: str = ""
    url: str = ""              # SEC source URL — used only as the EDGAR href
    accession_number: str = ""
    filing_date: str = ""
    preview: str = ""
    text: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    # Citation numbers that survived validation (in range + supported). The UI
    # linkifies ONLY these inline [n]; any other [n] is a fabricated citation and
    # is dropped rather than rendered.
    valid_citations: list[int] = []
    retrieval_path: str = "vector"   # "graph" | "vector" | "both" | "none"


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # sync def -> FastAPI runs it in a threadpool, so the blocking
    # google-genai / RavenDB calls don't stall the event loop.
    ticker = req.ticker.strip().upper() if req.ticker else None
    graph_sources: list[dict] = []
    try:
        from backend.graph.router import route_question
        answer, chunks, graph_sources, path = route_question(
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

    # Refusal answers carry no citations (see _looks_like_refusal).
    if _looks_like_refusal(answer):
        return ChatResponse(answer=answer, sources=[], valid_citations=[], retrieval_path=path)

    refs = _assemble_sources(chunks, graph_sources)
    sources = [Source(**r) for r in refs]
    valid = validate_citations(answer, chunks)
    return ChatResponse(answer=answer, sources=sources, valid_citations=valid, retrieval_path=path)


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
    graph_sources: list[dict] = []
    try:
        from backend.graph.router import prepare_chat_stream
        segments, chunks, graph_sources, path = prepare_chat_stream(
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

    # One reference list across paths: vector passages (numbered, inline-cited) +
    # graph/XBRL fact cards, same shape → one consistent citation UI.
    references = _assemble_sources(chunks, graph_sources)

    # --- Generation: stream each segment -------------------------------------
    # Accumulate the full answer as it streams so citations can be validated at
    # COMPLETION (the full claim set isn't known mid-stream). Tokens still stream
    # to the client for live rendering; the reference list + validated marker set
    # are attached only in the terminal `done` event.
    parts: list[str] = []
    try:
        for seg in segments:
            if seg["kind"] == "text":
                if seg["text"]:
                    parts.append(seg["text"])
                    yield _line({"type": "token", "text": seg["text"]})
            else:
                for delta in generate_stream(seg["system"], seg["prompt"], seg["temperature"]):
                    if delta:
                        parts.append(delta)
                        yield _line({"type": "token", "text": delta})
        full_answer = "".join(parts)
        # A refusal ("I can't find/identify this") must not show a citation list —
        # dangling passages under a non-answer read as misleading evidence.
        if _looks_like_refusal(full_answer):
            references, valid = [], []
        else:
            valid = validate_citations(full_answer, chunks)
        yield _line({
            "type": "done",
            "sources": references,
            "valid_citations": valid,
            "retrieval_path": path,
        })
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
