"""
backend/data_extract/embeddings.py

RavenDB-backed embedding ingest + semantic search for FinSight.

Design preserved from the Chroma version:
  - Paragraph-aware chunking with single-newline fallback for SEC filing prose
  - Explicit L2 normalization of vectors
  - Deterministic document IDs (re-ingest = upsert, never duplicates)
  - CLI with `ingest` / `search` subcommands

Embeddings are generated with bge-m3 (1024-dim, MIT) in-process by
sentence-transformers and stored on the document as a plain float array. One
producer for BOTH ingest and query, in local dev and in the deployed
python-service — no separate embedding service, no network hop. Unlike
gemini-embedding-001, bge-m3 uses the SAME encoder for documents and queries (no
RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY task-type asymmetry). RavenDB indexes
pre-made numerical arrays directly (no transformation), so all generation control
stays in this module. Generation (answers / summaries) still uses Gemini via
get_genai_client().

Deduplication
-------------
An IngestManifest document is written (upserted) to RavenDB only after ALL
chunks for a filing are successfully stored. This makes completeness detection
reliable: manifest present with chunk_count > 0 → fully indexed; no manifest
(or manifest absent) → partial or never ingested.

check_already_indexed() runs two passes:
  1. Fast O(1) manifest lookup by accession_number.
  2. Fallback: count existing chunks by ticker+form+source URL, covering filings
     ingested before manifest support was added. A retroactive manifest is
     written on hit so future checks use the fast path.

Persistent job queue
--------------------
IngestJob documents in the IngestJobs collection survive server restarts.
  upsert_job()         — create or reset a job entry
  update_job_status()  — update status, chunks, error, and quota-retry fields
  load_active_jobs()   — load all jobs not yet indexed (for startup recovery)

DailyQuotaExceededError is raised by embed_texts() when the Gemini per-day
quota is hit (PerDay in the error). The caller (app._run_ingest) handles this
by transitioning the job to waiting_for_quota instead of failed.

Auth (auto-detected by get_genai_client):
  - GEMINI_API_KEY set      -> Gemini Developer API (key mode)
  - else GOOGLE_CLOUD_PROJECT -> Vertex AI (ADC; run `gcloud auth application-default login`)

Prerequisites:
  - A running RavenDB server (7.x) using the Corax search engine
  - pip install ravendb google-genai numpy sentence-transformers torch
  - Env: RAVENDB_URLS, RAVENDB_DATABASE, and either GEMINI_API_KEY
    or (GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION) for Vertex mode
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

import numpy as np
from google import genai
from ravendb import DocumentStore

logger = logging.getLogger(__name__)

# --- Configuration ----------------------------------------------------------

RAVENDB_URLS = [u.strip() for u in os.getenv("RAVENDB_URLS", "http://127.0.0.1:8080").split(",")]
RAVENDB_DATABASE = os.getenv("RAVENDB_DATABASE", "finsight")
RAVENDB_CERT_PATH = os.getenv("RAVENDB_CERT_PATH")  # set for RavenDB Cloud; unset for local dev

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
# "global" is not valid for the embedding model on Vertex; default to a region.
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Embeddings are generated in-process by sentence-transformers (bge-m3). Same
# encoder for docs and queries — no task-type prefix on either side.
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
# Pin the exact model revision so the query producer is byte-identical to the one
# validated for stored-doc parity: the Ollama-embedded corpus vs this encoder
# measured cosine >= 0.99997 across 51 chunks (long / table / short). Bump ONLY
# with a re-run of that parity gate, or stored docs and new queries drift apart.
EMBED_MODEL_REVISION = os.getenv("EMBED_MODEL_REVISION", "5617a9f61b028005a4858fdac845db406aefb181")
# bge-m3 has a fixed 1024-dim output. This is the EXPECTED dimension, enforced by
# an assertion in the ingest path (see ingest()). Keep any env override in sync
# with the model — do NOT leave a stale 1536 in .env.python.
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
COLLECTION = "FilingChunks"
MANIFEST_COLLECTION = "IngestManifests"
JOB_COLLECTION = "IngestJobs"
METRICS_COLLECTION = "FilingMetrics"

# Batch size for sentence-transformers encode(): texts are embedded in batches,
# not one at a time, so ingest throughput is higher than the old per-call loop.
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "32"))

# ---------------------------------------------------------------------------
# Vector-search recall floor (min_similarity). CALIBRATED — read before changing.
#
# The old default 0.75 was tuned for Gemini's RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY
# asymmetry (doc and query encoded differently, cosines run high). bge-m3 uses the
# SAME encoder on both sides, so its cosines run lower and cluster tighter: at
# 0.75, vector.search() returns ZERO chunks for EVERY query and fails SILENTLY —
# _vector() then emits NO_CONTEXT_MESSAGE with a `none` badge and no error.
#
# This is a RECALL FLOOR / off-corpus guard, NOT a precision filter. On the 20-Q
# calibration set the chunks the generator actually cited had cosines as low as
# 0.554, which OVERLAPS the rank-21..50 noise band (up to 0.580) — no single
# threshold separates signal from noise. Precision comes from top-k ranking and
# the `ticker IN (...)` filter, not from this number. (A foreign company's chunk
# scored 0.588 / rank-2 on a cross-company question — above any viable threshold —
# so the ticker filter, not min_similarity, is what excludes it; lowering this
# does NOT increase contamination.)
#
# Worst observed rank-5 cosine was 0.5143, so 0.45 leaves ~0.06 margin (rank-5
# always survives) and sits below the 0.554 used-chunk floor (no cited chunk is
# cut). Calibrated on a 387-chunk subset; production is ~7026 chunks (18x) with
# unseen questions — hence env-tunable without a redeploy. The data says do NOT
# tighten this without real traffic proving otherwise.
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.45"))

# --- Singletons -------------------------------------------------------------

_store: Optional[DocumentStore] = None
_genai_client: Optional[genai.Client] = None
_embed_model = None  # lazy-loaded sentence-transformers bge-m3 encoder


def get_embed_model():
    """
    Lazily load and cache the in-process bge-m3 encoder.

    Loaded on the FIRST embed (first ingest or first query), NOT at import — so
    the service boots and serves non-RAG endpoints (market data, metrics, price
    history) without paying the ~10s model load. That cost is felt only by the
    first FinChat ask on a cold instance; every embed after that is warm (~0.4s).

    In the deployed image the weights are baked at build time and HF_HUB_OFFLINE=1,
    so this reads from the in-image cache and never touches the network.
    """
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("loading embedding model %s (revision %s) ...", EMBED_MODEL, EMBED_MODEL_REVISION)
        _embed_model = SentenceTransformer(EMBED_MODEL, revision=EMBED_MODEL_REVISION)
        logger.info("embedding model %s loaded", EMBED_MODEL)
    return _embed_model


def get_store() -> DocumentStore:
    """Lazily initialize and return the shared RavenDB DocumentStore."""
    global _store
    if _store is None:
        store = DocumentStore(RAVENDB_URLS, RAVENDB_DATABASE)

        if RAVENDB_CERT_PATH:
            store.certificate_pem_path = RAVENDB_CERT_PATH

        # The RavenDB Python client uses inflect to pluralize class names for
        # collection names.  "FilingMetrics" (already plural in English) becomes
        # "FilingMetricss" — the wrong collection.  Override the convention so
        # the client always maps the FilingMetrics class to the exact string
        # "FilingMetrics".  Must be set BEFORE store.initialize().
        _orig_find = store.conventions.find_collection_name
        def _find_collection_name(cls_type):
            if cls_type.__name__ == "FilingMetrics":
                return METRICS_COLLECTION   # "FilingMetrics" — no extra 's'
            return _orig_find(cls_type)
        store.conventions.find_collection_name = _find_collection_name

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


# --- Document models --------------------------------------------------------

class FilingChunk:
    """A single embedded chunk of an SEC filing."""

    def __init__(
        self,
        Id: Optional[str] = None,
        ticker: str = "",
        form: str = "",
        source: str = "",
        accession_number: str = "",
        filing_date: str = "",
        chunk_index: int = 0,
        text: str = "",
        embedding: Optional[list] = None,
    ):
        self.Id = Id
        self.ticker = ticker
        self.form = form
        self.source = source
        self.accession_number = accession_number
        self.filing_date = filing_date
        self.chunk_index = chunk_index
        self.text = text
        self.embedding = embedding or []


class IngestManifest:
    """
    Written (upserted) to RavenDB only after a full successful ingest.

    Absence of a manifest means the filing was never ingested OR only partially
    ingested (e.g. a 429 mid-batch cut the run short). check_already_indexed()
    treats both cases as needing (re-)ingest.
    """

    def __init__(
        self,
        Id: Optional[str] = None,
        ticker: str = "",
        form: str = "",
        accession_number: str = "",
        filing_date: str = "",
        chunk_count: int = 0,
        completed_at: str = "",
    ):
        self.Id = Id
        self.ticker = ticker
        self.form = form
        self.accession_number = accession_number
        self.filing_date = filing_date
        self.chunk_count = chunk_count
        self.completed_at = completed_at


class IngestJob:
    """
    Persistent record of an embedding ingest job, stored in the IngestJobs
    collection. Survives server restarts — the worker reloads and re-enqueues
    active jobs on startup.

    Status lifecycle:
      queued → indexing → indexed | failed | waiting_for_quota
      waiting_for_quota → (backoff elapsed) → queued → indexing → …
    """

    def __init__(
        self,
        Id: Optional[str] = None,
        job_type: str = "edgar",
        ticker: str = "",
        form: str = "",
        source: str = "",
        accession_number: str = "",
        filing_date: str = "",
        status: str = "queued",
        enqueued_at: str = "",
        updated_at: str = "",
        attempts: int = 0,
        quota_attempts: int = 0,
        first_quota_hit_at: str = "",
        quota_resume_after: str = "",
        last_error: Optional[str] = None,
        chunks: int = 0,
        sections: Optional[dict] = None,
    ):
        self.Id = Id
        self.job_type = job_type
        self.ticker = ticker
        self.form = form
        self.source = source
        self.accession_number = accession_number
        self.filing_date = filing_date
        self.status = status
        self.enqueued_at = enqueued_at
        self.updated_at = updated_at
        self.attempts = attempts
        self.quota_attempts = quota_attempts
        self.first_quota_hit_at = first_quota_hit_at
        self.quota_resume_after = quota_resume_after
        self.last_error = last_error
        self.chunks = chunks
        self.sections = sections if sections is not None else {}


class FilingMetrics:
    """
    Structured XBRL metrics for one indexed filing, persisted to RavenDB.

    Populated by register_filing() in router.py at /extract time and reloaded
    on startup to rebuild the in-memory RDF graph without re-fetching from EDGAR.

    The ``metrics`` dict mirrors the extractor result structure:
      { income_statement: {...}, balance_sheet: {...},
        cash_flow: {...}, computed_ratios: {...} }

    ``metrics_by_year`` must be an __init__ parameter (not just an instance
    attribute) so the RavenDB Python client maps it from the stored JSON on
    deserialization.  All fields that need to survive a round-trip must appear
    in the parameter list.
    """

    def __init__(
        self,
        Id: Optional[str] = None,
        ticker: str = "",
        form: str = "10-K",
        accession_number: str = "",
        filing_date: str = "",
        fiscal_year_end: str = "",
        period_end: str = "",
        sector: str = "Unknown",
        metrics: Optional[dict] = None,
        metrics_by_year: Optional[dict] = None,
    ):
        self.Id = Id
        self.ticker = ticker
        self.form = form
        self.accession_number = accession_number
        self.filing_date = filing_date
        # Four-digit year string derived from the XBRL period-end date, not the
        # filing date.  e.g. "2025" for a Dec-FY company whose 10-K was filed in
        # January 2026.  Empty string means not yet resolved.
        self.fiscal_year_end: str = fiscal_year_end or ""
        # Full ISO date of the most-recent XBRL fiscal period end, e.g.
        # "2025-09-27" for AAPL or "2025-12-31" for META.  Used for
        # cross-company fiscal-year-end disclosure in graph answers.
        self.period_end: str = period_end or ""
        self.sector = sector
        self.metrics = metrics if metrics is not None else {}
        self.metrics_by_year: dict = metrics_by_year if metrics_by_year is not None else {}


# --- Exceptions -------------------------------------------------------------

class DailyQuotaExceededError(Exception):
    """Raised when the Gemini embedding per-day (RPD) quota is exhausted."""


class PerMinuteQuotaError(Exception):
    """Raised when the Gemini embedding per-minute (RPM/TPM) quota is exhausted."""


def is_daily_quota_error(e: Exception) -> bool:
    """True only for per-day (RPD) exhaustion — explicitly NOT per-minute."""
    msg = str(e)
    # Exclude per-minute signals first; some error payloads mention multiple
    # quota dimensions and we must not misfire the midnight-UTC message for a
    # transient per-minute rate limit.
    if "PerMinute" in msg or "per_minute" in msg.lower():
        return False
    return "PerDay" in msg or "EmbedContentRequestsPerDay" in msg


def is_per_minute_quota_error(e: Exception) -> bool:
    """True for per-minute (RPM / TPM) rate-limit responses."""
    msg = str(e)
    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
        return False
    return "PerMinute" in msg or "per_minute" in msg.lower()


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
    Embed a list of texts with bge-m3 via in-process sentence-transformers,
    L2-normalized.

    `task_type` is kept in the signature for backwards compatibility — callers
    still pass RETRIEVAL_DOCUMENT (ingest) and RETRIEVAL_QUERY (search) — but it
    is IGNORED: bge-m3 uses the same encoder for documents and queries, so there
    is no task-type prefix or asymmetry to apply on either side.

    The encoder batches (EMBED_BATCH) rather than one-per-call. Every vector is
    passed through _normalize() for cosine consistency with the stored corpus and
    vector.search(). sentence-transformers already returns unit vectors, so this
    is belt-and-suspenders — and it keeps the EXACT code path that was parity-
    validated (>= 0.99997) against the Ollama-embedded documents already in RavenDB.

    No quota / rate handling: the encoder runs in-process with no per-day or
    per-minute quota. DailyQuotaExceededError / PerMinuteQuotaError are no longer
    raised from here (they remain defined and are still caught upstream in app.py,
    router.py and bulk_ingest.py — they simply never fire now).
    """
    _ = task_type  # intentionally ignored (symmetric encoder); see docstring
    if not texts:
        return []
    model = get_embed_model()
    vecs = model.encode(
        texts,
        batch_size=EMBED_BATCH,
        normalize_embeddings=False,
        show_progress_bar=False,
    )
    out = [_normalize(v) for v in vecs]
    for i, v in enumerate(out):
        if not v:
            raise RuntimeError(
                f"Empty embedding for text #{i} (model={EMBED_MODEL}, "
                f"revision={EMBED_MODEL_REVISION})."
            )
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


def _manifest_id(ticker: str, form: str, accession_number: str) -> str:
    return f"{MANIFEST_COLLECTION}/{ticker.strip().upper()}-{form}-{accession_number}"


def _job_id(key: str) -> str:
    return f"{JOB_COLLECTION}/{key}"


def _metrics_id(ticker: str, form: str, accession_number: str) -> str:
    return f"{METRICS_COLLECTION}/{ticker.strip().upper()}-{form}-{accession_number}"


def save_filing_metrics(
    ticker: str,
    form: str,
    accession_number: str,
    filing_date: str,
    sector: str,
    metrics: dict,
    metrics_by_year: Optional[dict] = None,
    fiscal_year_end: str = "",
    period_end: str = "",
) -> None:
    """
    Upsert structured metrics for one filing to the FilingMetrics collection.

    Called from router.register_filing() at /extract time. Non-fatal — the
    caller must catch and log exceptions so a RavenDB hiccup never aborts an
    extraction that otherwise succeeded.

    ``metrics`` contains the single-year snapshot (most recent fiscal year):
        income_statement, balance_sheet, cash_flow, computed_ratios.

    ``metrics_by_year`` contains per-year income data from XBRL historical rows:
        { "2025": { "income_statement": {...} }, "2024": {...}, ... }
    When present it allows the RDF graph to answer year-over-year comparisons via
    SPARQL without re-fetching from EDGAR on each server restart.
    """
    if not accession_number:
        return

    def _do_store(store, mid: str) -> None:
        with store.open_session() as session:
            doc = FilingMetrics(
                Id=mid,
                ticker=ticker.strip().upper(),
                form=form,
                accession_number=accession_number,
                filing_date=filing_date,
                fiscal_year_end=fiscal_year_end or "",
                period_end=period_end or "",
                sector=sector,
                metrics=metrics,
                metrics_by_year=metrics_by_year or {},
            )
            session.store(doc, mid)
            # Explicitly set the RavenDB collection name so the document lands in
            # "FilingMetrics", not the auto-pluralized "FilingMetricss" that the Python
            # client derives from the class name.
            session.advanced.get_metadata_for(doc)["@collection"] = METRICS_COLLECTION
            session.save_changes()

    try:
        store = get_store()
        mid = _metrics_id(ticker, form, accession_number)
        try:
            _do_store(store, mid)
        except Exception as write_e:
            if "CollectionMismatch" not in str(write_e):
                raise
            # An old doc with this ID exists in the wrong collection (e.g. "FilingMetricss").
            # RavenDB forbids changing a document's collection via update — delete via
            # the HTTP API and recreate in the correct collection.
            import urllib.parse
            import requests as _requests
            base = store.urls[0].rstrip("/")
            db   = store.database
            enc  = urllib.parse.quote(mid, safe="")
            _requests.delete(f"{base}/databases/{db}/docs?id={enc}", timeout=10)
            logger.info("Deleted orphan doc %s from wrong collection — retrying in %s",
                        mid, METRICS_COLLECTION)
            _do_store(store, mid)
        logger.info("Saved FilingMetrics %s (years=%s)", mid,
                    sorted(metrics_by_year or {}, reverse=True))
    except Exception as e:
        logger.warning("Could not save FilingMetrics for %s %s: %s", ticker, form, e)


def load_all_filing_metrics() -> list:
    """
    Load every FilingMetrics document from RavenDB.

    Returns a list of FilingMetrics instances (may be empty if none have been
    persisted yet — happens on the very first boot after the fix is deployed).
    """
    try:
        store = get_store()
        with store.open_session() as session:
            rows = list(
                session.advanced.raw_query(
                    "from FilingMetrics",
                    object_type=FilingMetrics,
                )
            )
        logger.info("load_all_filing_metrics: found %d docs", len(rows))
        return rows
    except Exception as e:
        logger.warning("Could not load FilingMetrics from RavenDB: %s", e)
        return []


def load_filing_metrics(ticker: str, form: str = "10-K"):
    """
    Load the most recent FilingMetrics doc for one ticker+form, or None.

    Pure read — no SEC call, no embedding. Backs GET /metrics/{ticker}'s fast
    path for the tickers already extracted at least once (FilingMetrics is
    written by register_filing() at /extract time, independent of whether the
    embedding half ever completed).
    """
    try:
        store = get_store()
        with store.open_session() as session:
            rows = list(
                session.advanced.raw_query(
                    f"from {METRICS_COLLECTION} "
                    "where ticker = $ticker and form = $form "
                    "order by filing_date desc",
                    object_type=FilingMetrics,
                )
                .add_parameter("ticker", ticker.strip().upper())
                .add_parameter("form", form)
            )
        return rows[0] if rows else None
    except Exception as e:
        logger.warning("Could not load FilingMetrics for %s %s: %s", ticker, form, e)
        return None


def load_all_ingest_manifests() -> list:
    """
    Load every IngestManifest document for the one-time graph migration.

    Returns a list of IngestManifest instances.
    """
    try:
        store = get_store()
        with store.open_session() as session:
            rows = list(
                session.advanced.raw_query(
                    "from IngestManifests",
                    object_type=IngestManifest,
                )
            )
        return rows
    except Exception as e:
        logger.warning("Could not load IngestManifests: %s", e)
        return []


def fix_collection_name_once() -> int:
    """
    One-time migration: move FilingMetrics documents from the auto-pluralized
    collection ('FilingMetricss') to the explicit 'FilingMetrics' collection.

    Root cause: session.store() without setting @collection causes RavenDB to
    derive the collection name from the Python class name, so class 'FilingMetrics'
    → collection 'FilingMetricss'.  The fix is applied going forward in
    save_filing_metrics() via get_metadata_for(doc)["@collection"] = METRICS_COLLECTION.
    This function migrates the 15 existing documents in the wrong collection.

    RavenDB does not allow changing a document's @collection via update — it
    requires delete + recreate.  We use the HTTP JSON API directly so we can
    preserve the exact document content while replacing the @metadata.@collection
    field, without going through the Python ORM (which re-derives the class name).

    Safe to call on every boot: exits immediately once the correct collection has
    documents.  Returns the number of documents migrated (0 on subsequent boots).
    """
    import requests as _requests

    _LEGACY = METRICS_COLLECTION + "s"   # "FilingMetricss"
    try:
        store = get_store()
        base = store.urls[0].rstrip("/")
        db   = store.database

        # If the correct collection already has data the migration has already run.
        with store.open_session() as session:
            already = list(
                session.advanced.raw_query(
                    f"from {METRICS_COLLECTION}",
                    object_type=FilingMetrics,
                )
            )
        if already:
            logger.info(
                "fix_collection_name_once: '%s' already has %d docs — skipping",
                METRICS_COLLECTION, len(already),
            )
            return 0

        # Fetch raw JSON from the legacy collection (up to 100 docs; we have 15).
        resp = _requests.get(
            f"{base}/databases/{db}/queries",
            params={"query": f"from {_LEGACY}", "pageSize": 100},
            timeout=15,
        )
        resp.raise_for_status()
        raw_docs = resp.json().get("Results", [])

        if not raw_docs:
            logger.info("fix_collection_name_once: '%s' is empty — nothing to migrate", _LEGACY)
            return 0

        migrated = 0
        for raw_doc in raw_docs:
            old_meta = raw_doc.get("@metadata", {})
            doc_id   = old_meta.get("@id", "")
            if not doc_id:
                continue

            # Step 1: delete from old collection.
            _requests.delete(
                f"{base}/databases/{db}/docs",
                params={"id": doc_id},
                timeout=10,
            ).raise_for_status()

            # Step 2: reconstruct with correct @collection metadata; strip
            # server-managed fields that must not be sent on PUT.
            new_meta = {
                k: v for k, v in old_meta.items()
                if k not in ("@change-vector", "@last-modified", "@flags", "@attachments")
            }
            new_meta["@collection"] = METRICS_COLLECTION
            new_doc = {k: v for k, v in raw_doc.items() if k != "@metadata"}
            new_doc["@metadata"] = new_meta

            _requests.put(
                f"{base}/databases/{db}/docs",
                params={"id": doc_id},
                json=new_doc,
                headers={"Content-Type": "application/json"},
                timeout=10,
            ).raise_for_status()

            migrated += 1

        logger.info(
            "fix_collection_name_once: migrated %d docs '%s' → '%s'",
            migrated, _LEGACY, METRICS_COLLECTION,
        )
        return migrated
    except Exception as e:
        logger.warning("fix_collection_name_once failed (non-fatal): %s", e)
        return 0


# --- Deduplication ----------------------------------------------------------

def _write_manifest(
    ticker: str,
    form: str,
    accession_number: str,
    filing_date: str,
    chunk_count: int,
) -> None:
    """Upsert the completion manifest. Called only after save_changes() succeeds."""
    if not accession_number:
        return
    try:
        store = get_store()
        mid = _manifest_id(ticker, form, accession_number)
        with store.open_session() as session:
            manifest = IngestManifest(
                Id=mid,
                ticker=ticker.strip().upper(),
                form=form,
                accession_number=accession_number,
                filing_date=filing_date,
                chunk_count=chunk_count,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            session.store(manifest, mid)
            session.save_changes()
        logger.info("Wrote ingest manifest %s (%d chunks)", mid, chunk_count)
    except Exception as e:
        # Non-fatal: ingest still succeeded; next run will use the fallback path.
        logger.warning("Could not write ingest manifest for %s: %s", accession_number, e)


def check_already_indexed(
    ticker: str,
    form: str,
    accession_number: str,
    source_url: str = "",
) -> tuple[bool, int]:
    """
    Return (is_fully_indexed, chunk_count).

    Pass 1 — manifest lookup (O(1), fast path):
      If IngestManifests/{ticker}-{form}-{accession_number} exists with chunk_count > 0,
      the filing is fully indexed.

    Pass 2 — chunk count fallback (migration path):
      For filings ingested before manifest support was added, count chunks
      stored with matching ticker+form+source. If > 0 chunks found, write a
      retroactive manifest so future calls use the fast path.

    Returns (False, 0) if RavenDB is unreachable; caller proceeds with ingest.
    """
    # Fast path via manifest
    if accession_number:
        try:
            store = get_store()
            with store.open_session() as session:
                manifest = session.load(
                    _manifest_id(ticker, form, accession_number),
                    object_type=IngestManifest,
                )
                if manifest and manifest.chunk_count > 0:
                    logger.debug(
                        "Manifest hit for %s %s %s: %d chunks",
                        ticker, form, accession_number, manifest.chunk_count,
                    )
                    return True, manifest.chunk_count
        except Exception as e:
            logger.warning("Manifest lookup failed for %s: %s — will proceed with ingest", accession_number, e)
            return False, 0

    # Fallback: count chunks by ticker+form+source (covers pre-manifest ingests).
    # Load only chunk_index to avoid pulling full text + embedding vectors.
    if source_url:
        try:
            store = get_store()
            with store.open_session() as session:
                rows = list(
                    session.advanced.raw_query(
                        "from FilingChunks "
                        "where ticker = $t and form = $f and source = $s "
                        "select chunk_index",
                        object_type=dict,
                    )
                    .add_parameter("t", ticker.strip().upper())
                    .add_parameter("f", form)
                    .add_parameter("s", source_url)
                )
            count = len(rows)
            if count > 0:
                logger.info(
                    "Migration path: found %d existing chunks for %s %s — writing retroactive manifest",
                    count, ticker, form,
                )
                _write_manifest(ticker, form, accession_number, "", count)
                return True, count
        except Exception as e:
            logger.warning("Chunk-count fallback failed for %s %s: %s", ticker, form, e)

    return False, 0


# --- Job persistence --------------------------------------------------------

def upsert_job(
    key: str,
    job_type: str,
    ticker: str,
    form: str,
    source: str,
    accession_number: str,
    filing_date: str,
    sections: dict,
) -> None:
    """
    Create or reset an IngestJob in RavenDB.

    If the job already exists, resets it to queued and updates sections (so a
    retry re-runs with current data). Quota state (quota_attempts,
    first_quota_hit_at) is preserved on existing jobs so the 72h deadline
    applies across manual retries.
    """
    try:
        store = get_store()
        jid = _job_id(key)
        now = datetime.now(timezone.utc).isoformat()
        with store.open_session() as session:
            existing = session.load(jid, object_type=IngestJob)
            if existing is None:
                job = IngestJob(
                    Id=jid,
                    job_type=job_type,
                    ticker=ticker.strip().upper(),
                    form=form,
                    source=source,
                    accession_number=accession_number,
                    filing_date=filing_date,
                    status="queued",
                    enqueued_at=now,
                    updated_at=now,
                    sections=sections,
                )
                session.store(job, jid)
            else:
                existing.status = "queued"
                existing.updated_at = now
                existing.sections = sections
                existing.last_error = None
            session.save_changes()
        logger.debug("Upserted IngestJob %s (type=%s)", jid, job_type)
    except Exception as e:
        logger.warning("Could not upsert job %s: %s", key, e)


def update_job_status(
    key: str,
    status: str,
    chunks: int = 0,
    error: Optional[str] = None,
    quota_resume_after: str = "",
    quota_attempt: int = 0,
    first_quota_hit_at: str = "",
) -> None:
    """Persist a job status transition to RavenDB. Non-fatal if RavenDB is unavailable."""
    try:
        store = get_store()
        jid = _job_id(key)
        now = datetime.now(timezone.utc).isoformat()
        with store.open_session() as session:
            job = session.load(jid, object_type=IngestJob)
            if job is None:
                logger.warning("update_job_status: job %s not found in RavenDB", jid)
                return
            job.status = status
            job.updated_at = now
            job.chunks = chunks
            job.last_error = error
            if status == "indexing":
                job.attempts = (job.attempts or 0) + 1
            if quota_resume_after:
                job.quota_resume_after = quota_resume_after
            if quota_attempt:
                job.quota_attempts = quota_attempt
            if first_quota_hit_at:
                job.first_quota_hit_at = first_quota_hit_at
            session.save_changes()
    except Exception as e:
        logger.warning("Could not update job status for %s: %s", key, e)


def load_active_jobs() -> list[IngestJob]:
    """
    Load all non-indexed jobs from RavenDB for startup recovery.

    Includes queued, indexing, waiting_for_quota, and failed so that:
      - queued/indexing are re-enqueued (may have been interrupted by a restart)
      - waiting_for_quota have their state restored for _check_waiting_jobs
      - failed have their payload restored so the retry endpoint works
    """
    try:
        store = get_store()
        with store.open_session() as session:
            rows = list(
                session.advanced.raw_query(
                    "from IngestJobs "
                    "where status in ($s1, $s2, $s3, $s4)",
                    object_type=IngestJob,
                )
                .add_parameter("s1", "queued")
                .add_parameter("s2", "indexing")
                .add_parameter("s3", "waiting_for_quota")
                .add_parameter("s4", "failed")
            )
        logger.info("load_active_jobs: found %d non-indexed jobs", len(rows))
        return rows
    except Exception as e:
        logger.warning("Could not load active jobs from RavenDB: %s", e)
        return []


# --- Ingest -----------------------------------------------------------------

def ingest(
    ticker: str,
    form: str,
    text: str,
    source: str,
    accession_number: str = "",
    filing_date: str = "",
) -> int:
    """
    Chunk -> embed (RETRIEVAL_DOCUMENT) -> upsert into RavenDB.
    Returns the number of chunks stored.

    Re-ingesting the same (ticker, form, source) overwrites chunks by
    deterministic ID — no duplicates accumulate.

    On full success, writes an IngestManifest so check_already_indexed()
    can skip future re-ingests of the same filing (same accession_number).
    """
    ticker = ticker.strip().upper()
    chunks = chunk_text(text)
    if not chunks:
        logger.warning("No chunks produced for %s %s (%s)", ticker, form, source)
        return 0

    logger.info("Embedding %d chunks for %s %s (model=%s, batch=%d)…",
                len(chunks), ticker, form, EMBED_MODEL, EMBED_BATCH)
    vectors = embed_texts(chunks, task_type="RETRIEVAL_DOCUMENT")

    # Dimension guard — crash LOUDLY here rather than fail silently at query time.
    # vector.search() returns nothing on a dim mismatch with no error, so if
    # EMBED_DIM and the real model ever disagree (bad env, model swap, unexpected
    # encoder output), we must stop BEFORE writing to RavenDB — not discover it as
    # mystery empty results days later. Cheap insurance against the exact failure
    # mode this migration is navigating around.
    for idx, vec in enumerate(vectors):
        if len(vec) != EMBED_DIM:
            raise ValueError(
                f"Embedding dimension mismatch for {ticker} {form} chunk #{idx}: "
                f"got {len(vec)}, expected EMBED_DIM={EMBED_DIM} "
                f"(model={EMBED_MODEL}). Refusing to store; check the model and "
                f"the EMBED_DIM env agree."
            )

    store = get_store()
    with store.open_session() as session:
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
            doc_id = _chunk_id(ticker, form, source, idx)
            doc = FilingChunk(
                Id=doc_id,
                ticker=ticker,
                form=form,
                source=source,
                accession_number=accession_number,
                filing_date=filing_date,
                chunk_index=idx,
                text=chunk,
                embedding=vec,
            )
            session.store(doc, doc_id)
        session.save_changes()

    # Write completion manifest only after all chunks are durably stored.
    # A partial ingest (exception before save_changes) leaves no manifest,
    # so check_already_indexed correctly treats it as incomplete.
    _write_manifest(ticker, form, accession_number, filing_date, len(chunks))

    logger.info("Ingested %d chunks for %s %s (%s)", len(chunks), ticker, form, source)
    return len(chunks)


# --- Search -----------------------------------------------------------------

def search(
    query: str,
    k: int = 5,
    ticker: Optional[str] = None,
    tickers: Optional[list[str]] = None,
    form: Optional[str] = None,
    min_similarity: float = MIN_SIMILARITY,
    candidates: int = 32,
) -> list[FilingChunk]:
    """
    Embed the query (RETRIEVAL_QUERY) and run a dynamic vector search.
    ticker/form act as regular filters combined with the vector search.

    `tickers` (a list) restricts to `ticker IN (...)` — used by route_question
    to scope a vector search to the companies the question actually names, so an
    unscoped question about a zero-chunk company can't silently retrieve another
    company's filing text. When both are given, `tickers` wins. When neither is
    given, the search is global (a legitimate corpus-wide question).
    """
    qvec = embed_texts([query], task_type="RETRIEVAL_QUERY")[0]

    # Normalize the ticker scope: prefer the multi-ticker list, fall back to the
    # single ticker. Empty/whitespace entries are dropped.
    scope = [t.strip().upper() for t in (tickers or []) if t and t.strip()]
    if not scope and ticker and ticker.strip():
        scope = [ticker.strip().upper()]

    filters = []
    if scope:
        placeholders = ", ".join(f"$tk{i}" for i in range(len(scope)))
        filters.append(f"ticker in ({placeholders})")
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
        for i, t in enumerate(scope):
            q = q.add_parameter(f"tk{i}", t)
        if form:
            q = q.add_parameter("form", form)
        results = list(q)

    # Silent-truncation breadcrumb. A GLOBAL (unfiltered) query returning fewer
    # than k chunks almost always means min_similarity is too high for the
    # current embedding model, not that the corpus is thin. A ticker/form-filtered
    # query legitimately returns fewer, so we only warn when unfiltered. Not an
    # error — just a log trail so a bad threshold shows up here instead of as
    # quietly thinner (or empty) answers with a `none` badge.
    if not scope and not form and len(results) < k:
        logger.warning(
            "search() returned %d/%d chunks for an unfiltered query "
            "(min_similarity=%.3f) — threshold may be too high for %r",
            len(results), k, min_similarity, query[:80],
        )
    return results


# --- CLI --------------------------------------------------------------------

def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="FinSight embeddings (RavenDB)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Embed and store a filing")
    p_ingest.add_argument("--ticker", required=True)
    p_ingest.add_argument("--form", required=True, choices=["10-K", "10-Q"])
    p_ingest.add_argument("--source", required=True, help="Filing identifier / source URL")
    p_ingest.add_argument("--accession", default="", help="Accession number for dedup manifest")
    p_ingest.add_argument("--filing-date", default="", help="Filing date (YYYY-MM-DD)")
    p_ingest.add_argument("--file", required=True, help="Path to extracted filing text")

    p_search = sub.add_parser("search", help="Semantic search over stored filings")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--k", type=int, default=5)
    p_search.add_argument("--ticker", default=None)
    p_search.add_argument("--form", default=None, choices=["10-K", "10-Q", None])
    p_search.add_argument("--min-similarity", type=float, default=MIN_SIMILARITY)

    args = parser.parse_args()

    if args.command == "ingest":
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
        n = ingest(
            args.ticker, args.form, text, args.source,
            accession_number=args.accession,
            filing_date=args.filing_date,
        )
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
