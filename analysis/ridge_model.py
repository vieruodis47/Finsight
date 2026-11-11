"""
analysis/ridge_model.py

Multi-variable predictive modeling using Ridge Regression (L2 Regularization).
Predicts next-year Revenue, Gross Margin %, and Operating Margin %
using current-year operational metrics as features.

Two modes:
- Per-company: train on one company's own history
- Cross-company: train on all 3 companies combined (more data, less personalized)
"""

import numpy as np
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score
import warnings
import pandas as pd
warnings.filterwarnings('ignore')


# Features used as predictors (X)
FEATURE_METRICS = [
    "inventory_turnover",
    "current_ratio",
    "debt_to_equity",
    "gross_margin_pct",
    "operating_margin_pct",
    "revenue_growth_pct",
    "free_cash_flow",
]

# Target metrics to predict (Y) — one model per target
TARGET_METRICS = [
    "revenue",
    "gross_margin_pct",
    "operating_margin_pct",
]

import pandas as pd

def filter_multicollinear_features(X, feature_names, threshold=0.75):
    """
    Scans the feature matrix X for pairs with a correlation higher than the threshold.
    Drops the second feature in any highly correlated pair.
    Returns the filtered X matrix and the remaining feature names.
    """
    if X.shape[1] <= 1:
        return X, feature_names

    # Convert to DataFrame to use the built-in correlation tool
    df = pd.DataFrame(X, columns=feature_names)
    corr_matrix = df.corr().abs()

    # Identify features to drop
    to_drop = set()
    for i in range(len(corr_matrix.columns)):
        for j in range(i):
            if corr_matrix.iloc[i, j] > threshold:
                colname = corr_matrix.columns[i]
                # Avoid dropping the target if it accidentally matches
                to_drop.add(colname)

    # Keep track of what we are keeping
    remaining_features = [f for f in feature_names if f not in to_drop]
    
    # Filter the numpy array columns
    keep_indices = [feature_names.index(f) for f in remaining_features]
    X_filtered = X[:, keep_indices]

    return X_filtered, remaining_features

def build_xy(ratios, raw_metrics, target_metric, normalize_revenue=False):
    """
    Build feature matrix X and target vector y from ratio/metrics data.
    Each row = one year's features, predicting the NEXT year's target.
    normalize_revenue: if True, uses revenue % change instead of raw dollars
    """
    years = sorted(ratios.keys())
    revenue_values = raw_metrics.get("revenue", {}).get("values", {})

    rows_X = []
    rows_y = []
    row_years = []

    for i in range(len(years) - 1):
        current_year = years[i]
        next_year = years[i + 1]

        features = []
        valid = True
        for feat in FEATURE_METRICS:
            val = ratios[current_year].get(feat)
            if val is None:
                valid = False
                break
            features.append(val)

        if not valid:
            continue

        # Get target value for next year
        if target_metric == "revenue":
            if normalize_revenue:
                # Use YoY % change instead of raw dollars
                curr_rev = revenue_values.get(current_year)
                next_rev = revenue_values.get(next_year)
                if curr_rev is None or next_rev is None or curr_rev == 0:
                    continue
                target_val = (next_rev - curr_rev) / curr_rev * 100
            else:
                target_val = revenue_values.get(next_year)
        else:
            target_val = ratios[next_year].get(target_metric)

        if target_val is None:
            continue

        rows_X.append(features)
        rows_y.append(target_val)
        row_years.append((current_year, next_year))

    if len(rows_X) < 3:
        return None, None, None

    return np.array(rows_X), np.array(rows_y), row_years

def train_ridge(X, y, feature_names):
    """
    Stabilized training pipeline: filter out collinear features based 
    on raw data, then isolate columns, fit a target-specific scaler, and cross-validate.
    """
    from sklearn.model_selection import LeaveOneOut, cross_val_score
    from sklearn.linear_model import Ridge
    import pandas as pd
    import numpy as np

    # STEP 1: Compute correlation matrix on raw feature data to find collinear pairs
    df_raw = pd.DataFrame(X, columns=feature_names)
    corr_matrix = df_raw.corr().abs()

    to_drop = set()
    threshold = 0.75
    for i in range(len(corr_matrix.columns)):
        for j in range(i):
            if corr_matrix.iloc[i, j] > threshold:
                to_drop.add(corr_matrix.columns[i])

    surviving_features = [f for f in feature_names if f not in to_drop]
    keep_indices = [feature_names.index(f) for f in surviving_features]
    
    # Fallback safeguard if all features are somehow dropped
    if not keep_indices:
        surviving_features = feature_names
        keep_indices = [feature_names.index(f) for f in feature_names]

    # STEP 2: Extract only the surviving columns from the raw X matrix
    X_filtered = X[:, keep_indices]

    # STEP 3: Scale ONLY the surviving features
    # Now scaler.transform() will expect exactly len(surviving_features) columns!
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_filtered)

    # STEP 4: Regularization search with a baseline guardrail alpha
    alphas = [0.5, 1.0, 5.0, 10.0, 50.0, 100.0]
    best_alpha = alphas[0]
    best_score = -np.inf
    loo = LeaveOneOut()

    for alpha in alphas:
        model_candidate = Ridge(alpha=alpha)
        scores = cross_val_score(model_candidate, X_scaled, y, cv=loo, scoring='r2')
        mean_score = np.mean(scores)
        if mean_score > best_score:
            best_score = mean_score
            best_alpha = alpha

    # STEP 5: Refit model on the final scaled dataset
    final_model = Ridge(alpha=best_alpha)
    final_model.fit(X_scaled, y)

    from sklearn.metrics import r2_score as r2
    in_sample_r2 = r2(y, final_model.predict(X_scaled))

    return final_model, scaler, round(float(best_score), 4), best_alpha, round(float(in_sample_r2), 4), surviving_features


def predict_next(model, scaler, latest_ratios, raw_metrics, target_metric, surviving_features):
    """
    Predict next year's target metric using only the features that survived the filter.
    """
    features = []
    for feat in surviving_features:
        val = latest_ratios.get(feat)
        if val is None:
            return None, None
        features.append(val)

    # X will have a shape of (1, len(surviving_features))
    X = np.array([features])
    X_scaled = scaler.transform(X) # This will match perfectly now!
    predicted = model.predict(X_scaled)[0]

    importances = {
        feat: round(float(coef), 4)
        for feat, coef in zip(surviving_features, model.coef_)
    }

    return float(round(predicted, 4)), importances


def run_per_company_models(all_ratios, all_raw_metrics):
    """
    Train one Ridge model per company per target metric.
    Returns: {ticker: {target: {predicted, r2, alpha, importances}}}
    """
    results = {}

    for ticker, ratios in all_ratios.items():
        results[ticker] = {}
        raw_metrics = all_raw_metrics[ticker]
        latest_year = sorted(ratios.keys())[-1]
        latest_ratios = ratios[latest_year]

        for target in TARGET_METRICS:
            # Inside your run loops:
            X, y, years = build_xy(ratios, raw_metrics, target, normalize_revenue=False)

            if X is not None:
                # Pass FEATURE_METRICS as the third argument
                model, scaler, r2, alpha, in_sample_r2, surviving_features = train_ridge(X, y, FEATURE_METRICS)
                
                # Pass surviving_features to your prediction function
                predicted, importances = predict_next(model, scaler, latest_ratios, raw_metrics, target, surviving_features)

            results[ticker][target] = {
                "predicted": predicted,
                "r2": r2,                    # LOO cross-validated (honest)
                "in_sample_r2": in_sample_r2,  # in-sample (for reference)
                "alpha": alpha,
                "importances": importances,
                "n_samples": len(y),
                "mode": "per_company"        # or "cross_company"
            }

    return results


def run_cross_company_models(all_ratios, all_raw_metrics):
    """
    Train one Ridge model per target metric using all companies combined.
    Returns: {ticker: {target: {predicted, r2, alpha, importances}}}
    """
    results = {ticker: {} for ticker in all_ratios}

    for target in TARGET_METRICS:
        # Combine data from all companies
        all_X, all_y = [], []
        for ticker, ratios in all_ratios.items():
            raw_metrics = all_raw_metrics[ticker]
            X, y, _ = build_xy(ratios, raw_metrics, target,
                   normalize_revenue=(target == "revenue"))
            if X is not None:
                all_X.append(X)
                all_y.append(y)

        if not all_X:
            continue

        X_combined = np.vstack(all_X)
        y_combined = np.concatenate(all_y)

        model, scaler, r2, alpha, in_sample_r2, surviving_features = train_ridge(X_combined, y_combined, FEATURE_METRICS)

        # Now predict for each company's latest year
        for ticker, ratios in all_ratios.items():
            latest_year = sorted(ratios.keys())[-1]
            latest_ratios = ratios[latest_year]
            raw_metrics = all_raw_metrics[ticker]

            predicted, importances = predict_next(
                model, scaler, latest_ratios, raw_metrics, target, surviving_features
            )

            results[ticker][target] = {
                "predicted": predicted,
                "r2": r2,
                "in_sample_r2": in_sample_r2,
                "alpha": alpha,
                "importances": importances,
                "n_samples": len(y_combined),
                "mode": "cross_company"
            }

    return results


def reliability_label(r2):
    if r2 >= 0.5:
        return "HIGH"
    elif r2 >= 0.2:
        return "MODERATE"
    else:
        return "LOW"


if __name__ == "__main__":
    import sys
    sys.path.append('.')
    from metrics import COMPANIES, get_company_metrics, calculate_ratios

    COMPANY_NAMES = {
        "GAP": "Gap Inc.",
        "PVH": "PVH Corp",
        "AEO": "American Eagle"
    }

    all_ratios = {}
    all_raw_metrics = {}
    for ticker in COMPANIES:
        raw = get_company_metrics(ticker)
        all_raw_metrics[ticker] = raw
        all_ratios[ticker] = calculate_ratios(raw)

    print("\n" + "="*60)
    print("RIDGE REGRESSION — PER COMPANY MODELS")
    print("="*60)
    per_company = run_per_company_models(all_ratios, all_raw_metrics)

    for ticker, targets in per_company.items():
        print(f"\n{COMPANY_NAMES[ticker]}:")
        for target, result in targets.items():
            if result is None:
                print(f"  {target}: insufficient data")
                continue
            print(f"\n  Target: {target}")
            print(f"  Predicted FY2027: {result['predicted']:,.4f}")
            print(f"  R²: {result['r2']} ({reliability_label(result['r2'])} confidence)")
            print(f"  R² (in-sample): {result['in_sample_r2']} ← inflated, use LOO instead")
            print(f"  Ridge alpha: {result['alpha']} | Samples: {result['n_samples']}")
            print(f"  Top features by influence:")
            sorted_imp = sorted(result['importances'].items(),
                                key=lambda x: abs(x[1]), reverse=True)
            for feat, coef in sorted_imp[:3]:
                direction = "↑" if coef > 0 else "↓"
                print(f"    {direction} {feat}: {coef}")

    print("\n" + "="*60)
    print("RIDGE REGRESSION — CROSS COMPANY MODEL")
    print("="*60)
    cross_company = run_cross_company_models(all_ratios, all_raw_metrics)

    for ticker, targets in cross_company.items():
        print(f"\n{COMPANY_NAMES[ticker]}:")
        for target, result in targets.items():
            if result is None:
                print(f"  {target}: insufficient data")
                continue
            print(f"\n  Target: {target}")
            print(f"  Predicted FY2027: {result['predicted']:,.4f}")
            print(f"  R²: {result['r2']} ({reliability_label(result['r2'])} confidence)")
            print(f"  R² (in-sample): {result['in_sample_r2']} ← inflated, use LOO instead")
            print(f"  Ridge alpha: {result['alpha']} | Samples: {result['n_samples']}")
            print(f"  Top features by influence:")
            sorted_imp = sorted(result['importances'].items(),
                                key=lambda x: abs(x[1]), reverse=True)
            for feat, coef in sorted_imp[:3]:
                direction = "↑" if coef > 0 else "↓"
                print(f"    {direction} {feat}: {coef}")
