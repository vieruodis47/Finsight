"""
Main extraction pipeline.

Numbers come from SEC's XBRL companyfacts API (standardized, works for any
filer); narrative sections come from the filing document.

Run from the repo root:
    python -m backend.data_extract.extractor
or import ``run`` from the FastAPI app (see app.py).
"""

import json

from .sec_client import (get_cik, get_filings, get_document_url,
                         fetch_and_parse, get_company_facts, get_sic)
from .sections import extract_sections
from . import facts as xbrl
from .ratios import compute_ratios
from .text_metrics import extract_qualitative
from .sectors import sic_to_sector, sector_label


def extract_all_metrics(company_facts: dict, sections: dict) -> dict:
    """Standardized numbers from XBRL + qualitative signals from the narrative."""
    try:
        income    = xbrl.extract_income_statement(company_facts)
        balance   = xbrl.extract_balance_sheet(company_facts)
        cash_flow = xbrl.extract_cash_flow(company_facts)
        ratios    = compute_ratios(income, balance, cash_flow)
        # Qualitative parsing is heuristic; never let it sink a run whose
        # numbers already succeeded.
        try:
            qualitative = extract_qualitative(sections)
        except Exception as e:
            print(f"  Warning: qualitative extraction failed; continuing without it: {e}")
            qualitative = {}
        return {
            "income_statement": income,
            "balance_sheet": balance,
            "cash_flow": cash_flow,
            "computed_ratios": ratios,
            "qualitative": qualitative,
        }
    except Exception as e:
        print(f"Error extracting all metrics: {e}")
        raise


def run(ticker: str, form_type: str = "10-K") -> dict:
    """Full pipeline: ticker symbol -> structured JSON."""
    try:
        print(f"\n[1/5] Looking up CIK for {ticker}...")
        cik = get_cik(ticker)
        sector = sector_label(sic_to_sector(get_sic(cik)))

        print(f"[2/5] Fetching {form_type} filings...")
        filings = get_filings(cik, form_type=form_type, limit=1)
        if not filings:
            raise ValueError(f"No {form_type} filings found for {ticker}")
        filing = filings[0]

        print(f"[3/5] Fetching and parsing document (narrative)...")
        url = get_document_url(cik, filing["accession"], filing["primary_document"])
        text = fetch_and_parse(url)
        sections = extract_sections(text)

        print(f"[4/5] Fetching XBRL company facts (numbers)...")
        company_facts = get_company_facts(cik)

        print(f"[5/5] Building metrics...")
        metrics = extract_all_metrics(company_facts, sections)

        # Derive fiscal year from the XBRL period-end date, not the filing date.
        period_end = xbrl.target_period_end(company_facts) or ""
        fiscal_year_end = period_end[:4] if period_end else filing["date"][:4]

        # Multi-year metrics — one entry per fiscal year for YoY comparisons.
        income_by_year    = xbrl.extract_income_multiyear(company_facts, n_years=5)
        balance_by_year   = xbrl.extract_balance_multiyear(company_facts, n_years=5)
        cash_flow_by_year = xbrl.extract_cash_flow_multiyear(company_facts, n_years=5)
        all_years = sorted(
            set(income_by_year) | set(balance_by_year) | set(cash_flow_by_year),
            reverse=True,
        )
        metrics_by_year: dict = {}
        for year in all_years:
            income  = income_by_year.get(year, {}).get("income_statement", {})
            balance = balance_by_year.get(year, {}).get("balance_sheet", {})
            cf      = cash_flow_by_year.get(year, {}).get("cash_flow", {})
            year_data: dict = {}
            if income:
                year_data["income_statement"] = income
            if balance:
                year_data["balance_sheet"] = balance
            if cf:
                year_data["cash_flow"] = cf
            if income or balance:
                ratios = compute_ratios(income, balance, cf)
                if ratios:
                    year_data["computed_ratios"] = ratios
            if year_data:
                metrics_by_year[year] = year_data

        return {
            "ticker": ticker.upper(),
            "form": form_type,
            "filing_date": filing["date"],
            "fiscal_year_end": fiscal_year_end,
            "period_end": period_end,
            "accession_number": filing["accession"],
            "source_url": url,
            "char_count": len(text),
            "metrics": metrics,
            "metrics_by_year": metrics_by_year,
            "sections": sections,
            "sector": sector,
        }
        
    except Exception as e:
        print(f"Error in run pipeline for {ticker} {form_type}: {e}")
        raise


if __name__ == "__main__":
    import sys

    ticker = sys.argv[1] if len(sys.argv) > 1 else None     # Required argument
    form   = sys.argv[2] if len(sys.argv) > 2 else "10-K"   # Optional, defaults to 10-K

    if not ticker:
        print("Error: Ticker symbol is required.")
        sys.exit(1)

    data = run(ticker, form)

    output_file = f"{ticker}_{form.replace('-', '')}.json"
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved -> {output_file}")
    print(f"Sections found:  {list(data['sections'].keys())}")
    print(f"\nMetrics summary:")
    for category, values in data["metrics"].items():
        if values:
            print(f"  {category}: {len(values)} fields extracted")
    print(f"\nTotal characters: {data['char_count']:,}")
