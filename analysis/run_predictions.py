# analysis/run_predictions.py
from metrics import COMPANIES, get_company_metrics, calculate_ratios
from stats import analyze_all_metrics

COMPANY_NAMES = {
    "GAP": "Gap Inc.",
    "PVH": "PVH Corp",
    "AEO": "American Eagle"
}

# The target core financial metrics you want to forecast
METRICS_TO_FORECAST = ["revenue", "gross_margin_pct", "operating_margin_pct"]

print("=" * 60)
print("EXPONENTIAL TIME-SERIES FORECASTS (FY2027)")
print("=" * 60)

for ticker in COMPANIES:
    print(f"\n🔹 {COMPANY_NAMES[ticker]} ({ticker}):")
    
    # 1. Pull fundamental historical accounting data
    raw_metrics = get_company_metrics(ticker)
    ratios = calculate_ratios(raw_metrics)
    
    # 2. We must inject raw revenue into our series since calculate_ratios 
    # only returns percentage margins for revenue streams.
    pivoted_series = {}
    for year, ratio_dict in ratios.items():
        for metric, val in ratio_dict.items():
            if metric not in pivoted_series:
                pivoted_series[metric] = {}
            pivoted_series[metric][year] = val
            
    # Manually append raw revenue history to the forecasting pool
    pivoted_series["revenue"] = raw_metrics["revenue"]["values"]

    # 3. Process every targeted metric through your stats.py pipeline
    for metric in METRICS_TO_FORECAST:
        if metric in pivoted_series:
            # analyze_metric handles anomaly identification, de-noising, and forecasting
            from stats import analyze_metric
            analysis_result = analyze_metric(pivoted_series[metric], metric_name=metric)
            
            pred = analysis_result["prediction"]
            anomalies = analysis_result["anomalies"]
            
            if not pred:
                continue
                
            # Print beautiful, stable, mathematical outputs
            print(f"\n  Target Metric: {metric.upper()}")
            if metric == "revenue":
                print(f"    Predicted FY2027: ${pred['predicted_value']:,.2f}")
                print(f"    95% Confidence Interval: (${pred['confidence_interval'][0]:,.2f} to ${pred['confidence_interval'][1]:,.2f})")
            else:
                print(f"    Predicted FY2027: {pred['predicted_value']:.2f}%")
                print(f"    95% Confidence Interval: ({pred['confidence_interval'][0]:.2f}% to {pred['confidence_interval'][1]:.2f}%)")
                
            print(f"    Trend Direction:  {pred['trend'].upper()}")
            print(f"    Model Reliability: {pred['reliability'].upper()} (R²: {pred['r_squared']})")
            
            if anomalies:
                print(f"    ⚠️  Denoised {len(anomalies)} historical anomaly outlier(s) before fitting trend.")
