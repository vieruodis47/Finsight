"""
data_extract/analysis_charts.py

Data-only JSON endpoints backing the Analysis "Trends" charts (ported from
Michelle's offline Plotly charts.py to Recharts on the frontend). This module
never renders figures — it only shapes numbers; the frontend owns all drawing
(theme tokens, green/red-directional-only convention).

All series flow through analysis.metrics.get_company_metrics, which is the
tag-merged, fiscal-year-correct layer (PR #53): each metric is unioned across
its fallback XBRL tags, so companies like MSFT return the FULL 2008-2025 series
rather than a truncated legacy slice. Year labels derive from the XBRL
period-END date, never filing_date.

Routes (prefix /analysis, already on the Node forwarder allowlist):
  GET /analysis/trends/{ticker}        -> multi-year revenue/profit/margins
  GET /analysis/quarterly/{ticker}     -> latest fiscal year Q1-Q4 breakdown
  GET /analysis/distribution/{ticker}  -> per-year values + trend anomalies
"""

import logging

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from ..analysis.metrics import (
    get_company_metrics,
    calculate_ratios,
    get_quarterly_metrics,
    get_available_years,
)
from ..analysis.stats import analyze_metric
from ..analysis.descriptions import (
    describe_series,
    describe_quarterly,
    describe_distribution,
    describe_margin_cascade,
)

# Human labels for the surfaced metrics, shared by the trend descriptions.
_TREND_LABELS = {
    "revenue": "Revenue",
    "net_income": "Net income",
    "gross_margin_pct": "Gross margin",
    "operating_margin_pct": "Operating margin",
    "net_margin_pct": "Net margin",
}
_QUARTER_LABELS = {
    "revenue": "Revenue",
    "gross_profit": "Gross profit",
    "operating_income": "Operating income",
    "net_income": "Net income",
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Raw-USD "flow" fields we surface as trend lines/stacks, plus the derived
# margin ratios. Order is display order.
_DOLLAR_FIELDS = ["revenue", "net_income", "cogs", "gross_profit", "operating_income"]
_MARGIN_FIELDS = ["gross_margin_pct", "operating_margin_pct", "net_margin_pct"]

# Metrics offered to the distribution view. USD series are strongly trended so a
# normal fit is only descriptive, but we keep the option; margins are the more
# meaningful case.
_DIST_UNITS = {
    "revenue": "usd", "net_income": "usd",
    "gross_margin_pct": "pct", "operating_margin_pct": "pct", "net_margin_pct": "pct",
}

_QUARTERLY_FIELDS = ["revenue", "cogs", "gross_profit", "operating_income", "net_income"]


def _load(ticker: str):
    """Fetch raw metrics for a ticker, mapping registry/fetch errors to HTTP."""
    try:
        return get_company_metrics(ticker)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' is not in the SEC registry.")
    except Exception as e:
        logger.warning("analysis_charts: metric fetch failed for %s: %s", ticker, e)
        raise HTTPException(status_code=502, detail=f"Could not load SEC metrics for {ticker}: {e}")


def _fy(period_end: str) -> str:
    """Fiscal-year label from an XBRL period-end date ('2024-06-30' -> '2024')."""
    return str(period_end)[:4]


@router.get("/trends/{ticker}")
def trends(ticker: str) -> dict:
    """Multi-year revenue / net income / COGS / gross profit + margin ratios.

    Returns one row per fiscal year (Recharts-ready), keyed by the period-end
    year. Backs the single-company trend line, the COGS/gross-profit stack, and
    the revenue-vs-net-income dual-axis chart.
    """
    ticker = ticker.upper()
    raw = _load(ticker)
    ratios = calculate_ratios(raw)  # {period_end: {margin: val}}

    # Union every fiscal year that any surfaced field reports.
    years: set[str] = set()
    for f in _DOLLAR_FIELDS:
        years.update((raw.get(f) or {}).get("values", {}).keys())
    years.update(ratios.keys())

    points = []
    for pe in sorted(years):
        row: dict = {"year": _fy(pe)}
        for f in _DOLLAR_FIELDS:
            v = (raw.get(f) or {}).get("values", {}).get(pe)
            row[f] = float(v) if v is not None else None
        for m in _MARGIN_FIELDS:
            v = ratios.get(pe, {}).get(m)
            row[m] = float(v) if v is not None else None
        points.append(row)

    if not points:
        raise HTTPException(status_code=422, detail=f"No trend data available for {ticker}.")

    # ── Deterministic, templated descriptions (no LLM, no quota) ──────────────
    # Computed from the same period-end series the charts plot, so the prose can
    # never disagree with the plotted numbers. Keyed to each chart / selector.
    def _vals(field: str) -> dict:
        return {pe: v for pe, v in (raw.get(field) or {}).get("values", {}).items() if v is not None}

    rev = _vals("revenue")
    cogs = _vals("cogs")
    margin_series = {
        m: {pe: r[m] for pe, r in ratios.items() if r.get(m) is not None}
        for m in _MARGIN_FIELDS
    }
    cogs_share = {pe: cogs[pe] / rev[pe] * 100 for pe in cogs if rev.get(pe)}

    descriptions = {
        "revenue": describe_series(rev, "usd", "Revenue"),
        "net_income": describe_series(_vals("net_income"), "usd", "Net income"),
        **{
            m: describe_series(margin_series[m], "pct", _TREND_LABELS[m])
            for m in _MARGIN_FIELDS
        },
        # Static charts: the cost-structure stack and the revenue-vs-net-income
        # dual axis. Both are summarised through the ratio that drives them.
        "cost_structure": describe_series(cogs_share, "pct", "COGS as a share of revenue"),
        "revenue_vs_income": describe_series(
            margin_series["net_margin_pct"], "pct", "Net margin (net income ÷ revenue)"
        ),
        # Cross-metric synthesis: the margin cascade (gross → operating → net) and
        # what its gaps/divergence say about cost structure and operating leverage.
        # Computed from the same margin series above, so prose matches the charts.
        "synthesis": describe_margin_cascade(
            margin_series["gross_margin_pct"],
            margin_series["operating_margin_pct"],
            margin_series["net_margin_pct"],
            rev,
        ),
    }

    return {"ticker": ticker, "currency": "usd", "points": points, "descriptions": descriptions}


@router.get("/quarterly/{ticker}")
def quarterly(ticker: str) -> dict:
    """Q1-Q4 breakdown for the latest fiscal year that has all four quarters.

    Q4 is derived (annual - Q1 - Q2 - Q3) upstream in analysis.metrics.
    """
    ticker = ticker.upper()
    # Surface registry errors the same way as the other routes.
    try:
        years = get_available_years(ticker)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' is not in the SEC registry.")
    except Exception as e:
        logger.warning("analysis_charts: quarterly fetch failed for %s: %s", ticker, e)
        raise HTTPException(status_code=502, detail=f"Could not load quarterly data for {ticker}: {e}")

    if not years:
        raise HTTPException(status_code=422, detail=f"No complete quarterly data for {ticker}.")

    latest = years[-1]
    # get_quarterly_metrics(year=latest) returns {metric: {latest_end: {Q1..Q4: val}}}.
    q_metrics = get_quarterly_metrics(ticker, year=latest)

    points = []
    for q in ("Q1", "Q2", "Q3", "Q4"):
        row: dict = {"quarter": q}
        for f in _QUARTERLY_FIELDS:
            v = (q_metrics.get(f) or {}).get(latest, {}).get(q)
            row[f] = float(v) if v is not None else None
        points.append(row)

    fy = _fy(latest)
    descriptions = {
        f: describe_quarterly(points, f, _QUARTER_LABELS[f], fy)
        for f in _QUARTER_LABELS
    }

    return {
        "ticker": ticker, "currency": "usd", "fy": fy,
        "points": points, "descriptions": descriptions,
    }


@router.get("/distribution/{ticker}")
def distribution(ticker: str, metric: str = Query("revenue")) -> dict:
    """Per-year values + distribution (mean/std) + TREND-relative anomaly flags.

    Anomalies come from analyze_metric (residuals around the trend, per PR #55),
    NOT global-mean z-scores, so a steep series' newest point isn't mislabeled an
    outlier. mean/std describe the historical spread for the bell curve overlay.
    """
    ticker = ticker.upper()
    if metric not in _DIST_UNITS:
        raise HTTPException(status_code=400, detail=f"Unsupported distribution metric '{metric}'.")

    raw = _load(ticker)

    if metric in raw:  # raw dollar series
        series = {pe: v for pe, v in (raw.get(metric) or {}).get("values", {}).items() if v is not None}
    else:              # derived margin ratio
        ratios = calculate_ratios(raw)
        series = {pe: r[metric] for pe, r in ratios.items() if r.get(metric) is not None}

    if len(series) < 3:
        raise HTTPException(status_code=422, detail=f"Not enough history to chart {metric} distribution for {ticker}.")

    analysis = analyze_metric(series, metric_name=metric)
    anomaly_years = set(analysis.get("anomalies", {}).keys())

    vals = np.array([float(v) for v in series.values()], dtype=float)
    points = [
        {"year": _fy(pe), "value": float(series[pe]), "is_anomaly": pe in anomaly_years}
        for pe in sorted(series)
    ]

    mean = float(np.mean(vals))
    std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
    label = _TREND_LABELS.get(metric, metric.replace("_", " ").title())
    description = describe_distribution(points, mean, std, _DIST_UNITS[metric], label)

    return {
        "ticker": ticker,
        "metric": metric,
        "unit": _DIST_UNITS[metric],
        "mean": mean,
        "std": std,
        "points": points,
        "description": description,
    }
