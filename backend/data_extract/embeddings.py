"""
backend/data_extract/embeddings.py

RavenDB-backed embedding ingest + semantic search for FinSight.

Design preserved from the Chroma version:
  - Paragraph-aware chunking with single-newline fallback for SEC filing prose
  - Explicit L2 normalization of vectors
  - Task-type asymmetry (RETRIEVAL_DOCUMENT for ingest, RETRIEVAL_QUERY for search)
  - Deterministic document IDs (re-ingest = upsert, never duplicates)
  - CLI with `ingest` / `search` subcommands

Embeddings are generated with gemini-embedding-001 via google-genai and stored on
the document as a plain float array. RavenDB indexes pre-made numerical arrays
directly (no transformation), so all generation control stays in this module.

Auth (auto-detected by get_genai_client):
  - GEMINI_API_KEY set      -> Gemini Developer API (key mode)
  - else GOOGLE_CLOUD_PROJECT -> Vertex AI (ADC; run `gcloud auth application-default login`)

Prerequisites:
  - A running RavenDB server (7.x) using the Corax search engine
  - pip install ravendb google-genai numpy
  - Env: RAVENDB_URLS, RAVENDB_DATABASE, and either GEMINI_API_KEY
    or (GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION) for Vertex mode
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import time
from typing import Iterable, Optional

import numpy as np
from google import genai
from google.genai import types
from ravendb import DocumentStore

logger = logging.getLogger(__name__)

# --- Configuration ----------------------------------------------------------

RAVENDB_URLS = [u.strip() for u in os.getenv("RAVENDB_URLS", "http://127.0.0.1:8080").split(",")]
RAVENDB_DATABASE = os.getenv("RAVENDB_DATABASE", "finsight")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
# "global" is not valid for the embedding model on Vertex; default to a region.
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))  # must stay consistent across all docs
COLLECTION = "FilingChunks"

# Batch size for embed_content calls. Small value (8) avoids per-minute token
# quota spikes on the free tier while still saving round-trips vs. one-at-a-time.
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "8"))
# Seconds to sleep between embedding batches (prevents 429 on free-tier RPM cap).
EMBED_BATCH_DELAY = float(os.getenv("EMBED_BATCH_DELAY", "1.0"))

# --- Singletons -------------------------------------------------------------

_store: Optional[DocumentStore] = None
_genai_client: Optional[genai.Client] = None


def get_store() -> DocumentStore:
    """Lazily initialize and return the shared RavenDB DocumentStore."""
    global _store
    if _store is None:
        store = DocumentStore(RAVENDB_URLS, RAVENDB_DATABASE)
        store.initialize()
        _store = store
        logger.info("Initialized RavenDB store: %s db=%s", RAVENDB_URLS, RAVENDB_DATABASE)
    return _store


def get_genai_client() -> genai.Client:
    """
    Build the shared google-genai client, auto-selecting the auth mode:

      1. API key  -- if GEMINI_API_KEY is set (Gemini Developer API).
      2. Vertex AI -- otherwise, using GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION
         and Application Default Credentials. Run `gcloud auth application-default
         login` once; no API key required.
    """
    global _genai_client
    if _genai_client is None:
        if GEMINI_API_KEY:
            _genai_client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("google-genai client: API key mode")
        elif GOOGLE_CLOUD_PROJECT:
            _genai_client = genai.Client(
                vertexai=True,
                project=GOOGLE_CLOUD_PROJECT,
                location=GOOGLE_CLOUD_LOCATION,
            )
            logger.info(
                "google-genai client: Vertex mode (project=%s, location=%s)",
                GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION,
            )
        else:
            raise RuntimeError(
                "No Gemini credentials found. Set GEMINI_API_KEY, or "
                "GOOGLE_CLOUD_PROJECT (+ GOOGLE_CLOUD_LOCATION) for Vertex mode."
            )
    return _genai_client


# --- Document model ---------------------------------------------------------

class FilingChunk:
    """A single embedded chunk of an SEC filing."""

    def __init__(
        self,
        Id: Optional[str] = None,
        ticker: str = "",
        form: str = "",
        source: str = "",
        chunk_index: int = 0,
        text: str = "",
        embedding: Optional[list] = None,
    ):
        self.Id = Id
        self.ticker = ticker
        self.form = form
        self.source = source
        self.chunk_index = chunk_index
        self.text = text
        # Stored as a plain float array. For large corpora, swap to RavenDB's
        # RavenVector type for tighter storage / faster reads.
        self.embedding = embedding or []


# --- Embedding generation ---------------------------------------------------

def _normalize(vec: Iterable[float]) -> list:
    """L2-normalize a vector; required for sub-3072 cosine consistency."""
    arr = np.asarray(list(vec), dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        return arr.tolist()
    return (arr / norm).tolist()


def embed_texts(texts: list[str], task_type: str) -> list[list]:
    """
    Embed a list of texts with the given task type, normalized.

    Uses small batches (EMBED_BATCH) with inter-batch sleep to pace the free-
    tier quota. On 429 RESOURCE_EXHAUSTED (per-minute RPM cap), waits 62s and
    retries up to 3 times — the API returns retryDelay ~60s on rate limits.
    """
    client = get_genai_client()
    out: list[list] = []
    for i, start in enumerate(range(0, len(texts), EMBED_BATCH)):
        if i > 0 and EMBED_BATCH_DELAY > 0:
            time.sleep(EMBED_BATCH_DELAY)
        batch = texts[start:start + EMBED_BATCH]

        for attempt in range(4):  # up to 3 retries
            try:
                resp = client.models.embed_content(
                    model=EMBED_MODEL,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type=task_type,
                        output_dimensionality=EMBED_DIM,
                    ),
                )
                out.extend(_normalize(e.values) for e in resp.embeddings)
                break
            except Exception as e:
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < 3:
                    wait = 62 + attempt * 10  # 62s, 72s, 82s
                    logger.warning(
                        "Embedding 429 on batch %d/%d (attempt %d), waiting %ds…",
                        i + 1, (len(texts) + EMBED_BATCH - 1) // EMBED_BATCH,
                        attempt + 1, wait,
                    )
                    time.sleep(wait)
                else:
                    raise
    return out


# --- Chunking ---------------------------------------------------------------

_DOUBLE_NL = re.compile(r"\n\s*\n+")
_SINGLE_NL = re.compile(r"\n")


def chunk_text(text: str, max_chars: int = 1800, overlap_paras: int = 1) -> list[str]:
    """
    Paragraph-aware chunking tuned for SEC filing prose.

    SEC filings extracted from HTML typically have only single newlines between
    sentences/paragraphs (not double newlines), so the splitter falls back from
    double-newline to single-newline splitting when paragraphs would be too large.
    Any line still exceeding max_chars is then split further at word boundaries.

    Consecutive small items are grouped up to the max_chars budget, with one
    unit of overlap between consecutive chunks for context continuity.
    """
    # 1. Try double-newline split (proper paragraphs)
    raw = [p.strip() for p in _DOUBLE_NL.split(text) if p.strip()]

    # If every "paragraph" is huge (no blank lines), fall back to single newlines
    if raw and max(len(p) for p in raw) > max_chars * 2:
        raw = [p.strip() for p in _SINGLE_NL.split(text) if p.strip()]

    # 2. Sub-split any line that still exceeds max_chars at word boundaries
    paras: list[str] = []
    for p in raw:
        if len(p) <= max_chars:
            paras.append(p)
        else:
            words = p.split()
            buf: list[str] = []
            size = 0
            for word in words:
                if size + len(word) + 1 > max_chars and buf:
                    paras.append(" ".join(buf))
                    buf = []
                    size = 0
                buf.append(word)
                size += len(word) + 1
            if buf:
                paras.append(" ".join(buf))

    # 3. Group paras into chunks with overlap
    chunks: list[str] = []
    buf_paras: list[str] = []
    size = 0

    for para in paras:
        if buf_paras and size + len(para) > max_chars:
            chunks.append("\n\n".join(buf_paras))
            buf_paras = buf_paras[-overlap_paras:] if overlap_paras else []
            size = sum(len(p) for p in buf_paras)
        buf_paras.append(para)
        size += len(para)

    if buf_paras:
        chunks.append("\n\n".join(buf_paras))

    return chunks


# --- IDs --------------------------------------------------------------------

def _chunk_id(ticker: str, form: str, source: str, idx: int) -> str:
    raw = f"{ticker}|{form}|{source}|{idx}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    return f"{COLLECTION}/{ticker}-{form}-{digest}"


# --- Ingest -----------------------------------------------------------------

def ingest(ticker: str, form: str, text: str, source: str) -> int:
    """
    Chunk -> embed (RETRIEVAL_DOCUMENT) -> upsert into RavenDB.
    Returns the number of chunks stored. Re-ingesting the same source overwrites
    by deterministic ID instead of duplicating.
    """
    ticker = ticker.strip().upper()
    chunks = chunk_text(text)
    if not chunks:
        logger.warning("No chunks produced for %s %s (%s)", ticker, form, source)
        return 0

    logger.info("Embedding %d chunks for %s %s (batch=%d, delay=%.1fs)…",
                len(chunks), ticker, form, EMBED_BATCH, EMBED_BATCH_DELAY)
    vectors = embed_texts(chunks, task_type="RETRIEVAL_DOCUMENT")

    store = get_store()
    with store.open_session() as session:
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
            doc_id = _chunk_id(ticker, form, source, idx)
            doc = FilingChunk(
                Id=doc_id,
                ticker=ticker,
                form=form,
                source=source,
                chunk_index=idx,
                text=chunk,
                embedding=vec,
            )
            session.store(doc, doc_id)
        session.save_changes()

    logger.info("Ingested %d chunks for %s %s (%s)", len(chunks), ticker, form, source)
    return len(chunks)


# --- Search -----------------------------------------------------------------

def search(
    query: str,
    k: int = 5,
    ticker: Optional[str] = None,
    form: Optional[str] = None,
    min_similarity: float = 0.75,
    candidates: int = 32,
) -> list[FilingChunk]:
    """
    Embed the query (RETRIEVAL_QUERY) and run a dynamic vector search.
    Optional ticker/form act as regular filters combined with the vector search.
    """
    qvec = embed_texts([query], task_type="RETRIEVAL_QUERY")[0]

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


# --- CLI --------------------------------------------------------------------

def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="FinSight embeddings (RavenDB)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Embed and store a filing")
    p_ingest.add_argument("--ticker", required=True)
    p_ingest.add_argument("--form", required=True, choices=["10-K", "10-Q"])
    p_ingest.add_argument("--source", required=True, help="Filing identifier / path")
    p_ingest.add_argument("--file", required=True, help="Path to extracted filing text")

    p_search = sub.add_parser("search", help="Semantic search over stored filings")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--k", type=int, default=5)
    p_search.add_argument("--ticker", default=None)
    p_search.add_argument("--form", default=None, choices=["10-K", "10-Q", None])
    p_search.add_argument("--min-similarity", type=float, default=0.75)

    args = parser.parse_args()

    if args.command == "ingest":
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
        n = ingest(args.ticker, args.form, text, args.source)
        print(f"Stored {n} chunks.")

    elif args.command == "search":
        results = search(
            args.query,
            k=args.k,
            ticker=args.ticker,
            form=args.form,
            min_similarity=args.min_similarity,
        )
        for r in results:
            preview = r.text[:160].replace("\n", " ")
            print(f"[{r.ticker} {r.form} #{r.chunk_index}] {preview}...")


if __name__ == "__main__":
    _cli()
