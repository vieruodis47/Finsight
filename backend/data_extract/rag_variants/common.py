"""
backend/data_extract/rag_variants/common.py

Shared plumbing for all RAG variants:

  - VariantResult: the contract every variant returns.
  - UsageMeter + measure(): one instrumentation layer that meters LLM tokens
    and retrieval calls identically for every variant by wrapping the shared
    google-genai client. Variants never self-report token counts — the meter
    sees every generate_content / embed_content call, including calls made
    deep inside backend/graph/router.py.
  - generate(): grounded generation with the production system prompt
    (identical model, temperature, prompt across variants unless the prompt
    itself is the registered experimental variable).
  - search_by_vector(): RavenDB vector search for a caller-supplied embedding
    (HyDE needs to search with a hypothetical-document vector, not the query).
  - run_variant(): wraps a variant implementation with timing + metering and
    assembles the VariantResult.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Load env exactly like backend/scripts/bulk_ingest.py does, BEFORE importing
# modules that read os.getenv at import time (rag.GEN_MODEL).
_REPO = Path(__file__).resolve().parents[3]
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / "backend" / ".env.python")
except ImportError:
    pass

from google.genai import types  # noqa: E402

from ..embeddings import (  # noqa: E402
    FilingChunk,
    embed_texts,
    get_genai_client,
    get_store,
    COLLECTION,
)
from .. import rag as prod_rag  # noqa: E402

GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-3.1-flash-lite")
EMBED_DIM_KEY = os.getenv("EMBED_DIM", "1536")  # embed-cache key component
GEN_TEMPERATURE = 0.2
# The production system prompt — the shared constant for all architecture
# variants. Prompt-engineering variants override it explicitly and register
# the prompt as their experimental variable.
SYSTEM_PROMPT = prod_rag.SYSTEM_PROMPT


# --- Contract ----------------------------------------------------------------

@dataclass
class VariantResult:
    answer: str
    sources: list = field(default_factory=list)      # list of chunk-ref dicts
    trace: list = field(default_factory=list)        # retrieval steps taken
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    retrieval_calls: int = 0
    llm_calls: int = 0
    config: dict = field(default_factory=dict)
    error: Optional[str] = None
    call_inputs: list = field(default_factory=list)  # LLM inputs, for faithfulness judging


def chunk_ref(c: FilingChunk) -> dict:
    """Serializable reference to a retrieved chunk (text kept for judging)."""
    return {
        "ticker": c.ticker,
        "form": c.form,
        "chunk_index": c.chunk_index,
        "source": c.source,
        "filing_date": getattr(c, "filing_date", ""),
        "text": c.text,
    }


# --- Instrumentation ---------------------------------------------------------

_MAX_CAPTURED_CALLS = 8
_MAX_CAPTURED_CHARS = 12000


class UsageMeter:
    """Accumulates token usage and call counts for one variant invocation.

    Also captures each LLM call's input payload (truncated) so the scorer can
    judge faithfulness against the exact context the model saw — including
    calls made inside backend/graph/router.py that variants can't observe.
    """

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.llm_calls = 0
        self.retrieval_calls = 0
        self.call_inputs: list[str] = []

    def add_usage(self, resp, contents=None) -> None:
        self.llm_calls += 1
        meta = getattr(resp, "usage_metadata", None)
        if meta is not None:
            self.prompt_tokens += int(getattr(meta, "prompt_token_count", 0) or 0)
            self.completion_tokens += int(
                getattr(meta, "candidates_token_count", 0) or 0
            ) + int(getattr(meta, "thoughts_token_count", 0) or 0)
        if contents is not None and len(self.call_inputs) < _MAX_CAPTURED_CALLS:
            self.call_inputs.append(str(contents)[:_MAX_CAPTURED_CHARS])


_local = threading.local()


def _current_meter() -> Optional[UsageMeter]:
    return getattr(_local, "meter", None)


_patch_lock = threading.Lock()
_patched = False


def _install_client_wrapper() -> None:
    """
    Wrap the shared genai client's generate_content AND the module-level
    vector search functions once, so every LLM call and every retrieval made
    anywhere in the process (rag.py, graph/router.py, variant code) is metered
    when a UsageMeter is active on this thread. rag.py binds `search` into its
    own namespace at import time, so both binding sites are patched.
    """
    global _patched
    with _patch_lock:
        if _patched:
            return
        client = get_genai_client()
        original = client.models.generate_content

        def wrapped(*args, **kwargs):
            _throttle_generation()
            resp = original(*args, **kwargs)
            meter = _current_meter()
            if meter is not None:
                contents = kwargs.get("contents")
                if contents is None and len(args) >= 2:
                    contents = args[1]
                meter.add_usage(resp, contents=contents)
            return resp

        client.models.generate_content = wrapped

        from .. import embeddings as _emb
        _orig_search = _emb.search

        def counted_search(*args, **kwargs):
            meter = _current_meter()
            if meter is not None:
                meter.retrieval_calls += 1
            return _orig_search(*args, **kwargs)

        _emb.search = counted_search
        prod_rag.search = counted_search  # rebind rag.py's import-time alias

        # Query-embedding cache (quota saver, results-identical): the same
        # question text is embedded up to variants x repeats times across an
        # experiment; embeddings are deterministic, so duplicates are pure
        # waste. Enabled only when EMBED_CACHE_PATH is set (the runner sets
        # it); RETRIEVAL_DOCUMENT (ingest) is never cached. Caveat for
        # reports: latency of a repeated identical query excludes the embed
        # API round-trip.
        _orig_embed = _emb.embed_texts

        def caching_embed(texts, task_type):
            path = os.getenv("EMBED_CACHE_PATH")
            if not path or task_type != "RETRIEVAL_QUERY":
                return _orig_embed(texts, task_type)
            cache = _load_embed_cache(path)
            missing = [t for t in texts if _ekey(t) not in cache]
            if missing:
                vecs = _orig_embed(missing, task_type)
                with open(path, "a", encoding="utf-8") as fh:
                    for t, v in zip(missing, vecs):
                        cache[_ekey(t)] = v
                        fh.write(json.dumps({"k": _ekey(t), "v": v}) + "\n")
            return [cache[_ekey(t)] for t in texts]

        _emb.embed_texts = caching_embed

        _patched = True


_embed_cache: Optional[dict] = None


def _ekey(text: str) -> str:
    import hashlib
    return hashlib.sha256(f"RETRIEVAL_QUERY|{EMBED_DIM_KEY}|{text}".encode()).hexdigest()


def _load_embed_cache(path: str) -> dict:
    global _embed_cache
    if _embed_cache is None:
        _embed_cache = {}
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    row = json.loads(line)
                    _embed_cache[row["k"]] = row["v"]
        except FileNotFoundError:
            pass
    return _embed_cache


class measure:
    """Context manager activating a UsageMeter for the current thread."""

    def __init__(self) -> None:
        self.meter = UsageMeter()

    def __enter__(self) -> UsageMeter:
        _install_client_wrapper()
        _local.meter = self.meter
        return self.meter

    def __exit__(self, *exc) -> None:
        _local.meter = None


# --- Generation --------------------------------------------------------------

# Free-tier generate_content is capped at 15 requests/min/model. A global
# min-interval keeps every metered call (variants, graph-internal, judges via
# the shared client) under the cap instead of burning 429 retries.
_GEN_MIN_INTERVAL_S = float(os.getenv("GEN_MIN_INTERVAL_S", "4.5"))
_throttle_lock = threading.Lock()
_last_gen_at = 0.0


def _throttle_generation() -> None:
    global _last_gen_at
    if _GEN_MIN_INTERVAL_S <= 0:
        return
    with _throttle_lock:
        now = time.monotonic()
        wait = _last_gen_at + _GEN_MIN_INTERVAL_S - now
        if wait > 0:
            time.sleep(wait)
        _last_gen_at = time.monotonic()


_GEN_RETRY_WAITS = [20, 45, 75]


def llm(
    contents: str,
    system: Optional[str] = None,
    temperature: float = GEN_TEMPERATURE,
    model: str = GEN_MODEL,
) -> str:
    """One generate_content call with 429 retry. Metered via the client wrapper."""
    client = get_genai_client()
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
    )
    for attempt in range(len(_GEN_RETRY_WAITS) + 1):
        try:
            resp = client.models.generate_content(
                model=model, contents=contents, config=cfg
            )
            return (resp.text or "").strip()
        except Exception as e:
            msg = str(e)
            transient = any(m in msg for m in
                            ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                             "500 INTERNAL", "Internal error", "DeadlineExceeded",
                             "504"))
            if transient and attempt < len(_GEN_RETRY_WAITS):
                wait = _GEN_RETRY_WAITS[attempt]
                logger.warning("generate_content transient error, retrying in %ds: %s",
                               wait, str(e)[:120])
                time.sleep(wait)
            else:
                raise
    return ""  # unreachable


def llm_json(contents: str, system: Optional[str] = None, temperature: float = 0.0,
             model: str = GEN_MODEL):
    """LLM call that must return JSON; tolerates markdown fences. None on failure."""
    raw = llm(contents, system=system, temperature=temperature, model=model)
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"[\[{].*[\]}]", raw, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    logger.warning("llm_json: unparseable JSON: %s", raw[:200])
    return None


def format_context(chunks: list[FilingChunk]) -> str:
    """The production context format (bookend ordering) from rag.py."""
    return prod_rag._format_context(chunks)


def generate_grounded(question: str, chunks: list[FilingChunk],
                      system_prompt: str = SYSTEM_PROMPT,
                      context_formatter: Callable = format_context) -> str:
    """Grounded generation matching the production call shape."""
    context = context_formatter(chunks)
    return llm(
        f"Context:\n{context}\n\nQuestion:\n{question}",
        system=system_prompt,
        temperature=GEN_TEMPERATURE,
    )


# --- Retrieval helpers ---------------------------------------------------------

def vector_search(query: str, k: int = 5, ticker: Optional[str] = None,
                  form: Optional[str] = None) -> list[FilingChunk]:
    """Production vector search. Counting happens in the patched
    embeddings.search (see _install_client_wrapper) — no double count here."""
    from .. import embeddings
    return embeddings.search(query, k=k, ticker=ticker, form=form)


def search_by_vector(qvec: list, k: int = 5, ticker: Optional[str] = None,
                     form: Optional[str] = None, min_similarity: float = 0.60,
                     candidates: int = 32) -> list[FilingChunk]:
    """
    Same RQL as embeddings.search but with a caller-supplied vector (HyDE).
    Lower default min_similarity: doc-vs-doc similarities run lower than
    query-vs-doc under the asymmetric task-type embedding.
    """
    meter = _current_meter()
    if meter is not None:
        meter.retrieval_calls += 1

    filters = []
    if ticker:
        filters.append("ticker = $ticker")
    if form:
        filters.append("form = $form")
    filter_clause = (" and ".join(filters) + " and ") if filters else ""
    rql = (
        f'from "{COLLECTION}" '
        f"where {filter_clause}"
        f"vector.search(embedding, $queryVector, $minSim, $candidates) "
        f"limit {int(k)}"
    )
    store = get_store()
    with store.open_session() as session:
        q = (
            session.advanced.raw_query(rql, object_type=FilingChunk)
            .add_parameter("queryVector", qvec)
            .add_parameter("minSim", min_similarity)
            .add_parameter("candidates", candidates)
        )
        if ticker:
            q = q.add_parameter("ticker", ticker.strip().upper())
        if form:
            q = q.add_parameter("form", form)
        return list(q)


def embed(texts: list[str], task_type: str) -> list[list]:
    """Embedding call passthrough (quota handling lives in embeddings.py).
    Routed through the module so the caching wrapper applies."""
    from .. import embeddings
    return embeddings.embed_texts(texts, task_type=task_type)


def dedupe_chunks(chunks: list[FilingChunk]) -> list[FilingChunk]:
    """First-seen-order dedupe by (ticker, form, source, chunk_index)."""
    seen: set = set()
    out: list[FilingChunk] = []
    for c in chunks:
        key = (c.ticker, c.form, c.source, c.chunk_index)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


# --- Variant wrapper -----------------------------------------------------------

def run_variant(impl: Callable, config: dict, question: str, k: int = 5,
                ticker: Optional[str] = None, form: Optional[str] = None) -> VariantResult:
    """
    Execute a variant implementation with uniform timing + metering.

    impl(question, k, ticker, form, trace) -> (answer_text, sources_list)
    where sources_list is list[FilingChunk] or list[dict] chunk refs.
    """
    trace: list = []
    t0 = time.perf_counter()
    error = None
    answer, sources = "", []
    with measure() as meter:
        try:
            answer, sources = impl(question, k, ticker, form, trace)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            logger.exception("Variant %s failed", config.get("variant"))
    latency_ms = int((time.perf_counter() - t0) * 1000)

    refs = [chunk_ref(s) if isinstance(s, FilingChunk) else s for s in (sources or [])]
    return VariantResult(
        answer=answer or "",
        sources=refs,
        trace=trace,
        prompt_tokens=meter.prompt_tokens,
        completion_tokens=meter.completion_tokens,
        latency_ms=latency_ms,
        retrieval_calls=meter.retrieval_calls,
        llm_calls=meter.llm_calls,
        config=dict(config),
        error=error,
        call_inputs=meter.call_inputs,
    )
