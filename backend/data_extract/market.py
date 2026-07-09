"""
data_extract/market.py

Market-data endpoint backed by yfinance. Serves the dashboard's "Market
snapshot" and "price history" panels with a current snapshot (price, market
cap, volume, 52-week range, P/E) plus a daily close series.

Self-contained on purpose: it calls yfinance directly rather than importing the
analysis/ pipeline, so the market route has no cross-package dependency.

In-process cache, 60s TTL, keyed on (ticker, period) — not ticker alone, since
period changes the returned history/snapshot. Time-based only: market prices
aren't tied to ingested filings, so no ingest event invalidates this.

Not a request-coalescing cache: the lock only protects the dict itself from
concurrent-write corruption, not the check-then-fetch sequence. Two requests
that miss on the same key at the same time will both hit yfinance and both
write the result — last write wins. Acceptable here since both calls fetch
the same data; this is not a cache to rely on for de-duplicating in-flight
upstream calls.
"""

import threading
import time
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
import yfinance as yf

router = APIRouter(prefix="/market", tags=["market"])

_CACHE_TTL_SECONDS = 60
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _extract_domain(url: str) -> str | None:
    """Return the hostname from a URL string, or None if empty/unparseable."""
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc or None


@router.get("/{ticker}")
def get_market(ticker: str, period: str = "1y"):
    """
    Current market snapshot + daily close history for a ticker.
    period: '1mo','3mo','6mo','1y','2y','5y','max'
    """
    ticker = ticker.strip().upper()
    cache_key = (ticker, period)

    with _cache_lock:
        cached = _cache.get(cache_key)
    if cached is not None:
        cached_at, cached_data = cached
        if time.monotonic() - cached_at < _CACHE_TTL_SECONDS:
            return cached_data

    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        # .info can be slow/flaky; tolerate failure and fall back to history.
        try:
            info = t.info or {}
        except Exception:
            info = {}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {e}")

    if hist is None or hist.empty:
        raise HTTPException(status_code=404, detail=f"No market data for {ticker}")

    closes = hist["Close"].dropna()
    history = [
        {"date": d.strftime("%Y-%m-%d"), "close": round(float(c), 2)}
        for d, c in closes.items()
    ]

    latest = float(closes.iloc[-1]) if len(closes) else None
    prev = float(closes.iloc[-2]) if len(closes) > 1 else latest
    change_pct = round((latest - prev) / prev * 100, 2) if (latest is not None and prev) else None

    snapshot = {
        "price":      round(latest, 2) if latest is not None else None,
        "market_cap": info.get("marketCap"),
        "volume":     info.get("volume") or info.get("regularMarketVolume") or info.get("averageVolume"),
        "high_52w":   info.get("fiftyTwoWeekHigh"),
        "low_52w":    info.get("fiftyTwoWeekLow"),
        "pe_ratio":   info.get("trailingPE"),
        "change_pct": change_pct,
        "website":    _extract_domain(info.get("website", "")),
    }

    result = {"ticker": ticker, "period": period, "snapshot": snapshot, "history": history}

    with _cache_lock:
        now = time.monotonic()
        # Single pass eviction of expired entries on write, so the dict doesn't
        # grow unbounded across many tickers x periods over the process lifetime.
        expired = [k for k, (cached_at, _) in _cache.items() if now - cached_at >= _CACHE_TTL_SECONDS]
        for k in expired:
            del _cache[k]
        _cache[cache_key] = (now, result)

    return result
