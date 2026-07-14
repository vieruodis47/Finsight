"""
data_extract/prediction.py

Statistical FORECAST endpoint for the Analysis page.

Wraps the offline forecasting pipeline (analysis/metrics + analysis/stats) and
returns plain JSON — denoised, weighted-linear-trend projections with 95%
confidence intervals for core metrics. Charts render client-side in Recharts
(see frontend/components/ForecastPanel.tsx), so there is deliberately NO plotly
here; this endpoint only shapes numbers, never figures.

Route:
  GET /analysis/prediction/{ticker}
    -> {ticker, metrics: [{metric, unit, history:[{year,value}],
        predicted_value, confidence_low, confidence_high, next_label,
        trend, reliability, r_squared, anomaly_years}]}

SEC access flows through analysis.metrics.get_company_facts, which is routed
through the shared throttled sec_client (see PR #51), so this endpoint inherits
the global 10 req/s throttle + 429 backoff — it does not add a new SEC egress path.
"""

import logging

from fastapi import APIRouter, HTTPException

# analysis/ is a sibling package under backend/. graph/router.py already imports
# from ..analysis.metrics, so this relative import resolves in the app package.
from ..analysis.metrics import get_company_metrics, calculate_ratios
from ..analysis.stats import analyze_metric

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Core metrics we forecast. "revenue" is a raw USD series; the rest are margins
# (percent). Order is display order on the Analysis page.
_FORECAST_METRICS = [
    "revenue",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
]

# stats.predict_next_value needs >= 3 points; mirror that so we don't ship a
# "prediction" the model itself would have refused to make.
_MIN_HISTORY = 3


@router.get("/prediction/{ticker}")
def prediction(ticker: str) -> dict:
    """Denoised trend forecast for a company's core metrics."""
    ticker = ticker.upper()

    try:
        raw = get_company_metrics(ticker)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Ticker '{ticker}' is not in the SEC registry."
        )
    except Exception as e:
        logger.warning("prediction: metric fetch failed for %s: %s", ticker, e)
        raise HTTPException(
            status_code=502, detail=f"Could not load SEC metrics for {ticker}: {e}"
        )

    ratios = calculate_ratios(raw)

    # Pivot {year: {metric: val}} -> {metric: {year: val}}; margins come from
    # ratios, and we inject the raw revenue series (ratios only carry percents).
    pivoted: dict = {}
    for year, metrics in ratios.items():
        for metric, value in metrics.items():
            pivoted.setdefault(metric, {})[year] = value
    try:
        pivoted["revenue"] = raw["revenue"]["values"]
    except (KeyError, TypeError):
        pass

    results = []
    for metric in _FORECAST_METRICS:
        series = pivoted.get(metric)
        if not series:
            continue

        history = [
            {"year": str(y), "value": float(series[y])}
            for y in sorted(series)
            if series[y] is not None
        ]
        if len(history) < _MIN_HISTORY:
            continue

        analysis = analyze_metric(series, metric_name=metric)
        pred = analysis.get("prediction")
        if not pred:
            continue

        lo, hi = pred["confidence_interval"]
        results.append(
            {
                "metric": metric,
                "unit": "usd" if metric == "revenue" else "pct",
                "history": history,
                "predicted_value": pred["predicted_value"],
                "confidence_low": lo,
                "confidence_high": hi,
                "next_label": pred["next_label"],
                "trend": pred["trend"],             # improving | declining | stable
                "reliability": pred["reliability"], # high | moderate | low
                "r_squared": pred["r_squared"],
                "anomaly_years": [str(y) for y in analysis.get("anomalies", {})],
            }
        )

    if not results:
        raise HTTPException(
            status_code=422,
            detail=f"Not enough historical filing data to forecast {ticker}.",
        )

    return {"ticker": ticker, "metrics": results}
