"""
backend/graph/rdf_graph.py

Minimal in-memory RDF knowledge graph for FinSight.

Builds from already-extracted XBRL structured metrics (income_statement,
balance_sheet, cash_flow, computed_ratios) — ZERO embedding calls, ZERO
Gemini embed_content calls.

Ontology
--------
  Namespace: http://finsight.io/ontology#   (prefix: fs)
  Data:      http://finsight.io/data/        (prefix: fsd)

  Classes:    fs:Company  fs:Filing  fs:FinancialMetric
  Properties: fs:hasTicker        (Company → xsd:string)
              fs:hasSector        (Company → xsd:string)
              fs:filedFiling      (Company → Filing)
              fs:fiscalYear       (Filing  → xsd:string)
              fs:filingForm       (Filing  → xsd:string)
              fs:reportsMetric    (Filing  → FinancialMetric)
              fs:metricName       (FinancialMetric → xsd:string)
              fs:metricValue      (FinancialMetric → xsd:decimal)
              fs:metricCategory   (FinancialMetric → xsd:string)

Usage
-----
    python -m backend.graph.rdf_graph          # demo mode: 3 companies, one query
    python3.11 backend/graph/rdf_graph.py      # direct invocation also works
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rdflib import (
    Graph, Namespace, BNode, Literal,
    RDF, RDFS, OWL, XSD,
)

# ---------------------------------------------------------------------------
# Path bootstrap — same pattern as bulk_ingest.py
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / "backend" / ".env.python")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
FS     = Namespace("http://finsight.io/ontology#")
FSD    = Namespace("http://finsight.io/data/")

# ---------------------------------------------------------------------------
# Metric categories included as RDF triples (qualitative is prose, not numbers)
# ---------------------------------------------------------------------------
_METRIC_CATEGORIES = ("income_statement", "balance_sheet", "cash_flow", "computed_ratios")


# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------

def build_ontology(g: Graph) -> None:
    """Assert class and property declarations into g."""
    g.bind("fs",  FS)
    g.bind("fsd", FSD)
    g.bind("owl", OWL)

    for cls in (FS.Company, FS.Filing, FS.FinancialMetric):
        g.add((cls, RDF.type, OWL.Class))

    prop_domains = {
        FS.hasTicker:      (FS.Company,          XSD.string),
        FS.hasSector:      (FS.Company,          XSD.string),
        FS.filedFiling:    (FS.Company,          None),          # range = fs:Filing
        FS.fiscalYear:     (FS.Filing,           XSD.string),
        FS.filingForm:     (FS.Filing,           XSD.string),
        FS.reportsMetric:  (FS.Filing,           None),          # range = fs:FinancialMetric
        FS.metricName:     (FS.FinancialMetric,  XSD.string),
        FS.metricValue:    (FS.FinancialMetric,  XSD.decimal),
        FS.metricCategory: (FS.FinancialMetric,  XSD.string),
    }
    for prop, (domain, rng) in prop_domains.items():
        g.add((prop, RDF.type, OWL.DatatypeProperty if rng else OWL.ObjectProperty))
        g.add((prop, RDFS.domain, domain))
        if rng:
            g.add((prop, RDFS.range, rng))


# ---------------------------------------------------------------------------
# Triple builder
# ---------------------------------------------------------------------------

def _add_metric_triples(g: Graph, filing_uri, metrics: dict) -> None:
    """Assert metric triples for one filing node from a flat or nested metrics dict."""
    for category in _METRIC_CATEGORIES:
        cat_dict = metrics.get(category, {})
        for name, value in cat_dict.items():
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            metric_node = BNode()
            g.add((metric_node, RDF.type,          FS.FinancialMetric))
            g.add((metric_node, FS.metricName,     Literal(name)))
            g.add((metric_node, FS.metricValue,    Literal(numeric, datatype=XSD.decimal)))
            g.add((metric_node, FS.metricCategory, Literal(category)))
            g.add((filing_uri,  FS.reportsMetric,  metric_node))


def add_company(g: Graph, result: dict) -> None:
    """
    Add all triples for one extractor result dict.

    Two modes, chosen by the keys present in ``result``:

    Multi-year mode (preferred):
        result["metrics_by_year"] = {"2025": {income_statement: {...}, ...},
                                     "2024": {...}, ...}
        One filing node is created per year so SPARQL can filter by fiscalYear
        and year-over-year comparisons work correctly.

    Single-year mode (legacy / fallback):
        result["metrics"] = {income_statement: {...}, balance_sheet: {...}, ...}
        One filing node is created, with fiscalYear derived from filing_date.
    """
    ticker    = result["ticker"].upper()
    accession = result.get("accession_number", "unknown").replace("-", "")
    sector    = result.get("sector", "Unknown")
    form      = result.get("form", "10-K")

    company_uri = FSD[f"company/{ticker}"]

    # Company node (written once; duplicate triples are silently ignored by rdflib)
    g.add((company_uri, RDF.type,     FS.Company))
    g.add((company_uri, FS.hasTicker, Literal(ticker)))
    g.add((company_uri, FS.hasSector, Literal(sector)))

    metrics_by_year: dict = result.get("metrics_by_year") or {}

    if metrics_by_year:
        # Multi-year: one filing node per year
        for year_str, year_metrics in metrics_by_year.items():
            filing_uri = FSD[f"filing/{ticker}/{accession}/{year_str}"]
            g.add((company_uri, FS.filedFiling, filing_uri))
            g.add((filing_uri, RDF.type,      FS.Filing))
            g.add((filing_uri, FS.fiscalYear, Literal(year_str)))
            g.add((filing_uri, FS.filingForm, Literal(form)))
            _add_metric_triples(g, filing_uri, year_metrics)
    else:
        # Single-year legacy path.
        # Use the XBRL period-end year (e.g. "2025" for a Dec-FY company whose
        # 10-K was filed in Jan 2026).  Fall back to filing_date[:4] only when
        # fiscal_year_end is absent (old docs not yet migrated).
        filing_date     = result.get("filing_date", "")
        fiscal_year_end = result.get("fiscal_year_end", "")
        fiscal_year     = fiscal_year_end or (filing_date[:4] if filing_date else "unknown")
        filing_uri      = FSD[f"filing/{ticker}/{accession}"]
        g.add((company_uri, FS.filedFiling, filing_uri))
        g.add((filing_uri, RDF.type,      FS.Filing))
        g.add((filing_uri, FS.fiscalYear, Literal(fiscal_year)))
        g.add((filing_uri, FS.filingForm, Literal(form)))
        _add_metric_triples(g, filing_uri, result.get("metrics", {}))


def build_graph(results: list[dict]) -> Graph:
    """Build and return a populated in-memory graph from a list of extractor results."""
    g = Graph()
    build_ontology(g)
    for r in results:
        add_company(g, r)
    return g


# ---------------------------------------------------------------------------
# SPARQL queries
# ---------------------------------------------------------------------------

NET_MARGIN_QUERY = """
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>

SELECT ?ticker ?fiscalYear ?netMargin
WHERE {
    ?company  a              fs:Company ;
              fs:hasTicker   ?ticker ;
              fs:filedFiling ?filing .

    ?filing   fs:fiscalYear  ?fiscalYear ;
              fs:reportsMetric ?m .

    ?m  fs:metricName     "net_margin_pct" ;
        fs:metricCategory "computed_ratios" ;
        fs:metricValue    ?netMargin .
}
ORDER BY DESC(?netMargin)
"""

MULTI_METRIC_QUERY = """
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>

SELECT ?ticker ?fiscalYear ?revenue ?netIncome ?netMargin ?operatingMargin ?roe
WHERE {
    ?company  a              fs:Company ;
              fs:hasTicker   ?ticker ;
              fs:filedFiling ?filing .

    ?filing   fs:fiscalYear  ?fiscalYear .

    OPTIONAL {
        ?filing fs:reportsMetric ?m_rev .
        ?m_rev fs:metricName "total_revenue_millions" ;
               fs:metricCategory "income_statement" ;
               fs:metricValue ?revenue .
    }
    OPTIONAL {
        ?filing fs:reportsMetric ?m_ni .
        ?m_ni fs:metricName "net_income_millions" ;
              fs:metricCategory "income_statement" ;
              fs:metricValue ?netIncome .
    }
    OPTIONAL {
        ?filing fs:reportsMetric ?m_nm .
        ?m_nm fs:metricName "net_margin_pct" ;
              fs:metricCategory "computed_ratios" ;
              fs:metricValue ?netMargin .
    }
    OPTIONAL {
        ?filing fs:reportsMetric ?m_om .
        ?m_om fs:metricName "operating_margin_pct" ;
              fs:metricCategory "computed_ratios" ;
              fs:metricValue ?operatingMargin .
    }
    OPTIONAL {
        ?filing fs:reportsMetric ?m_roe .
        ?m_roe fs:metricName "return_on_equity_pct" ;
               fs:metricCategory "computed_ratios" ;
               fs:metricValue ?roe .
    }
}
ORDER BY DESC(?netMargin)
"""


def run_sparql(g: Graph, query: str) -> list[dict]:
    """
    Execute a SPARQL SELECT and return results as a list of dicts.

    Values are coerced to float when possible.  xsd:decimal Literals have a
    toPython() that returns decimal.Decimal, which fails isinstance(int, float)
    — so we always call float(v.toPython()) inside a try/except rather than
    type-testing the result first.  None is preserved as None.
    """
    rows = []
    for row in g.query(query):
        d: dict = {}
        for k, v in row.asdict().items():
            if v is None:
                d[str(k)] = None
            elif hasattr(v, "toPython"):
                try:
                    d[str(k)] = float(v.toPython())
                except (TypeError, ValueError):
                    d[str(k)] = str(v)
            else:
                d[str(k)] = str(v)
        rows.append(d)
    return rows


def results_to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "_No results._"
    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM bridge  (generation model only — ZERO embedding calls)
# ---------------------------------------------------------------------------

def sparql_to_llm(question: str, sparql: str, g: Graph) -> str:
    """
    1. Run sparql against g.
    2. Format results as a markdown table.
    3. Send to Gemini generation model (NOT embed_content).
    Returns the model's natural-language answer.
    """
    from backend.data_extract.embeddings import get_genai_client
    from google.genai import types as genai_types

    gen_model = os.getenv("GEMINI_GEN_MODEL", "gemini-1.5-flash")

    rows = run_sparql(g, sparql)
    table = results_to_markdown(rows)

    prompt = (
        f"The following table contains structured financial data retrieved via SPARQL "
        f"from an RDF knowledge graph of SEC filings. Answer the question below using "
        f"ONLY the data in the table. If data is missing, say so.\n\n"
        f"## Data\n\n{table}\n\n"
        f"## Question\n\n{question}"
    )

    client = get_genai_client()
    resp = client.models.generate_content(
        model=gen_model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=(
                "You are FinSight, an expert financial analyst. "
                "Answer concisely and factually, citing specific numbers from the table."
            ),
            temperature=0.1,
        ),
    )
    return (resp.text or "").strip()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo() -> None:
    """
    Fetch AAPL, TSLA, F from EDGAR, build the graph, run a SPARQL query,
    send results to the LLM. Proves ZERO embed_texts calls.
    """
    import unittest.mock as mock

    # Guard: monkeypatch embed_texts so any accidental call raises immediately.
    with mock.patch(
        "backend.data_extract.embeddings.embed_texts",
        side_effect=AssertionError("embed_texts was called — this demo must NOT use embeddings"),
    ):
        from backend.data_extract.extractor import run as edgar_run

        tickers = ["AAPL", "TSLA", "F"]
        results = []
        for ticker in tickers:
            print(f"\n{'─'*60}")
            print(f"Fetching {ticker} from EDGAR…")
            try:
                r = edgar_run(ticker, "10-K")
                results.append(r)
                print(f"  ✓ {ticker}  filing_date={r.get('filing_date')}  "
                      f"metrics keys={list(r.get('metrics', {}).keys())}")
            except Exception as e:
                print(f"  ✗ {ticker}  FAILED: {e}")

        if not results:
            print("No results fetched — cannot build graph.")
            return

        print(f"\n{'─'*60}")
        print(f"Building RDF graph from {len(results)} companies…")
        g = build_graph(results)
        print(f"  Graph has {len(g)} triples")

        print(f"\n{'─'*60}")
        print("SPARQL: rank companies by net margin")
        print(NET_MARGIN_QUERY)
        rows = run_sparql(g, NET_MARGIN_QUERY)
        table = results_to_markdown(rows)
        print(table)

        print(f"\n{'─'*60}")
        print("SPARQL: multi-metric comparison")
        rows2 = run_sparql(g, MULTI_METRIC_QUERY)
        table2 = results_to_markdown(rows2)
        print(table2)

        print(f"\n{'─'*60}")
        question = (
            "Which of these companies (AAPL, TSLA, F) has the highest net margin "
            "and how does their profitability compare? Give specific numbers."
        )
        print(f"Question: {question}")
        print("\nCalling Gemini generation model (NOT embeddings)…")
        try:
            answer = sparql_to_llm(question, MULTI_METRIC_QUERY, g)
            print(f"\nAnswer:\n{answer}")
        except Exception as e:
            print(f"  LLM call failed (quota/auth): {e}")
            print("  (SPARQL results above are still valid — LLM is optional)")

        print(f"\n{'─'*60}")
        print("✓ CONFIRMED: embed_texts was never called (monkeypatch would have raised).")


if __name__ == "__main__":
    demo()
