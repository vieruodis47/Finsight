"""Fetch SEC's ticker list and save it as JSON (name + ticker + CIK)."""
import json
from datetime import date
import requests

HEADERS = {"User-Agent": "FinSight rahmansyah@wisc.edu"}  # SEC requires a real contact

raw = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS).json()

companies = sorted(
    ({"name": e["title"],
      "ticker": e["ticker"].upper(),
      "cik": str(e["cik_str"]).zfill(10)}      # 10-digit, ready for data.sec.gov
     for e in raw.values()),
    key=lambda c: c["name"],
)

payload = {
    "source": "https://www.sec.gov/files/company_tickers.json",
    "retrieved": date.today().isoformat(),     # listings change — date-stamp the snapshot
    "count": len(companies),
    "companies": companies,
}

with open("sec_companies.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, ensure_ascii=False)

# print(f"Saved {len(companies)} companies")

"""
What the result would look like:
json{
  "source": "https://www.sec.gov/files/company_tickers.json",
  "retrieved": "2026-06-19",
  "count": 10024,
  "companies": [
    { "name": "Apple Inc.", "ticker": "AAPL", "cik": "0000320193" },
    { "name": "Alphabet Inc.", "ticker": "GOOGL", "cik": "0001652044" }
  ]
}
"""