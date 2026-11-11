"""
analysis/stock_data.py

Fetches real-time and historical stock price data via yfinance.
Used by the FinSight app to power price charts and market data panels.
"""

import yfinance as yf
import pandas as pd

TICKERS = {
    "GAP": "GAP",
    "PVH": "PVH",
    "AEO": "AEO"
}


def get_price_history(ticker, period="2y"):
    """
    Fetch historical daily price data.
    period options: '1mo', '3mo', '6mo', '1y', '2y', '5y', 'max'
    Returns a pandas DataFrame with Date, Open, High, Low, Close, Volume.
    """
    stock = yf.Ticker(ticker)
    history = stock.history(period=period)
    return history


def get_key_stats(ticker):
    """
    Fetch current key stats: price, market cap, 52-week high/low, P/E, volume.
    """
    stock = yf.Ticker(ticker)
    info = stock.info

    return {
        "current_price": info.get("currentPrice"),
        "market_cap": info.get("marketCap"),
        "52_week_high": info.get("fiftyTwoWeekHigh"),
        "52_week_low": info.get("fiftyTwoWeekLow"),
        "pe_ratio": info.get("trailingPE"),
        "average_volume": info.get("averageVolume"),
        "dividend_yield": info.get("dividendYield"),
    }


def calculate_returns(history):
    """
    Given a price history DataFrame, calculate basic returns.
    Returns dict with 1-month, 3-month, 6-month, 1-year return %.
    """
    if history.empty:
        return {}

    latest_price = history["Close"].iloc[-1]
    latest_date = history.index[-1]

    def return_since(days_ago):
        target_date = latest_date - pd.Timedelta(days=days_ago)
        past_data = history[history.index <= target_date]
        if past_data.empty:
            return None
        past_price = past_data["Close"].iloc[-1]
        return round((latest_price - past_price) / past_price * 100, 2)

    return {
        "1_month_return_pct": return_since(30),
        "3_month_return_pct": return_since(90),
        "6_month_return_pct": return_since(180),
        "1_year_return_pct": return_since(365),
    }


# analysis/stock_data.py (Find and update this function)

def get_all_stock_data(tickers=None, period="2y"):
    """
    Fetches stock data for a dynamic list of tickers.
    If no tickers are provided, defaults to the core three.
    """
    import yfinance as yf # Assuming it's imported here
    
    if tickers is None:
        tickers = ["GAP", "PVH", "AEO"]
        
    stock_data_results = {}
    
    for ticker in tickers:
        try:
            print(f"  Downloading market data from Yahoo Finance for: {ticker}...")
            ticker_obj = yf.Ticker(ticker)
            history = ticker_obj.history(period=period)
            
            if history.empty:
                print(f"  ⚠️ No stock history found for {ticker} on Yahoo Finance.")
                continue
                
            # --- Keep whatever your existing returns calculation logic is here ---
            # (e.g., calculating 1M, 3M, 6M, 1Y returns and saving to a dict)
            # Make sure it populates data exactly how your charts expect:
            # stock_data_results[ticker] = {"history": history, "returns": ..., "stats": ...}
            
            # Placeholder to show structure:
            stock_data_results[ticker] = {
                "history": history,
                "returns": {
                    "1_month_return_pct": ((history["Close"].iloc[-1] / history["Close"].iloc[-21]) - 1) * 100 if len(history) > 21 else 0,
                    "3_month_return_pct": ((history["Close"].iloc[-1] / history["Close"].iloc[-63]) - 1) * 100 if len(history) > 63 else 0,
                    "6_month_return_pct": ((history["Close"].iloc[-1] / history["Close"].iloc[-126]) - 1) * 100 if len(history) > 126 else 0,
                    "1_year_return_pct": ((history["Close"].iloc[-1] / history["Close"].iloc[-252]) - 1) * 100 if len(history) > 252 else 0,
                }
            }
        except Exception as e:
            print(f"  ❌ Error fetching market data for {ticker}: {e}")
            
    return stock_data_results


if __name__ == "__main__":
    stock_data = get_all_stock_data()

    for name, data in stock_data.items():
        print(f"\n{'='*50}")
        print(f"{name} ({data['ticker']})")
        print('='*50)

        print("\nKey Stats:")
        for k, v in data["stats"].items():
            print(f"  {k}: {v}")

        print(f"\nPrice history: {len(data['history'])} trading days fetched")
        print(data["history"].tail(3))

        print("\nReturns:")
        for k, v in data["returns"].items():
            print(f"  {k}: {v}%")
