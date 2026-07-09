"""
GET /compare-metrics?a=AAPL&b=MSFT

Returns Recharts-ready multi-year comparison data for two tickers.
Inlines the XBRL extraction logic from analysis/metrics.py so no
cross-package import is needed.

In-process cache, keyed on frozenset({a, b}) so order doesn't matter.
Primary invalidation is ingest-based: invalidate_ticker() is wired into
graph.router.register_filing() and fires on every fresh filing ingest through
that path, with a fail-closed full clear if it can't be trusted to have run.
Cached response dicts are stored and returned by reference -- safe because
compare_metrics() is only ever reached through the FastAPI route and consumed
across the HTTP/JSON boundary; nothing in-process holds or mutates the object
after return.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from .sec_client import get_cik, get_company_facts

router = APIRouter()

# Belt-and-suspenders TTL on top of ingest-based invalidation -- NOT because
# the underlying XBRL expires (it's immutable once ingested), but because
# backend/scripts/bulk_ingest.py ingests filings in a separate OS process that
# never calls register_filing() and so cannot reach or invalidate this
# in-process cache. Bounds worst-case staleness to 1h instead of "until this
# process happens to restart."
_CACHE_TTL_SECONDS = 3600
_cache: dict[frozenset[str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def invalidate_ticker(ticker: str) -> None:
    """Drop every cached pair that includes this ticker.

    Called from graph.router.register_filing() whenever a filing is
    (re-)ingested for a ticker -- that's our signal that fresh XBRL data may
    now exist upstream, so any cached pair including it is potentially stale.
    """
    ticker = ticker.upper()
    with _cache_lock:
        stale = [key for key in _cache if ticker in key]
        for key in stale:
            del _cache[key]


def clear_cache() -> None:
    """Drop the entire cache. Fail-safe for when invalidate_ticker() can't be
    trusted to have removed the right entries -- losing the cache is cheap,
    serving a stale comparison is not."""
    with _cache_lock:
        _cache.clear()


# ── XBRL field name lists (fallback order) ─────────────────────────────────

_FLOW: dict[str, list[str]] = {
    "revenue":              ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "gross_profit":         ["GrossProfit"],
    "operating_income":     ["OperatingIncomeLoss"],
    "net_income":           ["NetIncomeLoss"],
    "operating_cash_flow":  ["NetCashProvidedByUsedInOperatingActivities"],
    "capex":                ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForCapitalImprovements"],
}

_INSTANT: dict[str, list[str]] = {
    "total_debt":           ["LongTermDebtNoncurrent", "LongTermDebt"],
    "equity":               ["StockholdersEquity"],
    "current_assets":       ["AssetsCurrent"],
    "current_liabilities":  ["LiabilitiesCurrent"],
}

# ── XBRL extraction helpers ─────────────────────────────────────────────────

def _annual(facts: dict, field: str) -> dict[str, float]:
    """Annual 10-K flow values (360–372 day periods only)."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    if field not in usgaap:
        return {}
    by_end: dict[str, dict] = {}
    for e in usgaap[field].get("units", {}).get("USD", []):
        if e.get("form") != "10-K" or "start" not in e:
            continue
        start = datetime.strptime(e["start"], "%Y-%m-%d")
        end   = datetime.strptime(e["end"],   "%Y-%m-%d")
        if not (360 <= (end - start).days <= 372):
            continue
        key = e["end"]
        if key not in by_end or e["filed"] > by_end[key]["filed"]:
            by_end[key] = e
    return {k: v["val"] for k, v in sorted(by_end.items())}


def _instant(facts: dict, field: str) -> dict[str, float]:
    """Instant (balance-sheet) 10-K values, most-recently-filed per period."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    if field not in usgaap:
        return {}
    by_end: dict[str, dict] = {}
    for e in usgaap[field].get("units", {}).get("USD", []):
        if e.get("form") != "10-K":
            continue
        key = e["end"]
        if key not in by_end or e["filed"] > by_end[key]["filed"]:
            by_end[key] = e
    return {k: v["val"] for k, v in sorted(by_end.items())}


def _first(facts: dict, fields: list[str], is_instant: bool) -> dict[str, float]:
    """Try XBRL field names in order; return first that yields data."""
    for name in fields:
        vals = _instant(facts, name) if is_instant else _annual(facts, name)
        if vals:
            return vals
    return {}


def _pull(facts: dict) -> dict[str, dict[str, float]]:
    """Pull all raw metric time-series for one company."""
    out: dict[str, dict[str, float]] = {}
    for key, names in _FLOW.items():
        out[key] = _first(facts, names, False)
    for key, names in _INSTANT.items():
        out[key] = _first(facts, names, True)
    return out


# ── Derived series computation ──────────────────────────────────────────────

def _compute(raw: dict[str, dict[str, float]]) -> dict[str, dict]:
    """
    Return {year_label: {metric: value}} for all years in revenue.
    Monetary values stored in $M (millions).
    """
    revenue = raw.get("revenue", {})
    years   = sorted(revenue.keys())
    series: dict[str, dict] = {}

    for i, yr in enumerate(years):
        rev = revenue.get(yr)
        gp  = raw["gross_profit"].get(yr)
        oi  = raw["operating_income"].get(yr)
        ni  = raw["net_income"].get(yr)
        ocf = raw["operating_cash_flow"].get(yr)
        cap = raw["capex"].get(yr)
        debt = raw["total_debt"].get(yr) or 0
        eq   = raw["equity"].get(yr)
        ca   = raw["current_assets"].get(yr)
        cl   = raw["current_liabilities"].get(yr)

        r: dict = {}

        # Absolute ($M)
        if rev  is not None: r["revenue"]       = round(rev / 1e6, 1)
        if ni   is not None: r["net_income"]     = round(ni  / 1e6, 1)
        if ocf is not None and cap is not None:
            r["free_cash_flow"] = round((ocf - cap) / 1e6, 1)

        # Margins (%)
        if rev:
            if gp is not None: r["gross_margin_pct"]     = round(gp / rev * 100, 2)
            if oi is not None: r["operating_margin_pct"] = round(oi / rev * 100, 2)
            if ni is not None: r["net_margin_pct"]       = round(ni / rev * 100, 2)

        # Revenue growth YoY
        if i > 0:
            prev_rev = revenue.get(years[i - 1])
            if rev is not None and prev_rev:
                r["revenue_growth_pct"] = round((rev - prev_rev) / prev_rev * 100, 2)

        # Balance-sheet ratios
        if eq: r["debt_to_equity"] = round(debt / eq, 2)
        if ca and cl: r["current_ratio"] = round(ca / cl, 2)

        # Use YYYY as the label; last entry wins if two filings share a year
        series[yr[:4]] = r

    return series


# ── Alignment helper ────────────────────────────────────────────────────────

def _merge(s_a: dict, s_b: dict, key: str, limit: int = 10) -> list[dict]:
    """Align two year-keyed series on one metric → [{year, a, b}] for the last `limit` years."""
    all_years = sorted(set(s_a) | set(s_b))
    rows = [
        {"year": yr, "a": s_a.get(yr, {}).get(key), "b": s_b.get(yr, {}).get(key)}
        for yr in all_years
    ]
    return rows[-limit:]


# ── FastAPI endpoint ─────────────────────────────────────────────────────────

_SERIES_KEYS = [
    "revenue", "net_income", "gross_margin_pct", "operating_margin_pct",
    "net_margin_pct", "revenue_growth_pct", "free_cash_flow",
    "debt_to_equity", "current_ratio",
]


def _fetch_ticker(ticker: str) -> dict:
    """Resolve ticker → CIK → company facts (blocking I/O)."""
    cik = get_cik(ticker)
    return get_company_facts(cik)


@router.get("/compare-metrics")
def compare_metrics(a: str = Query(...), b: str = Query(...)):
    """Return Recharts-ready multi-year comparison data for two tickers."""
    a, b = a.upper().strip(), b.upper().strip()
    cache_key = frozenset({a, b})

    with _cache_lock:
        cached = _cache.get(cache_key)
    if cached is not None:
        cached_at, cached_data = cached
        if time.monotonic() - cached_at < _CACHE_TTL_SECONDS:
            # Returned by reference, not copied: this dict is shared with the
            # cache entry. Safe today because this route has no response_model
            # (FastAPI's jsonable_encoder builds a new structure, never mutates
            # the input) and no other code in the repo calls compare_metrics()
            # directly. If either of those stops being true, mutate a
            # copy.deepcopy() of this, never the object itself.
            return cached_data

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(_fetch_ticker, a)
            fut_b = pool.submit(_fetch_ticker, b)
            facts_a = fut_a.result()
            facts_b = fut_b.result()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"XBRL fetch failed: {e}")

    series_a = _compute(_pull(facts_a))
    series_b = _compute(_pull(facts_b))

    result = {
        "tickers": {"a": a, "b": b},
        **{k: _merge(series_a, series_b, k) for k in _SERIES_KEYS},
    }

    with _cache_lock:
        now = time.monotonic()
        # Single-pass eviction of expired entries on write, same as #3's
        # /market cache, so the dict doesn't grow unbounded over the process
        # lifetime.
        expired = [k for k, (cached_at, _) in _cache.items() if now - cached_at >= _CACHE_TTL_SECONDS]
        for k in expired:
            del _cache[k]
        _cache[cache_key] = (now, result)

    return result
