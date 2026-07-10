"""
GET /indexed?tickers=AAPL,DELL  ->  {"AAPL": true, "DELL": false}

Checks whether a ticker has a completed IngestManifest (fully embedded and
searchable via vector RAG) -- NOT whether /extract has ever been called for
it. /ingest-status is not a substitute for this: it reads the in-memory
_ingest_status job-queue dict in app.py, which starts empty on every process
restart, so a ticker embedded in a prior process lifetime reads "unknown"
there even though it's fully indexed in RavenDB.

Unknown and not-indexed are the same thing to the UI: any requested ticker
without a manifest returns false, never an error. load_all_ingest_manifests()
already fails soft (returns [] on any RavenDB error), so that fallback is
inherited for free -- a RavenDB hiccup here degrades to "nothing is indexed"
rather than a 5xx.

In-process cache, 60s TTL, invalidated on graph.router.register_filing() --
same spirit as the /market and /compare-metrics caches, but shaped
differently: load_all_ingest_manifests() is one bulk "give me everything"
RavenDB query, not a per-ticker fetch, so there's one cached set with one
timestamp rather than a per-ticker dict. The TTL is the safety net for ingest
paths that don't call register_filing() (e.g. bulk_ingest.py runs in a
separate process); the invalidation hook just tightens that window on the
common path.
"""

import threading
import time

from fastapi import APIRouter, Query

router = APIRouter()

_CACHE_TTL_SECONDS = 60
_cache: tuple[float, set[str]] | None = None
_cache_lock = threading.Lock()


def _load_indexed_tickers() -> set[str]:
    from .embeddings import load_all_ingest_manifests
    manifests = load_all_ingest_manifests()
    return {m.ticker.upper() for m in manifests if m.ticker}


def _get_indexed_tickers() -> set[str]:
    global _cache
    with _cache_lock:
        if _cache is not None:
            cached_at, tickers = _cache
            if time.monotonic() - cached_at < _CACHE_TTL_SECONDS:
                return tickers

    tickers = _load_indexed_tickers()
    with _cache_lock:
        _cache = (time.monotonic(), tickers)
    return tickers


def invalidate() -> None:
    """Drop the cached indexed-ticker set. Called from register_filing()."""
    global _cache
    with _cache_lock:
        _cache = None


@router.get("/indexed")
def indexed(tickers: str = Query(...)) -> dict[str, bool]:
    """Return {ticker: isIndexed} for a comma-separated list of tickers."""
    requested = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    indexed_set = _get_indexed_tickers()
    return {t: t in indexed_set for t in requested}
