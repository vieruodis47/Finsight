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


def predict_next_value(values_dict, n_ahead=1):
    """
    Fit a weighted linear trend to historical values and predict n_ahead steps forward.
    Recent years are weighted exponentially higher than older ones.
    """
    years = sorted(values_dict.keys())
    values = [values_dict[y] for y in years if values_dict[y] is not None]
    valid_years = [y for y in years if values_dict[y] is not None]

    if len(values) < 3:
        return None

    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)

    # Exponential weights — most recent year weighted highest
    weights = np.exp(np.linspace(0, 1, len(values)))
    weights = weights / weights.sum()  # normalize

    # Weighted means
    x_mean = np.average(x, weights=weights)
    y_mean = np.average(y, weights=weights)

    # Weighted linear regression
    slope = np.sum(weights * (x - x_mean) * (y - y_mean)) / \
            np.sum(weights * (x - x_mean) ** 2)
    intercept = y_mean - slope * x_mean

    # Predict next value
    next_x = len(values) - 1 + n_ahead
    predicted = slope * next_x + intercept

    # Weighted R² calculation
    y_pred = slope * x + intercept
    residuals = y - y_pred
    ss_res = np.sum(weights * residuals ** 2)
    ss_tot = np.sum(weights * (y - y_mean) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # 95% CI using weighted residual std
    residual_std = np.sqrt(np.sum(weights * residuals ** 2))
    margin = 1.96 * residual_std * np.sqrt(len(values))

    # Trend direction based on weighted slope
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
        "confidence_interval": (float(round(predicted - margin, 4)),
                                float(round(predicted + margin, 4))),
        "r_squared": float(round(r_squared, 4)),
        "slope": float(round(slope, 4)),
        "trend": trend,
        "reliability": reliability,
        "next_label": f"FY{int(valid_years[-1][:4]) + 1} (projected)"
    }

def analyze_metric(values_dict, metric_name="metric"):
    """
    Full analysis pipeline for one metric:
    standardize + detect anomalies + DE-NOISE + predict next value.
    """
    standardized = standardize_series(values_dict)
    anomalies = {y: d for y, d in standardized.items() if d["is_anomaly"]}
    
    denoised_dict = {}
    for year, value in values_dict.items():
        if year in standardized and standardized[year]["is_anomaly"]:
            denoised_dict[year] = standardized[year]["mean"]
        else:
            denoised_dict[year] = value

    prediction = predict_next_value(denoised_dict)

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

