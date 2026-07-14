"""
analysis/stats.py

Statistical analysis module for FinSight.
Provides:
- Z-score standardization of financial metrics and stock returns
- Anomaly detection (|z| > 2 flags)
- Denoised linear trend prediction with 95% confidence intervals
"""

import numpy as np
from scipy import stats


def standardize_series(values_dict):
    """
    Given a dict of {year: value}, compute z-scores for each year.
    Returns: {year: {'value': v, 'z_score': z, 'is_anomaly': bool}}
    """
    years = sorted(values_dict.keys())
    values = [values_dict[y] for y in years if values_dict[y] is not None]
    valid_years = [y for y in years if values_dict[y] is not None]

    if len(values) < 3:
        return {}  # not enough data for meaningful stats

    mean = np.mean(values)
    std = np.std(values, ddof=1)  # ddof=1 for sample std

    if std == 0:
        return {y: {"value": v, "z_score": 0.0, "is_anomaly": False}
                for y, v in zip(valid_years, values)}

    result = {}
    for year, value in zip(valid_years, values):
        z = (value - mean) / std
        result[year] = {
            "value": float(value),
            "z_score": float(round(z, 3)),
            "is_anomaly": bool(abs(z) > 2),
            "mean": float(round(mean, 4)),
            "std": float(round(std, 4))
        }
    return result


def _weighted_linear_fit(y):
    """Recency-weighted least-squares line through y (x = 0..n-1).

    Most recent point weighted e× the oldest. Returns
    (slope, intercept, weights, y_pred, residuals, r_squared) in the space of y.
    """
    n = len(y)
    x = np.arange(n, dtype=float)

    weights = np.exp(np.linspace(0, 1, n))
    weights = weights / weights.sum()

    x_mean = np.average(x, weights=weights)
    y_mean = np.average(y, weights=weights)

    slope = np.sum(weights * (x - x_mean) * (y - y_mean)) / \
            np.sum(weights * (x - x_mean) ** 2)
    intercept = y_mean - slope * x_mean

    y_pred = slope * x + intercept
    residuals = y - y_pred
    ss_res = np.sum(weights * residuals ** 2)
    ss_tot = np.sum(weights * (y - y_mean) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return slope, intercept, weights, y_pred, residuals, r_squared


def _use_geometric(values):
    """Whether to fit in log space (constant-growth / CAGR) vs. linear.

    Strictly-positive growth series (revenue, most margins) are multiplicative:
    a straight line through accelerating revenue under-projects the next point
    (and can fall below the latest actual). Fitting log(value) captures a growth
    RATE instead. Series that can go non-positive (e.g. a net-margin loss year)
    can't be logged, so they stay linear.
    """
    return len(values) >= 3 and all(v > 0 for v in values)


def predict_next_value(values_dict, n_ahead=1, geometric=None):
    """
    Fit a recency-weighted trend and predict n_ahead steps forward.

    For strictly-positive growth series the fit is done in log space (geometric /
    constant-growth), so the projection tracks the recent growth rate rather than
    a straight line that lags accelerating data. `geometric=None` auto-selects.
    """
    years = sorted(values_dict.keys())
    valid_years = [y for y in years if values_dict[y] is not None]
    values = [values_dict[y] for y in valid_years]

    if len(values) < 3:
        return None

    if geometric is None:
        geometric = _use_geometric(values)

    y_raw = np.array(values, dtype=float)
    y = np.log(y_raw) if geometric else y_raw

    slope, _, weights, _, residuals, r_squared = _weighted_linear_fit(y)

    # Project from the LATEST observation, extended by the fitted growth rate
    # (Holt-style), rather than extrapolating the fitted intercept. A least-squares
    # line lags an accelerating series, so its endpoint can fall below the last
    # actual even with a positive slope; anchoring to the last point and adding the
    # trend keeps the 1-step forecast on the right side of the latest value.
    projected = y[-1] + slope * n_ahead

    # 95% prediction band from the weighted residual spread, in the fit's own
    # space. No sqrt(n) inflation — the width now reflects model fit: a tight fit
    # (small residuals / high R²) yields a tight band.
    residual_std = np.sqrt(np.sum(weights * residuals ** 2))
    margin = 1.96 * residual_std

    # Back-transform the point + interval. In log space the band is multiplicative
    # (asymmetric in dollars) — the correct shape for a growth series.
    if geometric:
        predicted = float(np.exp(projected))
        lo, hi = float(np.exp(projected - margin)), float(np.exp(projected + margin))
    else:
        predicted = float(projected)
        lo, hi = float(projected - margin), float(projected + margin)

    # Trend from the sign of the weighted slope; a residual-scaled dead-band keeps
    # a near-flat series reading "stable". (Sign is space-invariant: a positive log
    # slope is still growth.)
    if slope > residual_std * 0.1:
        trend = "improving"
    elif slope < -residual_std * 0.1:
        trend = "declining"
    else:
        trend = "stable"

    # R² reliability label
    if r_squared >= 0.5:
        reliability = "high"
    elif r_squared >= 0.2:
        reliability = "moderate"
    else:
        reliability = "low"

    return {
        "predicted_value": float(round(predicted, 4)),
        "confidence_interval": (float(round(lo, 4)), float(round(hi, 4))),
        "r_squared": float(round(r_squared, 4)),
        "slope": float(round(slope, 4)),
        "trend": trend,
        "reliability": reliability,
        "geometric": bool(geometric),
        "next_label": f"FY{int(valid_years[-1][:4]) + 1} (projected)"
    }


def denoise_series(values_dict, geometric=None):
    """Replace genuine outliers with the recency-weighted TREND value.

    Anomalies are measured as residuals around the trend, NOT distance from the
    global mean: on a steep monotonic series the newest, largest value sits far
    from the mean yet is perfectly on-trend, so a global-mean test wrongly flags
    it and (as before) flattened the forecast to the mean. A point is an anomaly
    only if its trend residual exceeds 2σ; it is then replaced with the fitted
    value so the projection is nudged toward the trend, never toward the mean.

    Returns (denoised_dict, anomalies) where anomalies maps year -> details.
    """
    years = sorted(values_dict.keys())
    valid_years = [y for y in years if values_dict[y] is not None]
    values = [values_dict[y] for y in valid_years]

    denoised = dict(values_dict)
    anomalies = {}
    if len(values) < 3:
        return denoised, anomalies

    if geometric is None:
        geometric = _use_geometric(values)

    y_raw = np.array(values, dtype=float)
    y = np.log(y_raw) if geometric else y_raw

    _, _, _, y_pred, residuals, _ = _weighted_linear_fit(y)
    resid_std = np.std(residuals, ddof=1)
    # Guard a (near-)perfect fit: residuals at floating-point noise level must not
    # be divided into large z-scores that spuriously flag on-trend points.
    if resid_std <= 1e-9 * (abs(np.mean(y)) + 1e-12):
        return denoised, anomalies

    for i, yr in enumerate(valid_years):
        z = residuals[i] / resid_std
        if abs(z) > 2:
            fitted = float(np.exp(y_pred[i])) if geometric else float(y_pred[i])
            denoised[yr] = fitted
            anomalies[yr] = {
                "value": float(y_raw[i]),
                "fitted": float(round(fitted, 4)),
                "z_score": float(round(z, 3)),
                "is_anomaly": True,
            }

    return denoised, anomalies

def analyze_metric(values_dict, metric_name="metric"):
    """
    Full analysis pipeline for one metric:
    standardize + detect anomalies + DE-NOISE + predict next value.
    """
    values = [v for v in values_dict.values() if v is not None]
    geometric = _use_geometric(values)

    # standardize_series stays for the per-year z-score summary, but anomaly
    # detection + de-noising are now TREND-relative (see denoise_series) so the
    # endpoints of a steep series are no longer mistaken for outliers.
    standardized = standardize_series(values_dict)
    denoised_dict, anomalies = denoise_series(values_dict, geometric=geometric)
    prediction = predict_next_value(denoised_dict, geometric=geometric)

    return {
        "metric_name": metric_name,
        "standardized": standardized,
        "anomalies": anomalies,
        "prediction": prediction,
        "n_anomalies": len(anomalies)
    }


def analyze_all_metrics(ratios, stock_returns=None):
    """
    Run full analysis on all financial ratios and optionally stock returns.
    """
    # Pivot ratios from {year: {metric: val}} to {metric: {year: val}}
    metric_series = {}
    for year, metrics in ratios.items():
        for metric, value in metrics.items():
            if metric not in metric_series:
                metric_series[metric] = {}
            metric_series[metric][year] = value

    results = {}
    for metric_name, values_dict in metric_series.items():
        results[metric_name] = analyze_metric(values_dict, metric_name)

    return results


if __name__ == "__main__":
    import sys
    sys.path.append('.')
    from metrics import COMPANIES, get_company_metrics, calculate_ratios

    COMPANY_NAMES = {
        "GAP": "Gap Inc.",
        "PVH": "PVH Corp",
        "AEO": "American Eagle"
    }

    for ticker in COMPANIES:
        print(f"\n{'='*60}")
        print(f"{COMPANY_NAMES[ticker]} — Statistical Analysis (DENOISED)")
        print('='*60)

        metrics = get_company_metrics(ticker)
        ratios = calculate_ratios(metrics)
        analysis = analyze_all_metrics(ratios)

        for metric_name, result in analysis.items():
            pred = result["prediction"]
            anomalies = result["anomalies"]

            if pred is None:
                continue

            print(f"\n{metric_name}:")
            print(f"  Trend:      {pred['trend']}")
            print(f"  Prediction: {pred['predicted_value']} "
                  f"({pred['next_label']})")
            print(f"  95% CI:     {pred['confidence_interval']}")
            print(f"  R²:         {pred['r_squared']}")

            if anomalies:
                print(f"  ⚠️  Anomalies detected ({len(anomalies)}):")
                for year, data in anomalies.items():
                    direction = "above" if data['z_score'] > 0 else "below"
                    print(f"     {year}: {data['value']} "
                          f"(z={data['z_score']}, "
                          f"{abs(data['z_score']):.1f}σ {direction} mean)")

