"""
GET /metrics/{ticker}  ->  single-ticker XBRL metrics for the dashboard.

Named filing_metrics.py (not metrics.py) to avoid colliding with the unrelated
analysis/metrics.py, which is a separate chart/comparison extraction utility
with a different output shape and its own SEC fetch. This route reads the
FilingMetrics RavenDB collection, hence the name.

This is the READ-ONLY, EMBED-FREE counterpart to /extract. The dashboard's
fundamentals (revenue, margins, income, EPS, FCF, assets, cash, sector) are a
free XBRL read; embedding is a separate, quota-gated step that only FinChat
needs. A pasted /company/:ticker URL renders the dashboard through this route
and must never spend Gemini quota.

Two paths, both free, distinction invisible to the user:
  - FilingMetrics doc exists in RavenDB  -> return it. Pure DB read, no SEC call.
  - No doc yet                           -> run() (XBRL fetch, embed-free),
                                            persist via register_filing() (same
                                            path /extract uses), return it.

CRITICAL INVARIANT: this handler NEVER enqueues embedding work. See the
assertion at the register_filing() call below -- unlike /extract, no code path
here reaches app._ingest_queue.put().

In-process cache, 60s TTL, per-ticker, evict-expired-on-write (same shape as
the /market cache). Invalidated on register_filing() via invalidate_ticker(),
the same hook shared by the /indexed and /compare-metrics caches.
"""

import threading
import time

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/metrics", tags=["metrics"])

_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def invalidate_ticker(ticker: str) -> None:
    """Drop this ticker's cached metrics. Called from register_filing()."""
    with _cache_lock:
        _cache.pop(ticker.strip().upper(), None)


def _from_filing_metrics(doc) -> dict:
    """Map a RavenDB FilingMetrics document to the response shape."""
    return {
        "ticker":           doc.ticker,
        "form":             doc.form,
        "filing_date":      doc.filing_date,
        "fiscal_year_end":  getattr(doc, "fiscal_year_end", "") or "",
        "accession_number": doc.accession_number,
        "sector":           doc.sector,
        "metrics":          doc.metrics if isinstance(doc.metrics, dict) else {},
        "source":           "ravendb",
    }


def _from_run(result: dict) -> dict:
    """Map an extractor run() result to the response shape."""
    return {
        "ticker":           result.get("ticker", ""),
        "form":             result.get("form", "10-K"),
        "filing_date":      result.get("filing_date", ""),
        "fiscal_year_end":  result.get("fiscal_year_end", ""),
        "accession_number": result.get("accession_number", ""),
        "sector":           result.get("sector", "Unknown"),
        "metrics":          result.get("metrics", {}),
        "source":           "sec",
    }


@router.get("/{ticker}")
def get_metrics(ticker: str, form: str = "10-K") -> dict:
    """Return single-ticker dashboard metrics. Never enqueues embedding."""
    ticker = ticker.strip().upper()

    with _cache_lock:
        cached = _cache.get(ticker)
    if cached is not None:
        cached_at, cached_data = cached
        if time.monotonic() - cached_at < _CACHE_TTL_SECONDS:
            return cached_data

    # Fast path: serve the existing FilingMetrics doc. No SEC call, no embed.
    from .embeddings import load_filing_metrics
    doc = load_filing_metrics(ticker, form)
    if doc is not None:
        result = _from_filing_metrics(doc)
    else:
        # Fallback: no doc yet. run() is the SAME embed-free EDGAR caller
        # /extract uses -- reusing it means no second, unthrottled SEC caller
        # is introduced; SEC pacing is exactly whatever /extract already has.
        from .extractor import run
        try:
            extracted = run(ticker, form)
        except ValueError as e:
            # No CIK / no 10-K -- expected for many of the 10,433 searchable
            # tickers. 404, not 500, so the peer picker degrades gracefully.
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Metrics fetch failed: {e}")

        # Persist exactly as /extract does, so the next read hits the fast path
        # above. register_filing() writes FilingMetrics and invalidates caches;
        # it does NOT touch app._ingest_queue. This is the enqueue-adjacent
        # assertion: unlike the /extract handler, control never continues to an
        # _ingest_queue.put() -- no embedding job is ever created from /metrics.
        try:
            from ..graph.router import register_filing
            register_filing(extracted)
        except Exception:
            pass  # non-fatal: metrics still returned even if persistence fails
        result = _from_run(extracted)

    with _cache_lock:
        now = time.monotonic()
        # Evict expired entries on write so the dict can't grow unbounded across
        # many looked-up tickers over the process lifetime (same as /market).
        expired = [k for k, (ts, _) in _cache.items() if now - ts >= _CACHE_TTL_SECONDS]
        for k in expired:
            del _cache[k]
        _cache[ticker] = (now, result)

    return result
