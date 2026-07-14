"""
FastAPI service for FinSight (backend/data_extract/app.py).

Surfaces:
  - GET  /extract/{ticker}          -> extraction pipeline (ticker -> clean structured data)
  - GET  /ingest-status/{ticker}    -> poll ingest progress for an EDGAR filing
  - POST /ingest-retry              -> re-queue a previously failed EDGAR ingest
  - POST /upload                    -> upload a PDF or TXT file for embedding
  - GET  /upload-status/{doc_id}   -> poll ingest progress for an uploaded file
  - POST /upload-retry              -> re-queue a previously failed upload ingest
  - GET  /market/{ticker}           -> market snapshot + price history (yfinance)
  - GET  /search?q=<text>           -> company name/ticker search over the SEC registry
  - POST /api/chat                  -> RAG chat (RavenDB retrieval + Gemini generation)

Run from the repo root:
    uvicorn backend.data_extract.app:app --reload --port 8000

Ingest queue
------------
A single daemon worker drains the queue one filing at a time to stay within
the Gemini free-tier RPM limit. Status lifecycle:

  queued → indexing → indexed | failed | waiting_for_quota

Already-indexed check
---------------------
check_already_indexed() is called SYNCHRONOUSLY inside /extract and /upload
BEFORE touching _ingest_status, so a re-added filing that is already in
RavenDB gets status "indexed" immediately in the response — no "queued" flash,
no embedding calls, no quota consumed.

The accession_number returned by run() (the extractor) is used for the O(1)
manifest fast-path. A source_url fallback handles filings ingested before
manifest support and cases where accession is temporarily unavailable.

A genuinely newer filing (different accession AND different source URL) is
NOT skipped — both fast-path and fallback would miss it, triggering normal
embedding.

Job persistence
---------------
Jobs are persisted to a RavenDB IngestJobs collection so they survive server
restarts. On startup, the lifespan handler reloads active jobs and re-enqueues
any that were interrupted mid-ingest.

Daily quota handling: when embed_texts() raises DailyQuotaExceededError (Gemini
PerDay limit hit), the job transitions to waiting_for_quota with an exponential
backoff: 30 min, 60 min, 120 min, up to 360 min (6 h). The worker wakes every
30 minutes to re-enqueue jobs whose backoff has elapsed. After 72 hours total
from the first quota hit, the job is marked failed.
"""

import hashlib
import io
import logging
import os
import queue
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.python")
except ImportError:
    pass

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .extractor import run
from .sec_client import SecRateLimitError
from .rag import router as chat_router
from .market import router as market_router
from .search import router as search_router
from .compare_metrics import router as compare_metrics_router
from .indexed import router as indexed_router
from .filing_metrics import router as filing_metrics_router
from .prediction import router as prediction_router
from .embeddings import DailyQuotaExceededError, PerMinuteQuotaError

# Wire root logging to stdout at import time so app logger.info() lines (worker
# start, "Enqueued", "Startup recovery", "chunks stored") reach Cloud Logging.
# Without this, Python's last-resort handler emits WARNING+ only and every INFO
# line from this module is silently dropped — making the ingest worker invisible.
# force=True so we win even if a dependency called basicConfig first.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", "50"))

# Maximum hours to wait before declaring a daily-quota job permanently failed.
QUOTA_DEADLINE_HOURS = int(os.getenv("QUOTA_DEADLINE_HOURS", "72"))

# Hard wall-clock cap on a single ingest job. The worker is single-threaded, so a
# job that hangs (e.g. a wedged embed) would block every job behind it forever —
# head-of-line blocking. If a job exceeds this, we mark it failed and move on so
# the queue keeps draining. Generous enough that a normal large 10-K (a few
# hundred chunks, single-thread CPU encode) finishes well within it.
INGEST_JOB_TIMEOUT = int(os.getenv("INGEST_JOB_TIMEOUT", "900"))  # 15 min


# ---------------------------------------------------------------------------
# Shared in-memory state
# ---------------------------------------------------------------------------
#
# _ingest_status   keyed by status_key → {status, chunks, error, ...quota fields}
# _ingest_payloads keyed the same      → {ticker, form, sections, source,
#                                          accession_number, filing_date}
#
# EDGAR filings use key = "{TICKER}-{form}".
# Uploaded files   use key = doc_id (opaque 12-char sha1 of filename).

_ingest_queue: queue.Queue = queue.Queue()
_ingest_status: dict[str, dict] = {}
_ingest_payloads: dict[str, dict] = {}
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


# ---------------------------------------------------------------------------
# Job status helpers
# ---------------------------------------------------------------------------

def _set_job_status(
    key: str,
    status: str,
    chunks: int = 0,
    error: Optional[str] = None,
    quota_resume_after: str = "",
    quota_attempt: int = 0,
    first_quota_hit_at: str = "",
) -> None:
    """Update in-memory status dict AND persist to RavenDB (non-fatal on DB error)."""
    entry: dict = {"status": status, "chunks": chunks, "error": error}
    if quota_resume_after:
        entry["quota_resume_after"] = quota_resume_after
    if quota_attempt:
        entry["quota_attempts"] = quota_attempt
    if first_quota_hit_at:
        entry["first_quota_hit_at"] = first_quota_hit_at
    with _status_lock:
        _ingest_status[key] = entry
    try:
        from .embeddings import update_job_status
        update_job_status(
            key, status,
            chunks=chunks,
            error=error,
            quota_resume_after=quota_resume_after,
            quota_attempt=quota_attempt,
            first_quota_hit_at=first_quota_hit_at,
        )
    except Exception as e:
        logger.warning("Could not persist job status for %s: %s", key, e)


# ---------------------------------------------------------------------------
# Inline already-indexed check
# ---------------------------------------------------------------------------

def _check_already_indexed_inline(
    ticker: str,
    form: str,
    accession_number: str,
    source: str,
) -> tuple[bool, int]:
    """
    Run check_already_indexed() and absorb all exceptions.

    Returns (False, 0) on any error so callers always proceed safely.
    The accession_number here is the one returned by run() / derived from the
    filename, so it is always fully resolved before this is called.

    Pass 1 — manifest key:  IngestManifests/{TICKER}-{form}-{accession_number}
    Pass 2 — source_url fallback for filings ingested before manifest support.
             A genuinely newer filing (different accession AND different URL)
             produces (False, 0) from both passes → proceeds to embed normally.
    """
    try:
        from .embeddings import check_already_indexed
        return check_already_indexed(ticker, form, accession_number, source_url=source)
    except Exception as e:
        logger.warning(
            "Inline already-indexed check failed for %s %s — will queue: %s",
            ticker, form, e,
        )
        return False, 0


# ---------------------------------------------------------------------------
# Core ingest logic (runs in the worker thread)
# ---------------------------------------------------------------------------

def _run_ingest(
    ticker: str,
    form: str,
    sections: dict,
    source: str,
    key: str,
    accession_number: str = "",
    filing_date: str = "",
) -> None:
    """
    Belt-and-suspenders check, then embed and store.

    A second already-indexed check here guards against the edge case where the
    inline check was unavailable (RavenDB down at request time) but RavenDB
    recovered by the time the worker runs. Also handles retried jobs.

    DailyQuotaExceededError → transitions job to waiting_for_quota with
    exponential backoff. Any other exception → failed.
    """
    try:
        from .embeddings import ingest, check_already_indexed

        is_indexed, n_existing = check_already_indexed(
            ticker, form, accession_number, source_url=source,
        )
        if is_indexed:
            logger.info(
                "Worker: already indexed %s %s acc=%s (%d chunks)",
                ticker, form, accession_number or "n/a", n_existing,
            )
            _set_job_status(key, "indexed", chunks=n_existing)
            return

        text = _build_ingest_text(sections)
        if not text.strip():
            _set_job_status(
                key, "failed",
                error="No section text extracted to embed",
            )
            return

        n = ingest(ticker, form, text, source,
                   accession_number=accession_number, filing_date=filing_date)
        _set_job_status(key, "indexed", chunks=n)
        logger.info("Ingest complete: %s %s -> %d chunks stored", ticker, form, n)

    except Exception as e:
        is_daily   = isinstance(e, DailyQuotaExceededError)
        is_per_min = isinstance(e, PerMinuteQuotaError)

        if is_per_min:
            # Per-minute rate limit — retry after a short fixed backoff (~90s).
            resume_after = (
                datetime.now(timezone.utc) + timedelta(seconds=90)
            ).isoformat()
            logger.warning(
                "Per-minute quota hit for %s %s — will retry after %s",
                ticker, form, resume_after,
            )
            _set_job_status(
                key, "waiting_for_quota",
                error=str(e),
                quota_resume_after=resume_after,
                quota_attempt=1,
                first_quota_hit_at=datetime.now(timezone.utc).isoformat(),
            )
        elif is_daily:
            with _status_lock:
                old = _ingest_status.get(key, {})
                quota_attempts = old.get("quota_attempts", 0) + 1
                first_hit = old.get("first_quota_hit_at") or datetime.now(timezone.utc).isoformat()

            first_hit_dt = datetime.fromisoformat(first_hit)
            hours_elapsed = (datetime.now(timezone.utc) - first_hit_dt).total_seconds() / 3600
            if hours_elapsed > QUOTA_DEADLINE_HOURS:
                logger.error(
                    "Daily quota exhausted for over %dh on %s — marking failed",
                    QUOTA_DEADLINE_HOURS, key,
                )
                _set_job_status(
                    key, "failed",
                    error=f"Daily quota exhausted for over {QUOTA_DEADLINE_HOURS} hours: {e}",
                )
                return

            retry_minutes = min(30 * (2 ** (quota_attempts - 1)), 360)
            resume_after = (
                datetime.now(timezone.utc) + timedelta(minutes=retry_minutes)
            ).isoformat()
            logger.warning(
                "Daily quota hit for %s (attempt %d), retrying in %d min at %s",
                key, quota_attempts, retry_minutes, resume_after,
            )
            _set_job_status(
                key, "waiting_for_quota",
                error=str(e),
                quota_resume_after=resume_after,
                quota_attempt=quota_attempts,
                first_quota_hit_at=first_hit,
            )
        else:
            logger.exception("Ingest failed for %s %s: %s", ticker, form, e)
            _set_job_status(key, "failed", error=str(e))


# ---------------------------------------------------------------------------
# Quota-recovery check (called by worker at top of each loop iteration)
# ---------------------------------------------------------------------------

def _check_waiting_jobs() -> None:
    """Re-enqueue any waiting_for_quota jobs whose backoff period has elapsed."""
    now = datetime.now(timezone.utc)
    with _status_lock:
        waiting = [(k, dict(v)) for k, v in _ingest_status.items()
                   if v.get("status") == "waiting_for_quota"]

    for key, info in waiting:
        resume_str = info.get("quota_resume_after", "")
        if not resume_str:
            continue
        try:
            if now < datetime.fromisoformat(resume_str):
                continue

            first_hit = info.get("first_quota_hit_at", "")
            if first_hit:
                hours_elapsed = (now - datetime.fromisoformat(first_hit)).total_seconds() / 3600
                if hours_elapsed > QUOTA_DEADLINE_HOURS:
                    logger.error("72h quota deadline passed for %s — marking failed", key)
                    _set_job_status(
                        key, "failed",
                        error=f"Daily quota exhausted for over {QUOTA_DEADLINE_HOURS} hours",
                    )
                    continue

            payload = _ingest_payloads.get(key)
            if not payload:
                logger.warning("No payload for waiting job %s — cannot re-enqueue", key)
                continue

            with _status_lock:
                _ingest_status[key]["status"] = "queued"

            logger.info("Quota backoff elapsed for %s — re-enqueuing", key)
            _ingest_queue.put((
                payload["ticker"], payload["form"],
                payload["sections"], payload["source"], key,
                payload.get("accession_number", ""), payload.get("filing_date", ""),
            ))
        except Exception as exc:
            logger.warning("Error in _check_waiting_jobs for %s: %s", key, exc)


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

def _queue_worker() -> None:
    """
    Daemon thread: drain one item at a time.

    Uses a 30-minute timeout so _check_waiting_jobs() runs at least every
    30 minutes even when the queue is idle, recovering quota-waiting jobs
    without requiring new submissions.
    """
    while True:
        _check_waiting_jobs()
        try:
            item = _ingest_queue.get(timeout=1800)  # 30-min wakeup for quota recovery
        except queue.Empty:
            continue

        ticker, form, sections, source, key, accession_number, filing_date = item
        logger.info(
            "Queue worker: starting %s %s acc=%s (depth after: %d)",
            ticker, form, accession_number or "n/a", _ingest_queue.qsize(),
        )
        _set_job_status(key, "indexing")
        try:
            # Run the job in a helper thread and join with a timeout so a single
            # hung job (wedged embed) can't block the queue behind it. _run_ingest
            # sets its own terminal status; we only override on timeout.
            job_thread = threading.Thread(
                target=_run_ingest,
                args=(ticker, form, sections, source, key, accession_number, filing_date),
                daemon=True,
                name=f"ingest-{key}",
            )
            job_thread.start()
            job_thread.join(INGEST_JOB_TIMEOUT)
            if job_thread.is_alive():
                logger.error(
                    "Ingest for %s %s exceeded %ds — marking failed and moving on "
                    "(job thread left running)",
                    ticker, form, INGEST_JOB_TIMEOUT,
                )
                _set_job_status(
                    key, "failed",
                    error=f"Ingest exceeded {INGEST_JOB_TIMEOUT}s timeout "
                          f"(possible embed wedge)",
                )
        finally:
            _ingest_queue.task_done()


_worker = threading.Thread(target=_queue_worker, daemon=True, name="ingest-worker")
_worker.start()


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------

def _resume_pending_jobs() -> None:
    """
    On startup: reload active IngestJobs from RavenDB and restore in-memory state.

    - queued / indexing (interrupted by restart): re-enqueue immediately.
    - waiting_for_quota: restore status dict so _check_waiting_jobs picks them up.
    - failed: restore payload so the retry endpoint works.
    """
    try:
        from .embeddings import load_active_jobs
        jobs = load_active_jobs()
    except Exception as e:
        logger.warning("Startup recovery skipped (could not load jobs): %s", e)
        return

    if not jobs:
        logger.info("Startup: no active jobs to recover")
        return

    recovered = 0
    for job in jobs:
        raw_id = job.Id or ""
        key = raw_id.split("/", 1)[-1] if "/" in raw_id else raw_id
        if not key:
            continue

        sections = job.sections or {}

        with _status_lock:
            _ingest_payloads[key] = {
                "ticker": job.ticker or "",
                "form": job.form or "",
                "sections": sections,
                "source": job.source or "",
                "accession_number": job.accession_number or "",
                "filing_date": job.filing_date or "",
            }

        if job.status == "waiting_for_quota":
            with _status_lock:
                _ingest_status[key] = {
                    "status": "waiting_for_quota",
                    "chunks": job.chunks or 0,
                    "error": job.last_error,
                    "quota_attempts": job.quota_attempts or 0,
                    "first_quota_hit_at": job.first_quota_hit_at or "",
                    "quota_resume_after": job.quota_resume_after or "",
                }
            logger.info("Startup recovery: restored waiting_for_quota job %s", key)

        elif job.status == "failed":
            with _status_lock:
                _ingest_status[key] = {
                    "status": "failed",
                    "chunks": job.chunks or 0,
                    "error": job.last_error,
                }
            logger.debug("Startup recovery: restored failed job %s", key)

        else:
            # queued or indexing (interrupted mid-run) — re-enqueue.
            with _status_lock:
                _ingest_status[key] = {"status": "queued", "chunks": 0, "error": None}
            _ingest_queue.put((
                job.ticker or "", job.form or "",
                sections, job.source or "", key,
                job.accession_number or "", job.filing_date or "",
            ))
            logger.info(
                "Startup recovery: re-enqueued %s %s", job.ticker, job.form,
            )

        recovered += 1

    logger.info("Startup: recovered %d active jobs from RavenDB", recovered)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    _resume_pending_jobs()
    # Step 1: one-time collection-name fix (idempotent, exits fast after first run).
    # Moves existing FilingMetrics docs from the auto-pluralized 'FilingMetricss'
    # collection to the explicit 'FilingMetrics' collection so load_all_filing_metrics
    # can find them.  Must run BEFORE rebuild_graph_from_ravendb.
    try:
        from .embeddings import fix_collection_name_once
        fix_collection_name_once()
    except Exception as e:
        logger.warning("Collection name fix failed (non-fatal): %s", e)
    # Step 2: rebuild the in-memory RDF graph from persisted FilingMetrics.
    # After the collection-name fix above this will find all 15 documents and
    # populate the graph without triggering a full EDGAR re-migration.
    try:
        from ..graph.router import rebuild_graph_from_ravendb
        rebuild_graph_from_ravendb()
    except Exception as e:
        logger.warning("Could not rebuild graph on startup: %s", e)
    yield


app = FastAPI(title="FinSight Service", lifespan=_lifespan)

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
app.include_router(indexed_router)
app.include_router(filing_metrics_router)
app.include_router(prediction_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# EDGAR extract + enqueue
# ---------------------------------------------------------------------------

@app.get("/extract/{ticker}")
def extract(
    ticker: str,
    form: Literal["10-K"] = "10-K",
) -> dict:
    """
    Run the full extraction pipeline and return structured JSON immediately.

    Already-indexed check:
      check_already_indexed() runs synchronously here, BEFORE setting any
      queue status. The accession_number from run() is used for the O(1)
      manifest fast-path, with a source_url fallback for pre-manifest ingests.

      If the filing is already fully indexed: returns {status: "indexed"}
      immediately — no queue entry, no embedding calls, no quota consumed.

      If the filing is genuinely new/changed (different accession AND different
      URL): the check returns (False, 0) from both passes, the job is queued
      normally, and embedding proceeds.

    Poll GET /ingest-status/{ticker}?form=<form> to track queue progress.
    """
    ticker = ticker.upper()
    key = _ingest_key(ticker, form)

    try:
        result = run(ticker, form)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SecRateLimitError as e:
        # SEC EDGAR throttled us even after ret/backoff. This is transient, not a
        # bug on our side — surface a 503 with a clear, retryable message (and a
        # Retry-After hint) so the UI can say "try again shortly" rather than a
        # generic 502.
        logger.warning("SEC rate-limited extract for %s %s: %s", ticker, form, e)
        raise HTTPException(
            status_code=503,
            detail=(
                "SEC EDGAR is rate-limiting filing downloads right now "
                "(429 Too Many Requests). This is temporary — please retry in a minute."
            ),
            headers={"Retry-After": "30"},
        )
    except Exception as e:
        logger.exception("Extraction failed for %s %s", ticker, form)
        raise HTTPException(status_code=502, detail=f"Extraction failed: {e}")

    # Populate the in-memory RDF graph with structured metrics (non-fatal).
    try:
        from ..graph.router import register_filing
        register_filing(result)
    except Exception as e:
        logger.warning("Could not register %s in graph: %s", ticker, e)

    sections = result.get("sections", {})
    source = result.get("source_url", f"{ticker}/{form}")
    accession_number = result.get("accession_number", "")
    filing_date = result.get("filing_date", "")

    # Store payload unconditionally — needed for retry endpoint and for
    # reload of sections at startup if we do end up queuing.
    with _status_lock:
        _ingest_payloads[key] = {
            "ticker": ticker, "form": form,
            "sections": sections, "source": source,
            "accession_number": accession_number, "filing_date": filing_date,
        }

    # Inline already-indexed check — accession_number is fully resolved here.
    is_indexed, n_existing = _check_already_indexed_inline(
        ticker, form, accession_number, source,
    )

    if is_indexed:
        logger.info(
            "Already indexed %s %s acc=%s (%d chunks) — instant indexed, skipping queue",
            ticker, form, accession_number or "n/a", n_existing,
        )
        with _status_lock:
            _ingest_status[key] = {"status": "indexed", "chunks": n_existing, "error": None}
        # Persist so the job shows as indexed in RavenDB (non-fatal if it fails).
        try:
            from .embeddings import upsert_job, update_job_status
            upsert_job(key, "edgar", ticker, form, source, accession_number, filing_date, {})
            update_job_status(key, "indexed", chunks=n_existing)
        except Exception as e:
            logger.warning("Could not persist indexed state for %s: %s", key, e)
    else:
        with _status_lock:
            _ingest_status[key] = {"status": "queued", "chunks": 0, "error": None}
        try:
            from .embeddings import upsert_job
            upsert_job(
                key, "edgar", ticker, form, source, accession_number, filing_date, sections,
            )
        except Exception as e:
            logger.warning("Could not upsert job for %s %s: %s", ticker, form, e)
        _ingest_queue.put((ticker, form, sections, source, key, accession_number, filing_date))
        logger.info(
            "Enqueued %s %s acc=%s (depth: %d)",
            ticker, form, accession_number or "n/a", _ingest_queue.qsize(),
        )

    return result


class IngestStatusResponse(BaseModel):
    status: Literal["queued", "indexing", "indexed", "failed", "unknown", "waiting_for_quota"]
    chunks: int
    error: Optional[str] = None


# Statuses a persisted IngestJob can legitimately carry; guards the response
# model against an unexpected value read from RavenDB (which would 500 on
# validation). Excludes "unknown", which is only ever synthesized here.
_INGEST_STATUS_VALUES = {
    "queued", "indexing", "indexed", "failed", "waiting_for_quota",
}


@app.get("/ingest-status/{ticker}", response_model=IngestStatusResponse)
def ingest_status(
    ticker: str,
    form: Literal["10-K"] = "10-K",
) -> IngestStatusResponse:
    """
    Returns current ingest status for a (ticker, form) pair.
    - "queued":           waiting in the background queue
    - "indexing":         actively embedding
    - "indexed":          done; `chunks` = count stored
    - "failed":           embedding or RavenDB write failed; `error` has details
    - "waiting_for_quota": daily Gemini quota hit; will auto-retry on a schedule
    - "unknown":          no ingest has been triggered (or server was restarted)

    Read authoritatively from RavenDB, NOT the per-process in-memory dict. With
    more than one instance, the in-memory status reflects only the requests THIS
    instance handled, so it routinely disagreed with /indexed (e.g. a stale
    "failed" from a timed-out attempt on one instance while another instance had
    finished and written the manifest). Resolution order:
      1. Manifest present (the /indexed truth) -> "indexed" — this wins over any
         job status, so /ingest-status and /indexed can never disagree.
      2. Else the shared IngestJob doc — the live lifecycle every instance writes.
      3. Else the in-memory dict — covers the brief window before the first
         RavenDB persist; else "unknown".
    """
    key = _ingest_key(ticker, form)
    tkr = ticker.strip().upper()

    # 1. Manifest = definitive "indexed" (same source and cache as /indexed).
    try:
        from .indexed import get_indexed_map
        indexed_map = get_indexed_map()
        if tkr in indexed_map:
            return IngestStatusResponse(status="indexed", chunks=indexed_map[tkr])
    except Exception as e:
        logger.warning("ingest-status: indexed-map lookup failed for %s: %s", key, e)

    # 2. Shared IngestJob doc — authoritative in-flight lifecycle across instances.
    try:
        from .embeddings import load_ingest_job
        job = load_ingest_job(key)
    except Exception as e:
        logger.warning("ingest-status: job load failed for %s: %s", key, e)
        job = None
    if job is not None and job.status in _INGEST_STATUS_VALUES:
        return IngestStatusResponse(
            status=job.status, chunks=job.chunks or 0, error=job.last_error,
        )

    # 3. In-memory fallback (pre-persist window), else unknown.
    with _status_lock:
        info = _ingest_status.get(key)
    if info is not None:
        return IngestStatusResponse(
            status=info["status"], chunks=info["chunks"], error=info.get("error"),
        )
    return IngestStatusResponse(status="unknown", chunks=0)


class RetryRequest(BaseModel):
    ticker: str
    form: Literal["10-K"]


@app.post("/ingest-retry")
def ingest_retry(req: RetryRequest) -> dict:
    """Re-enqueue a previously failed/waiting EDGAR ingest using the stored payload."""
    ticker = req.ticker.strip().upper()
    key = _ingest_key(ticker, req.form)
    with _status_lock:
        payload = _ingest_payloads.get(key)
        if not payload:
            raise HTTPException(
                status_code=404,
                detail=f"No stored payload for {ticker} {req.form}. Re-fetch from EDGAR first.",
            )
        _ingest_status[key] = {"status": "queued", "chunks": 0, "error": None}

    try:
        from .embeddings import upsert_job
        upsert_job(
            key, "edgar", ticker, req.form,
            payload["source"], payload.get("accession_number", ""),
            payload.get("filing_date", ""), payload["sections"],
        )
    except Exception as e:
        logger.warning("Could not upsert job on retry for %s %s: %s", ticker, req.form, e)

    _ingest_queue.put((
        ticker, req.form,
        payload["sections"], payload["source"], key,
        payload.get("accession_number", ""), payload.get("filing_date", ""),
    ))
    logger.info("Re-enqueued EDGAR ingest for %s %s", ticker, req.form)
    return {"queued": True}


# ---------------------------------------------------------------------------
# File upload + enqueue
# ---------------------------------------------------------------------------

def _extract_pdf_text(data: bytes) -> str:
    """Extract text from a digital PDF. Returns '' for scanned/image-only PDFs."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        raise RuntimeError("PyPDF2 not installed. Run: pip install PyPDF2")
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _upload_doc_id(filename: str) -> str:
    """Stable 12-char ID from filename — same file always gets the same key."""
    return hashlib.sha1(filename.encode()).hexdigest()[:12]


@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    name: Optional[str] = Form(default=None),
) -> dict:
    """
    Accept a PDF or TXT file, extract its text, and enqueue it for embedding.

    Like /extract, runs an inline already-indexed check using the stable doc_id
    (sha1 of filename) as the accession_number. Re-uploading an already-indexed
    file returns "indexed" status immediately with no embedding calls.

    Returns immediately with {doc_id, filename, char_count} so the frontend
    can create the document entry and start polling /upload-status.
    """
    filename = name or file.filename or "upload"
    ext = Path(filename).suffix.lower()

    if ext not in (".pdf", ".txt", ".text"):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Upload a PDF or TXT file.",
        )

    raw = file.file.read()

    if len(raw) > UPLOAD_MAX_MB * 1_048_576:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {UPLOAD_MAX_MB} MB limit.",
        )

    if ext == ".pdf":
        try:
            text = _extract_pdf_text(raw)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"PDF parsing failed: {e}")
        if len(text.strip()) < 200:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No extractable text found in this PDF. "
                    "It may be a scanned or image-only document. "
                    "Try copying text from it — if nothing selects, OCR is required."
                ),
            )
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        if len(text.strip()) < 200:
            raise HTTPException(status_code=422, detail="File appears to be empty or too short to embed.")

    doc_id = _upload_doc_id(filename)
    ticker_label = Path(filename).stem[:20].upper().replace(" ", "_")
    source = filename

    # Store payload unconditionally.
    with _status_lock:
        _ingest_payloads[doc_id] = {
            "ticker": ticker_label, "form": "UPLOAD",
            "sections": {"full_text": text}, "source": source,
            "accession_number": doc_id, "filing_date": "",
        }

    # Inline already-indexed check — doc_id is the stable accession_number.
    is_indexed, n_existing = _check_already_indexed_inline(
        ticker_label, "UPLOAD", doc_id, source,
    )

    if is_indexed:
        logger.info("Upload already indexed: %s doc_id=%s (%d chunks)", filename, doc_id, n_existing)
        with _status_lock:
            _ingest_status[doc_id] = {"status": "indexed", "chunks": n_existing, "error": None}
    else:
        with _status_lock:
            _ingest_status[doc_id] = {"status": "queued", "chunks": 0, "error": None}
        try:
            from .embeddings import upsert_job
            upsert_job(
                doc_id, "upload", ticker_label, "UPLOAD",
                source, doc_id, "", {"full_text": text},
            )
        except Exception as e:
            logger.warning("Could not upsert upload job for %s: %s", doc_id, e)
        _ingest_queue.put((ticker_label, "UPLOAD", {"full_text": text}, source, doc_id, doc_id, ""))
        logger.info(
            "Upload enqueued: %s (%d chars) doc_id=%s", filename, len(text), doc_id,
        )

    return {
        "doc_id": doc_id,
        "filename": filename,
        "char_count": len(text),
        "ticker_label": ticker_label,
    }


@app.get("/upload-status/{doc_id}", response_model=IngestStatusResponse)
def upload_status(doc_id: str) -> IngestStatusResponse:
    with _status_lock:
        info = _ingest_status.get(doc_id)
    if info is None:
        return IngestStatusResponse(status="unknown", chunks=0)
    return IngestStatusResponse(
        status=info["status"], chunks=info["chunks"], error=info.get("error"),
    )


class UploadRetryRequest(BaseModel):
    doc_id: str


@app.post("/upload-retry")
def upload_retry(req: UploadRetryRequest) -> dict:
    """Re-enqueue a previously failed/waiting upload ingest using the stored payload."""
    doc_id = req.doc_id
    with _status_lock:
        payload = _ingest_payloads.get(doc_id)
        if not payload:
            raise HTTPException(
                status_code=404,
                detail=f"No stored payload for doc {doc_id}. Please re-upload the file.",
            )
        _ingest_status[doc_id] = {"status": "queued", "chunks": 0, "error": None}

    try:
        from .embeddings import upsert_job
        upsert_job(
            doc_id, "upload",
            payload["ticker"], payload["form"],
            payload["source"], payload.get("accession_number", doc_id),
            payload.get("filing_date", ""), payload["sections"],
        )
    except Exception as e:
        logger.warning("Could not upsert upload job on retry for %s: %s", doc_id, e)

    _ingest_queue.put((
        payload["ticker"], payload["form"],
        payload["sections"], payload["source"], doc_id,
        payload.get("accession_number", doc_id), payload.get("filing_date", ""),
    ))
    logger.info("Re-enqueued upload ingest for doc_id=%s", doc_id)
    return {"queued": True}
