"""
analysis/metrics.py

Extracts financial metrics from SEC EDGAR XBRL data for any public filer.
Company ticker -> CIK resolution comes entirely from the generated SEC registry
(company_name/sec_companies.json); there are no hardcoded companies.
Used by the FinSight app to power charts and comparisons.
"""

import requests
from datetime import datetime
import json
import os
import re

HEADERS = {"User-Agent": "FinSight rahmansyah@wisc.edu"}  # SEC requires a real contact

# Ticker -> 10-digit CIK. Populated from the generated SEC registry below.
COMPANIES = {}
# Ticker -> company display name, from the same registry.
COMPANY_NAMES = {}

# The registry is built by company_name/extract_name.py from SEC's full ticker
# list and written next to that script.
JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'company_name', 'sec_companies.json')

if os.path.exists(JSON_PATH):
    try:
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            master_sec_data = json.load(f)

        company_list = master_sec_data.get("companies", [])

        for item in company_list:
            ticker = item.get("ticker")
            raw_cik = item.get("cik")

            if ticker and raw_cik:
                clean_ticker = str(ticker).strip().upper()

                # Strip any non-numeric text and pad to 10 digits
                digit_match = re.findall(r'\d+', str(raw_cik))
                if digit_match:
                    clean_cik = "".join(digit_match).zfill(10)
                    COMPANIES[clean_ticker] = clean_cik
                    COMPANY_NAMES[clean_ticker] = str(item.get("name") or clean_ticker)

        print(f"[Success] Loaded SEC registry: {len(COMPANIES)} companies mapped.")
    except Exception as e:
        print(f"[Error] Failed to read SEC registry at {JSON_PATH}: {e}")
else:
    print(
        f"[Error] SEC registry not found at {JSON_PATH}. "
        f"Generate it first by running company_name/extract_name.py. "
        f"Until then, no tickers can be resolved."
    )

# Fallback field names for each metric (different companies use different XBRL tags)
METRIC_FIELDS = {
    "revenue": (["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"], False),
    "cogs": (["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"], False),
    "gross_profit": (["GrossProfit"], False),
    "operating_income": (["OperatingIncomeLoss"], False),
    "net_income": (["NetIncomeLoss"], False),
    "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities"], False),
    "inventory": (["InventoryNet", "InventoryFinishedGoodsNetOfReserves", "InventoryFinishedGoods"], True),
    "total_assets": (["Assets"], True),
    "total_debt": (["LongTermDebtNoncurrent", "LongTermDebt"], True),
    "equity": (["StockholdersEquity"], True),
    "capex": (["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForCapitalImprovements"], False),
    "current_assets": (["AssetsCurrent"], True),
    "current_liabilities": (["LiabilitiesCurrent"], True),
}

# Only "flow" metrics make sense to break into quarters
QUARTERLY_METRIC_FIELDS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
}

# Metric Explanation
METRIC_EXPLANATIONS = {
    "gross_margin_pct": {
        "label": "Gross Margin %",
        "explanation": "The percentage of revenue left after paying for the cost of goods sold. Higher means the company keeps more profit per item sold before operating costs.",
        "category": "Profitability"
    },
    "operating_margin_pct": {
        "label": "Operating Margin %",
        "explanation": "Profit remaining after both cost of goods sold and operating expenses (SG&A, marketing, store costs). Shows how efficiently the company runs its core business.",
        "category": "Profitability"
    },
    "net_margin_pct": {
        "label": "Net Margin %",
        "explanation": "The final profit percentage after everything — interest, taxes, one-off items. The 'bottom line' — what's truly left for shareholders.",
        "category": "Profitability"
    },
    "inventory_turnover": {
        "label": "Inventory Turnover",
        "explanation": "How many times per year the company sells through its entire inventory. Higher means faster-moving stock, which generally reduces markdown and obsolescence risk.",
        "category": "Operational Efficiency"
    },
    "days_inventory_outstanding": {
        "label": "Days Inventory Outstanding",
        "explanation": "The same idea as inventory turnover, expressed in days. Shows how long, on average, inventory sits before it sells. Lower generally indicates leaner inventory management.",
        "category": "Operational Efficiency"
    },
    "revenue_growth_pct": {
        "label": "Revenue Growth %",
        "explanation": "How much revenue grew or shrank compared to the prior year. The most basic signal of whether a company is growing.",
        "category": "Growth"
    },
    "gross_profit_growth_pct": {
        "label": "Gross Profit Growth %",
        "explanation": "How much gross profit grew or shrank year-over-year. If this grows faster than revenue, margins are improving; if slower, margins are compressing even as sales rise.",
        "category": "Growth"
    },
    "debt_to_equity": {
        "label": "Debt-to-Equity",
        "explanation": "Total long-term debt divided by shareholder equity. Measures reliance on borrowed money vs. the company's own capital. Lower is generally a safer balance sheet.",
        "category": "Financial Health"
    },
    "operating_cash_flow": {
        "label": "Operating Cash Flow",
        "explanation": "Actual cash generated by core business operations, excluding non-cash accounting items. Often considered a more reliable health signal than net income.",
        "category": "Financial Health"
    },
    "free_cash_flow": {
        "label": "Free Cash Flow",
        "explanation": "Operating cash flow minus capital expenditures (money spent on property, equipment, stores). Represents cash truly available after running and maintaining the business — for paying down debt, buybacks, or dividends.",
        "category": "Financial Health"
    },
    "current_ratio": {
        "label": "Current Ratio",
        "explanation": "Current assets divided by current liabilities. Measures whether a company can cover its short-term obligations (bills due within a year) with its short-term assets. Above 1.0 generally means it can.",
        "category": "Financial Health"
    },
}


def get_metric_explanation(metric_name):
    """Look up the label and explanation for a given metric key."""
    return METRIC_EXPLANATIONS.get(metric_name, {
        "label": metric_name.replace("_", " ").title(),
        "explanation": "No explanation available for this metric.",
        "category": "Other"
    })


def get_company_facts(cik):
    """Fetch raw XBRL company facts JSON from SEC EDGAR."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def _extract_annual_field(data, field_name):
    """Extract clean annual (10-K) values for 'flow' fields (Revenue, COGS, etc.)"""
    if field_name not in data['facts']['us-gaap']:
        return {}

    usd_data = data['facts']['us-gaap'][field_name]['units']['USD']

    annual = []
    for entry in usd_data:
        if entry['form'] != '10-K':
            continue
        start = datetime.strptime(entry['start'], '%Y-%m-%d')
        end = datetime.strptime(entry['end'], '%Y-%m-%d')
        duration_days = (end - start).days
        if 360 <= duration_days <= 372:
            annual.append(entry)

    by_end = {}
    for entry in annual:
        key = entry['end']
        if key not in by_end or entry['filed'] > by_end[key]['filed']:
            by_end[key] = entry

    return {k: v['val'] for k, v in sorted(by_end.items())}


def _extract_instant_field(data, field_name):
    """Extract clean annual (10-K) values for 'stock' fields (Inventory, Assets, etc.)"""
    if field_name not in data['facts']['us-gaap']:
        return {}

    usd_data = data['facts']['us-gaap'][field_name]['units']['USD']

    annual = [entry for entry in usd_data if entry['form'] == '10-K']

    by_end = {}
    for entry in annual:
        key = entry['end']
        if key not in by_end or entry['filed'] > by_end[key]['filed']:
            by_end[key] = entry

    return {k: v['val'] for k, v in sorted(by_end.items())}


def extract_metric(data, field_options, instant=False):
    """Try multiple possible XBRL field names until one returns data."""
    for field_name in field_options:
        if instant:
            result = _extract_instant_field(data, field_name)
        else:
            result = _extract_annual_field(data, field_name)
        if result:
            return result, field_name
    return {}, None


def extract_all_metrics(data):
    """Extract all defined metrics for a company. Returns dict of {metric: {values, field_used}}"""
    results = {}
    for metric_name, (field_options, is_instant) in METRIC_FIELDS.items():
        values, used_field = extract_metric(data, field_options, instant=is_instant)
        results[metric_name] = {
            "values": values,
            "field_used": used_field
        }
    return results


def get_company_metrics(ticker):
    """
    Main entry point: given any public company ticker, fetch and return all
    financial metrics. Raises KeyError if the ticker isn't in the registry.
    """
    ticker = ticker.strip().upper()
    if ticker not in COMPANIES:
        raise KeyError(
            f"Ticker '{ticker}' not found in the SEC registry "
            f"({len(COMPANIES)} companies loaded)."
        )
    cik = COMPANIES[ticker]
    data = get_company_facts(cik)
    return extract_all_metrics(data)


def calculate_ratios(metrics):
    """
    Given the output of get_company_metrics(), calculate derived ratios
    for every year where the underlying data is available.
    Returns: {year: {ratio_name: value}}
    """
    ratios = {}

    revenue = metrics["revenue"]["values"]
    cogs = metrics["cogs"]["values"]
    gross_profit = metrics["gross_profit"]["values"]
    operating_income = metrics["operating_income"]["values"]
    net_income = metrics["net_income"]["values"]
    inventory = metrics["inventory"]["values"]
    total_debt = metrics["total_debt"]["values"]
    equity = metrics["equity"]["values"]
    operating_cash_flow = metrics["operating_cash_flow"]["values"]
    capex = metrics["capex"]["values"]
    current_assets = metrics["current_assets"]["values"]
    current_liabilities = metrics["current_liabilities"]["values"]

    years = sorted(revenue.keys())

    for i, year in enumerate(years):
        r = {}

        rev = revenue.get(year)
        gp = gross_profit.get(year)
        oi = operating_income.get(year)
        ni = net_income.get(year)
        cg = cogs.get(year)
        inv = inventory.get(year)
        debt = total_debt.get(year, 0)  # treat missing long-term debt as 0
        cap = capex.get(year)
        ca = current_assets.get(year)
        cl = current_liabilities.get(year)
        eq = equity.get(year)
        ocf = operating_cash_flow.get(year)

        # Profitability margins
        if rev:
            if gp is not None:
                r["gross_margin_pct"] = round(gp / rev * 100, 2)
            if oi is not None:
                r["operating_margin_pct"] = round(oi / rev * 100, 2)
            if ni is not None:
                r["net_margin_pct"] = round(ni / rev * 100, 2)

        # Inventory turnover (needs average inventory between this year and last)
        if cg is not None and inv is not None and i > 0:
            prev_year = years[i - 1]
            prev_inv = inventory.get(prev_year)
            if prev_inv is not None:
                avg_inventory = (inv + prev_inv) / 2
                if avg_inventory > 0:
                    turnover = cg / avg_inventory
                    r["inventory_turnover"] = round(turnover, 2)
                    r["days_inventory_outstanding"] = round(365 / turnover, 1)

        # YoY growth (needs previous year)
        if i > 0:
            prev_year = years[i - 1]
            prev_rev = revenue.get(prev_year)
            if rev is not None and prev_rev:
                r["revenue_growth_pct"] = round((rev - prev_rev) / prev_rev * 100, 2)

            prev_gp = gross_profit.get(prev_year)
            if gp is not None and prev_gp:
                r["gross_profit_growth_pct"] = round((gp - prev_gp) / prev_gp * 100, 2)

        # Financial health
        if eq:
            r["debt_to_equity"] = round(debt / eq, 2)

        if ocf is not None:
            r["operating_cash_flow"] = ocf

        # Free cash flow
        if ocf is not None and cap is not None:
            r["free_cash_flow"] = ocf - cap

        # Current ratio
        if ca is not None and cl:
            r["current_ratio"] = round(ca / cl, 2)

        ratios[year] = r

    return ratios


def extract_quarterly_field(data, field_name):
    """
    Extract quarterly values using actual fiscal year-end groupings,
    derived from each quarter's 'end' date rather than SEC's self-reported fy/fp tags.
    """
    if field_name not in data['facts']['us-gaap']:
        return {}

    usd_data = data['facts']['us-gaap'][field_name]['units']['USD']

    quarterly_entries = []
    annual_entries = []

    for entry in usd_data:
        start = datetime.strptime(entry['start'], '%Y-%m-%d')
        end = datetime.strptime(entry['end'], '%Y-%m-%d')
        duration_days = (end - start).days

        if entry['form'] == '10-Q' and 80 <= duration_days <= 100:
            quarterly_entries.append(entry)
        elif entry['form'] == '10-K' and 360 <= duration_days <= 372:
            annual_entries.append(entry)

    # Dedupe by end date, keep most recently filed
    q_by_end = {}
    for entry in quarterly_entries:
        key = entry['end']
        if key not in q_by_end or entry['filed'] > q_by_end[key]['filed']:
            q_by_end[key] = entry

    a_by_end = {}
    for entry in annual_entries:
        key = entry['end']
        if key not in a_by_end or entry['filed'] > a_by_end[key]['filed']:
            a_by_end[key] = entry

    # Group quarters under the fiscal year they roll up into
    annual_end_dates = sorted(a_by_end.keys())

    result = {}
    for q_end, entry in q_by_end.items():
        q_end_date = datetime.strptime(q_end, '%Y-%m-%d')
        matching_fy_end = None
        for a_end in annual_end_dates:
            a_end_date = datetime.strptime(a_end, '%Y-%m-%d')
            if a_end_date >= q_end_date:
                matching_fy_end = a_end
                break
        if matching_fy_end is None:
            continue

        if matching_fy_end not in result:
            result[matching_fy_end] = {}

        result[matching_fy_end][q_end] = entry['val']

    # Convert each fy group into Q1/Q2/Q3/Q4, derive Q4
    final_result = {}
    for fy_end, quarters_by_date in result.items():
        sorted_dates = sorted(quarters_by_date.keys())
        labeled = {}
        for i, date in enumerate(sorted_dates[:3]):
            labeled[f"Q{i+1}"] = quarters_by_date[date]

        annual_val = a_by_end[fy_end]['val']
        if all(k in labeled for k in ['Q1', 'Q2', 'Q3']):
            labeled['Q4'] = annual_val - labeled['Q1'] - labeled['Q2'] - labeled['Q3']

        final_result[fy_end] = labeled

    return final_result


def get_quarterly_metrics(ticker, year=None):
    """
    Fetch quarterly (Q1-Q4) values for all flow metrics for a given company.
    """
    ticker = ticker.strip().upper()
    if ticker not in COMPANIES:
        raise KeyError(
            f"Ticker '{ticker}' not found in the SEC registry "
            f"({len(COMPANIES)} companies loaded)."
        )
    cik = COMPANIES[ticker]
    data = get_company_facts(cik)

    results = {}
    for metric_name, field_options in QUARTERLY_METRIC_FIELDS.items():
        quarterly_data = {}
        for field_name in field_options:
            extracted = extract_quarterly_field(data, field_name)
            if extracted:
                quarterly_data = extracted
                break

        if year is not None:
            quarterly_data = {year: quarterly_data[year]} if year in quarterly_data else {}

        results[metric_name] = quarterly_data

    return results


def get_available_years(ticker):
    """
    Returns a sorted list of fiscal year-end dates that have quarterly data available.
    """
    quarterly = get_quarterly_metrics(ticker)
    revenue_years = quarterly.get("revenue", {})
    complete_years = [
        year for year, quarters in revenue_years.items()
        if all(q in quarters for q in ['Q1', 'Q2', 'Q3', 'Q4'])
    ]
    return sorted(complete_years)


# =====================================================================
# METRICS SCRIPT TEST BLOCK
# =====================================================================
if __name__ == "__main__":
    print("\n--- Running Internal Metrics Pipeline Integration Test ---")

    # Generic sample tickers; skipped automatically if not in the loaded registry.
    test_tickers = ["AAPL", "MSFT", "NKE"]

    for ticker in test_tickers:
        if ticker not in COMPANIES:
            print(f"\n⚠️ {ticker} not in registry ({len(COMPANIES)} loaded) — skipping.")
            continue

        print(f"\nTesting data compilation for: {ticker}...")
        try:
            raw_metrics = get_company_metrics(ticker)

            if "revenue" in raw_metrics and "values" in raw_metrics["revenue"]:
                rev_data = raw_metrics["revenue"]["values"]
                if rev_data:
                    print(f"✅ Successfully retrieved {ticker} Revenue Data!")
                    for yr in sorted(rev_data.keys())[-2:]:
                        print(f"  Year {yr}: ${rev_data[yr]:,.2f}")
                else:
                    print(f"⚠️ Revenue field resolved but returned no values for {ticker}.")
            else:
                print(f"⚠️ Raw data retrieved for {ticker}, but revenue fields were missing.")

        except Exception as err:
            print(f"❌ Integration test failed for ticker '{ticker}': {err}")

    print("\n--- Test Suite Complete ---")