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


def run_monte_carlo_forecast(historical_series, steps=3, simulations=5000):
    """
    Runs a Log-Normal Monte Carlo simulation to forecast future horizons.
    Guarantees no values drop below zero and cleanly models long-tail upside growth.
    """
    # Filter out invalid or zero entries
    vals = [float(v) for v in historical_series.values() if v is not None and v > 0]
    if len(vals) < 2:
        return None

    # 1. Calculate historical log returns (Geometric growth changes)
    log_returns = []
    for i in range(1, len(vals)):
        log_returns.append(np.log(vals[i] / vals[i-1]))
            
    if not log_returns:
        log_returns = [0.0]

    # 2. Derive log-space parameters
    mu = np.mean(log_returns)
    sigma = np.std(log_returns) if np.std(log_returns) > 0 else 0.02
    
    last_value = vals[-1]
    last_year = int(max(list(historical_series.keys()))[:4])
    
    # Simulation matrix: Shape = (simulations, steps)
    sim_results = np.zeros((simulations, steps))
    
    # 3. Execute the Log-Normal random walk matrix operation
    for s in range(simulations):
        current_val = last_value
        for step in range(steps):
            # Sample from standard normal distribution
            z = np.random.normal(0, 1)
            # Apply log-normal growth step formula: S_t = S_{t-1} * exp((mu - 0.5*sigma^2) + sigma*z)
            growth_factor = np.exp((mu - 0.5 * (sigma ** 2)) + sigma * z)
            current_val = current_val * growth_factor
            sim_results[s, step] = current_val

    # 4. Extract probabilistic percentiles
    forecast_years = [str(last_year + i + 1) for i in range(steps)]
    p10 = np.percentile(sim_results, 10, axis=0)  # Safe downside floor
    p50 = np.percentile(sim_results, 50, axis=0)  # Median compounded trajectory
    p90 = np.percentile(sim_results, 90, axis=0)  # Long-tail optimistic ceiling

    return {
        "years": forecast_years,
        "p10": p10.tolist(),
        "p50": p50.tolist(),
        "p90": p90.tolist(),
        "last_year": str(last_year),
        "last_value": last_value
    }


def monte_carlo_forecast_chart(mc_results, metric_name, company_name):
    """
    Renders a 3-year probabilistic forecasting cloud using Monte Carlo outputs.
    """
    if not mc_results:
        return None

    import plotly.graph_objects as go

    clean_metric = metric_name.replace('_', ' ').title()
    
    # Setup timeline x-vector
    timeline = [mc_results["last_year"]] + mc_results["years"]
    
    # Tie the historical baseline to the front of the forecast vectors
    y_p10 = [mc_results["last_value"]] + mc_results["p10"]
    y_p50 = [mc_results["last_value"]] + mc_results["p50"]
    y_p90 = [mc_results["last_value"]] + mc_results["p90"]

    fig = go.Figure()

    # 1. Plot the Upper 90th Percentile Bound Line
    fig.add_trace(go.Scatter(
        x=timeline, y=y_p90,
        mode='lines',
        line=dict(width=0.5, color='rgba(78, 121, 167, 0.2)'),
        name='90th Percentile (Optimistic Target)',
        showlegend=True
    ))

    # 2. Shaded Confidence Interval Cloud (Filled down to 10th Percentile)
    fig.add_trace(go.Scatter(
        x=timeline, y=y_p10,
        mode='lines',
        fill='tonexty', # 👈 Shades the space between p90 and p10
        fillcolor='rgba(78, 121, 167, 0.15)',
        line=dict(width=0.5, color='rgba(78, 121, 167, 0.2)'),
        name='10th Percentile (Downside Risk)',
        showlegend=True
    ))

    # 3. Plot the Core Median Forecast Trajectory
    fig.add_trace(go.Scatter(
        x=timeline, y=y_p50,
        mode='lines+markers',
        line=dict(width=3, color='#2B5C8F', dash='dash'),
        name='Median Expected Path (Monte Carlo Walk)'
    ))

    fig.update_layout(
        title=f"{company_name} — 3-Year Log-Normal Probabilistic {clean_metric} Forecast",
        xaxis=dict(title="Fiscal Year Horizon", type="category", automargin=True),
        yaxis=dict(title=clean_metric, automargin=True),
        template="plotly_white",
        hovermode="x unified"
    )
    
    return fig

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
