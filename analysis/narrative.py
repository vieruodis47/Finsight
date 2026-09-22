from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def generate_company_narrative(ticker, ratios, stock_stats, company_name):
    latest_year = sorted(ratios.keys())[-1]
    latest = ratios[latest_year]

    prompt = f"""
    You are a financial analyst specializing in the fast fashion retail industry.
    Based on the following data for {company_name}, write a concise 3-4 sentence
    analyst commentary. Focus on key strengths, risks, and what the numbers suggest
    about the company's financial health. Be specific — reference actual numbers.

    Financial Data ({latest_year}):
    - Gross Margin: {latest.get('gross_margin_pct')}%
    - Operating Margin: {latest.get('operating_margin_pct')}%
    - Net Margin: {latest.get('net_margin_pct')}%
    - Inventory Turnover: {latest.get('inventory_turnover')}x
    - Days Inventory Outstanding: {latest.get('days_inventory_outstanding')} days
    - Revenue Growth YoY: {latest.get('revenue_growth_pct')}%
    - Debt-to-Equity: {latest.get('debt_to_equity')}
    - Free Cash Flow: ${latest.get('free_cash_flow'):,}
    - Current Ratio: {latest.get('current_ratio')}

    Market Data:
    - Current Price: ${stock_stats.get('current_price')}
    - Market Cap: ${stock_stats.get('market_cap'):,}
    - 52-Week High: ${stock_stats.get('52_week_high')}
    - 52-Week Low: ${stock_stats.get('52_week_low')}
    - P/E Ratio: {stock_stats.get('pe_ratio')}

    Write the commentary in plain English, no bullet points, no headers.
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt
    )
    return response.text


if __name__ == "__main__":
    import sys
    sys.path.append('.')
    from metrics import COMPANIES, get_company_metrics, calculate_ratios
    from stock_data import get_all_stock_data

    COMPANY_NAMES = {
        "GAP": "Gap Inc.",
        "PVH": "PVH Corp",
        "AEO": "American Eagle"
    }

    stock_data = get_all_stock_data()

    for ticker in COMPANIES:
        metrics = get_company_metrics(ticker)
        ratios = calculate_ratios(metrics)
        stats = stock_data[ticker]["stats"]

        print(f"\n{'='*50}")
        print(f"{COMPANY_NAMES[ticker]}")
        print('='*50)
        narrative = generate_company_narrative(
            ticker, ratios, stats, COMPANY_NAMES[ticker]
        )
        print(narrative)
