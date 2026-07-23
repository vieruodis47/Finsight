"""
experiments/rag/ingest_eval_corpus.py — ingest the eval corpus (N most recent
10-Ks per ticker) into RavenDB, measuring ingest cost per METRICS.md.

Unlike backend/scripts/bulk_ingest.py (latest filing only), this fetches the
last N annual filings per ticker so temporal questions have both fiscal years
indexed. Also registers XBRL metrics (FilingMetrics) so the graph variant has
its RDF substrate — measuring the graph's ingest path separately (it costs
zero LLM tokens by design; the cost is EDGAR fetch time).

Usage:
    python experiments/rag/ingest_eval_corpus.py --tickers AAPL,MSFT,NVDA --years 2
    python experiments/rag/ingest_eval_corpus.py --tickers AAPL --years 2 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / "backend" / ".env.python")
except ImportError:
    pass

from backend.data_extract.sec_client import (  # noqa: E402
    get_cik, get_filings, get_document_url, fetch_and_parse, get_company_facts,
    get_sic,
)
from backend.data_extract.sections import extract_sections  # noqa: E402
from backend.data_extract.embeddings import (  # noqa: E402
    ingest, check_already_indexed, DailyQuotaExceededError,
)
from backend.data_extract import facts as xbrl  # noqa: E402
from backend.data_extract.ratios import compute_ratios  # noqa: E402
from backend.data_extract.sectors import sic_to_sector, sector_label  # noqa: E402


def _sections_to_text(sections: dict) -> str:
    parts = []
    for key, text in sections.items():
        if text and key != "header":
            parts.append(f"## {key.replace('_', ' ').title()}\n\n{text}")
    return "\n\n".join(parts)


def _register_graph_metrics(ticker: str, cik: str, form: str,
                            accession: str, filing_date: str) -> None:
    """Populate FilingMetrics (graph substrate) from XBRL. Zero LLM calls."""
    from backend.graph.router import register_filing

    company_facts = get_company_facts(cik)
    income = xbrl.extract_income_statement(company_facts)
    balance = xbrl.extract_balance_sheet(company_facts)
    cash_flow = xbrl.extract_cash_flow(company_facts)
    ratios = compute_ratios(income, balance, cash_flow)
    income_by_year = xbrl.extract_income_multiyear(company_facts, n_years=5)
    balance_by_year = xbrl.extract_balance_multiyear(company_facts, n_years=5)
    cf_by_year = xbrl.extract_cash_flow_multiyear(company_facts, n_years=5)

    all_years = sorted(set(income_by_year) | set(balance_by_year) | set(cf_by_year),
                       reverse=True)
    metrics_by_year: dict = {}
    for year in all_years:
        inc = income_by_year.get(year, {}).get("income_statement", {})
        bal = balance_by_year.get(year, {}).get("balance_sheet", {})
        cf = cf_by_year.get(year, {}).get("cash_flow", {})
        yd: dict = {}
        if inc:
            yd["income_statement"] = inc
        if bal:
            yd["balance_sheet"] = bal
        if cf:
            yd["cash_flow"] = cf
        if inc or bal:
            r = compute_ratios(inc, bal, cf)
            if r:
                yd["computed_ratios"] = r
        if yd:
            metrics_by_year[year] = yd

    period_end = xbrl.target_period_end(company_facts) or ""
    try:
        sector = sector_label(sic_to_sector(get_sic(cik)))
    except Exception:
        sector = "Unknown"

    register_filing({
        "ticker": ticker,
        "form": form,
        "accession_number": accession,
        "filing_date": filing_date,
        "fiscal_year_end": period_end[:4] if period_end else "",
        "period_end": period_end,
        "sector": sector,
        "metrics": {
            "income_statement": income, "balance_sheet": balance,
            "cash_flow": cash_flow, "computed_ratios": ratios,
        },
        "metrics_by_year": metrics_by_year,
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True)
    ap.add_argument("--years", type=int, default=2, help="filings per ticker")
    ap.add_argument("--form", default="10-K")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="", help="ingest.json output path")
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    report = {"form": args.form, "filings": [], "vector": {}, "graph": {},
              "started_at": datetime.now(timezone.utc).isoformat()}

    vec_wall = 0.0
    graph_wall = 0.0
    total_chunks = 0

    for ticker in tickers:
        cik = get_cik(ticker)
        filings = get_filings(cik, form_type=args.form, limit=args.years)
        print(f"[ingest] {ticker}: {len(filings)} {args.form} filings found")
        for filing in filings:
            accession = filing["accession"]
            fdate = filing["date"]
            already, n = check_already_indexed(ticker, args.form, accession)
            if already:
                print(f"[ingest]   {accession} ({fdate}): already indexed ({n} chunks)")
                report["filings"].append({"ticker": ticker, "accession": accession,
                                          "date": fdate, "status": "skipped",
                                          "chunks": n})
                total_chunks += n
                continue
            if args.dry_run:
                print(f"[ingest]   {accession} ({fdate}): would ingest")
                report["filings"].append({"ticker": ticker, "accession": accession,
                                          "date": fdate, "status": "would_ingest"})
                continue

            url = get_document_url(cik, accession, filing["primary_document"])
            text = fetch_and_parse(url)
            sections = extract_sections(text)
            body = _sections_to_text(sections)
            print(f"[ingest]   {accession} ({fdate}): {len(body):,} chars — embedding…")
            t0 = time.perf_counter()
            try:
                chunks = ingest(ticker, args.form, body, url,
                                accession_number=accession, filing_date=fdate)
            except DailyQuotaExceededError:
                print("[ingest] DAILY EMBEDDING QUOTA EXHAUSTED — stopping cleanly.")
                report["quota_stop"] = True
                break
            dt = time.perf_counter() - t0
            vec_wall += dt
            total_chunks += chunks
            print(f"[ingest]   -> {chunks} chunks in {dt:.0f}s")
            report["filings"].append({"ticker": ticker, "accession": accession,
                                      "date": fdate, "status": "indexed",
                                      "chunks": chunks, "wall_clock_s": round(dt, 1)})
            time.sleep(1.0)

        # Graph substrate (one XBRL registration per ticker — covers all years)
        if not args.dry_run:
            t0 = time.perf_counter()
            try:
                latest = filings[0] if filings else {"accession": "", "date": ""}
                _register_graph_metrics(ticker, cik, args.form,
                                        latest["accession"], latest["date"])
                graph_wall += time.perf_counter() - t0
                print(f"[ingest]   graph metrics registered for {ticker}")
            except Exception as e:
                print(f"[ingest]   WARN graph metrics failed for {ticker}: {e}")
        time.sleep(1.0)

    report["vector"] = {"wall_clock_s": round(vec_wall, 1), "chunks": total_chunks,
                        "llm_tokens": 0,
                        "note": "embedding-model calls only; no generation tokens"}
    report["graph"] = {"wall_clock_s": round(graph_wall, 1), "llm_tokens": 0,
                       "note": "XBRL structured fetch; zero LLM/embedding calls"}
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    out_path = Path(args.out) if args.out else (
        _REPO / "experiments" / "rag" / "results" / "ingest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[ingest] report -> {out_path}")


if __name__ == "__main__":
    main()
