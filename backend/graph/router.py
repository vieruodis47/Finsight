"""
backend/graph/router.py

GraphRAG router for FinSight.

Routes each chat question to the appropriate retrieval path:
  - GRAPH  (SPARQL over in-memory RDF graph)  for structured / metric questions
  - VECTOR (existing RavenDB RAG in rag.py)   for narrative / qualitative questions
  - BOTH   when the question needs numbers AND prose context

Routing uses keyword/pattern heuristics — no LLM call, no embeddings.
Rationale: the structural-vs-narrative split maps cleanly to surface patterns
("compare", "net margin", "rank" → GRAPH; "risk factors", "MD&A", "describe"
→ VECTOR). An extra LLM routing call would consume generation-model quota on
every question for marginal accuracy gain.

GRAPH path is zero-embedding: the RDF graph is built from XBRL structured
metrics (income_statement, balance_sheet, cash_flow, computed_ratios) via
register_filing(). Gemini is invoked only for final answer generation.

Startup behaviour: the in-memory graph starts empty. It is populated each time
/extract runs and calls register_filing(). On server restart, users need to
re-extract their filings for the graph path to work; the vector path is always
available independently via RavenDB.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Optional

from rdflib import Graph

from .rdf_graph import build_graph, run_sparql, results_to_markdown, MULTI_METRIC_QUERY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory graph registry
# ---------------------------------------------------------------------------

_lock: threading.Lock = threading.Lock()
_registry: dict[str, dict] = {}   # ticker → full extractor result dict
_graph: Optional[Graph] = None
_dirty: bool = False


def register_filing(result: dict) -> None:
    """
    Register one extractor result dict in the graph.
    Called from /extract after run() succeeds. Non-fatal — caller catches exceptions.

    Also persists structured metrics to the FilingMetrics RavenDB collection so
    the graph can be rebuilt on the next server startup without a fresh /extract.
    Only the four numeric categories are stored (income_statement, balance_sheet,
    cash_flow, computed_ratios); the qualitative category is prose and is not
    used by SPARQL queries.
    """
    ticker = (result.get("ticker") or "").upper()
    if not ticker:
        return
    global _dirty
    with _lock:
        _registry[ticker] = result
        _dirty = True
    logger.info("Graph registry: registered %s (%d total)", ticker, len(_registry))

    # Persist metrics to RavenDB (non-fatal).
    try:
        from ..data_extract.embeddings import save_filing_metrics
        graph_metrics = {
            k: v for k, v in result.get("metrics", {}).items()
            if k in ("income_statement", "balance_sheet", "cash_flow", "computed_ratios")
        }
        save_filing_metrics(
            ticker=ticker,
            form=result.get("form", "10-K"),
            accession_number=result.get("accession_number", ""),
            filing_date=result.get("filing_date", ""),
            sector=result.get("sector", "Unknown"),
            metrics=graph_metrics,
            metrics_by_year=result.get("metrics_by_year"),
        )
    except Exception as e:
        logger.warning("Could not persist FilingMetrics for %s: %s", ticker, e)


def _get_graph() -> Graph:
    global _graph, _dirty
    with _lock:
        if _graph is None or _dirty:
            _graph = build_graph(list(_registry.values()))
            _dirty = False
        return _graph


def _graph_tickers() -> set[str]:
    with _lock:
        return set(_registry.keys())


# ---------------------------------------------------------------------------
# Startup rehydration
# ---------------------------------------------------------------------------

def rebuild_graph_from_ravendb() -> int:
    """
    Reload the in-memory RDF graph from persisted FilingMetrics documents.

    Called once from app._lifespan on every server startup.  Returns the number
    of companies loaded.  If RavenDB has no FilingMetrics yet (first boot after
    the fix is deployed, or a fresh DB), kicks off a one-time background migration
    that fetches XBRL-only data from SEC for each already-indexed filing.
    """
    try:
        from ..data_extract.embeddings import load_all_filing_metrics
        docs = load_all_filing_metrics()
    except Exception as e:
        logger.warning("Could not load FilingMetrics from RavenDB: %s", e)
        return 0

    # Check whether any docs are missing multi-year data (old format from before the
    # metrics_by_year field was added).  If so, re-run migration for those tickers.
    needs_upgrade = [d for d in docs if not getattr(d, "metrics_by_year", None)]
    if not docs or needs_upgrade:
        reason = "no FilingMetrics found" if not docs else (
            f"{len(needs_upgrade)}/{len(docs)} docs lack multi-year data"
        )
        logger.info(
            "Scheduling XBRL migration (%s) — fetches structured data only, zero embeddings",
            reason,
        )
        _migrate_from_manifests_background()
        if not docs:
            return 0
        # Load whatever valid multi-year docs exist now; migration will add the rest.

    loaded = 0
    for doc in docs:
        by_year = getattr(doc, "metrics_by_year", None) or {}
        try:
            result = {
                "ticker":           doc.ticker,
                "form":             doc.form,
                "accession_number": doc.accession_number,
                "filing_date":      doc.filing_date,
                "sector":           doc.sector,
                "metrics":          doc.metrics if isinstance(doc.metrics, dict) else {},
                "metrics_by_year":  by_year if isinstance(by_year, dict) else {},
            }
            register_filing(result)
            loaded += 1
        except Exception as e:
            logger.warning("Could not register %s from FilingMetrics: %s", getattr(doc, "ticker", "?"), e)

    logger.info("Graph rebuilt from RavenDB: %d companies loaded (migration running in background)", loaded)
    return loaded


def _migrate_from_manifests_background() -> None:
    """Spawn the one-time XBRL migration in a daemon thread so startup is non-blocking."""
    import threading
    t = threading.Thread(
        target=_migrate_from_manifests,
        daemon=True,
        name="graph-xbrl-migration",
    )
    t.start()


def _migrate_from_manifests() -> None:
    """
    One-time migration: build FilingMetrics from IngestManifests + SEC XBRL.

    For each IngestManifest that has no corresponding FilingMetrics document:
    1.  Derive the CIK from the accession_number prefix (e.g. "0000320193-25-000079"
        → CIK "0000320193").
    2.  Fetch the companyfacts JSON from SEC EDGAR — one HTTPS call per company,
        no HTML parsing, zero embedding calls.
    3.  Run the same facts.py / ratios.py pipeline as the regular /extract flow.
    4.  Save a FilingMetrics document and call register_filing() to populate the
        in-memory graph immediately.

    This runs exactly once: on the next startup, FilingMetrics exist and
    rebuild_graph_from_ravendb() loads them directly, skipping this branch.
    """
    import time

    logger.info("graph-xbrl-migration: starting one-time XBRL migration")

    try:
        from ..data_extract.embeddings import load_all_ingest_manifests, load_all_filing_metrics
        from ..data_extract.sec_client import get_company_facts
        from ..data_extract import facts as xbrl
        from ..data_extract.ratios import compute_ratios
    except Exception as e:
        logger.error("graph-xbrl-migration: import error — %s", e)
        return

    # Build the set of tickers that already have multi-year data — skip those.
    existing_metrics = load_all_filing_metrics()
    skip_tickers = {
        m.ticker.upper() for m in existing_metrics
        if getattr(m, "metrics_by_year", None)
    }

    manifests = load_all_ingest_manifests()
    if not manifests:
        logger.info("graph-xbrl-migration: no IngestManifests found, nothing to migrate")
        return

    logger.info("graph-xbrl-migration: %d manifests, %d already fully migrated",
                len(manifests), len(skip_tickers))

    migrated = 0
    for manifest in manifests:
        ticker = (manifest.ticker or "").upper()
        if not ticker or ticker in skip_tickers:
            continue

        accession = manifest.accession_number or ""

        # Resolve the company's CIK from its ticker — the leading segment of the
        # accession_number is the *filer's* CIK (often a filing agent like Workiva),
        # not the company's.  Use the local SEC registry for a fast local lookup;
        # fall back to a live SEC API call only if the ticker isn't in the registry.
        try:
            try:
                from ..analysis.metrics import COMPANIES as _SEC_COMPANIES
                cik = _SEC_COMPANIES.get(ticker)
            except Exception:
                cik = None
            if not cik:
                from ..data_extract.sec_client import get_cik
                cik = get_cik(ticker)
        except Exception as e:
            logger.warning("graph-xbrl-migration: cannot resolve CIK for %s — %s", ticker, e)
            continue

        try:
            logger.info("graph-xbrl-migration: fetching XBRL for %s (CIK %s)", ticker, cik)
            facts = get_company_facts(cik)

            # Single-year snapshot (most recent) for backward-compatible metrics field.
            income    = xbrl.extract_income_statement(facts)
            balance   = xbrl.extract_balance_sheet(facts)
            cash_flow = xbrl.extract_cash_flow(facts)
            ratios    = compute_ratios(income, balance, cash_flow)

            # Multi-year income history — enables YoY SPARQL queries without
            # re-fetching from EDGAR on each restart.
            metrics_by_year = xbrl.extract_income_multiyear(facts, n_years=5)

            result = {
                "ticker":           ticker,
                "form":             manifest.form or "10-K",
                "accession_number": accession,
                "filing_date":      manifest.filing_date or "",
                "sector":           "Unknown",   # not critical for graph queries
                "metrics": {
                    "income_statement": income,
                    "balance_sheet":    balance,
                    "cash_flow":        cash_flow,
                    "computed_ratios":  ratios,
                },
                "metrics_by_year": metrics_by_year,
            }

            # register_filing() updates the in-memory registry AND persists FilingMetrics.
            register_filing(result)
            skip_tickers.add(ticker)
            migrated += 1
            logger.info("graph-xbrl-migration: migrated %s (%d years)", ticker, len(metrics_by_year))

        except Exception as e:
            logger.warning("graph-xbrl-migration: failed for %s — %s", ticker, e)

        # 1-second pause between companies to respect the SEC rate limit.
        time.sleep(1.0)

    logger.info("graph-xbrl-migration: complete — migrated %d companies", migrated)


# ---------------------------------------------------------------------------
# Question classifier — keyword/pattern heuristics
# ---------------------------------------------------------------------------

_METRIC_KW = re.compile(
    r"\b(revenue|income|profit|loss|margin|ebitda|eps|earnings per share"
    r"|operating income|net income|gross profit|cash flow|capex|roe|roa"
    r"|equity|assets|liabilities|ratio|free cash|fcf|return on"
    r"|net margin|operating margin|gross margin|effective tax|tax rate"
    r"|total revenue|total assets|market cap|debt|long.term debt"
    r"|earnings|profitab|valuation)\b",
    re.IGNORECASE,
)

_STRUCTURED_KW = re.compile(
    r"\b(compare|versus|vs\.?|rank|highest|lowest|best|worst|which company"
    r"|cross.company|side.by.side|benchmark)\b",
    re.IGNORECASE,
)

_NARRATIVE_KW = re.compile(
    r"\b(risk factor|summarize|summary|business overview|strategy|management"
    r"|md&a|management discussion|outlook|guidance|segment|geographic"
    r"|supply chain|competition|competitive|regulatory|cybersecurity|litigation"
    r"|forward.looking|china|international|employee|headcount|product"
    r"|service offering|what does the|describe|explain|tell me about"
    r"|according to|narrative|qualitative|disclose|disclosure)\b",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"\b(fy|fiscal|year)?\s*20\d{2}\b", re.IGNORECASE)


def classify_question(question: str) -> str:
    """
    Return one of: 'graph', 'vector', 'both'.

    Decision logic:
      - Narrative trigger with no structure/year  → vector (or both if metric mentioned)
      - Narrative + structured/year               → both
      - Structured comparison or metric + year    → graph
      - Metric alone (no narrative)               → graph
      - No clear signal                           → vector (safer: prose fallback)
    """
    has_metric     = bool(_METRIC_KW.search(question))
    has_structured = bool(_STRUCTURED_KW.search(question))
    has_narrative  = bool(_NARRATIVE_KW.search(question))
    has_year       = bool(_YEAR_RE.search(question))

    if has_narrative:
        if has_structured or has_year:
            return "both"
        if has_metric:
            return "both"
        return "vector"

    if has_structured or (has_metric and has_year):
        return "graph"

    if has_metric:
        return "graph"

    return "vector"


# ---------------------------------------------------------------------------
# Ticker extraction
# ---------------------------------------------------------------------------

_ENGLISH_STOP = frozenset({
    # Question / pronoun words
    "WHAT", "WHEN", "WHERE", "WHICH", "THAT", "THIS", "THEN", "BOTH", "EACH",
    "WHO",  "ALL",  "ANY",  "HOW",  "ARE",  "WAS",  "ITS",  "HAS",  "HAD",
    "DOES", "DID",  "CAN",  "WILL", "HAVE", "BEEN", "NOT",  "BUT",  "THEM",
    "THEY", "VERY", "EVEN", "BACK",
    # Prepositions / conjunctions / articles
    "AND", "FOR", "THE", "FROM", "WITH", "INTO", "OVER", "MOST", "SOME",
    "SUCH", "MORE", "ALSO", "ONLY", "THAN", "JUST", "HERE", "THERE",
    "THESE", "THOSE", "SINCE", "WHILE", "AFTER", "BELOW", "ABOVE",
    "TOTAL", "OTHER", "EVERY", "GIVEN", "BEING", "ABOUT", "WOULD",
    "COULD", "SHOULD", "FIRST", "LAST", "NEXT", "SAME",
    # Common short English words (not tickers)
    "TWO", "MAY", "SAY", "HIS", "HER", "OUR", "NEW", "ONE", "OWN",
    "PUT", "SET", "OLD", "TOO", "PER", "OFF", "YEAR", "LOOK", "KNOW",
    "TAKE", "MAKE", "COME", "WANT", "GOOD", "MUCH", "TELL", "USE", "GET",
    "OUT", "HIGH", "LOW", "LONG", "WELL", "SHOW", "FIND", "GIVE", "PICK",
    "RANK", "LIST", "NAME", "BEST", "BACK",
    # Financial terms that look like tickers but aren't
    "NET",  "CASH", "DEBT", "LOSS", "GAIN", "COST", "RATE", "RISK",
    "FAIR", "BOOK", "REAL", "SALE", "GROW",
    # Financial / regulatory abbreviations
    "SEC", "IRS", "CEO", "CFO", "COO", "EVP", "SVP", "IPO", "EPS",
    "GAAP", "XBRL", "USD", "FY", "YOY", "QOQ", "LTM", "NTM", "EDGAR",
})

_COMPANY_NAMES: dict[str, str] = {
    "apple":     "AAPL",
    "tesla":     "TSLA",
    "microsoft": "MSFT",
    "amazon":    "AMZN",
    "google":    "GOOG",
    "alphabet":  "GOOG",
    "meta":      "META",
    "nvidia":    "NVDA",
    "ford":      "F",
    "netflix":   "NFLX",
    "salesforce": "CRM",
    "berkshire": "BRK",
    "jp morgan": "JPM",
    "jpmorgan":  "JPM",
    "walmart":   "WMT",
}


def _extract_tickers(question: str) -> list[str]:
    """
    Extract ticker symbols from a question.
    Checks uppercase letter sequences (2-5 chars) and common company names.
    Returns tickers in mention order, deduplicated.
    """
    seen: set[str] = set()
    result: list[str] = []

    for word in re.findall(r"\b([A-Z]{2,5})\b", question.upper()):
        if word not in _ENGLISH_STOP and word not in seen:
            seen.add(word)
            result.append(word)

    q_lower = question.lower()
    for name, ticker in _COMPANY_NAMES.items():
        if name in q_lower and ticker not in seen:
            seen.add(ticker)
            result.append(ticker)

    return result


# ---------------------------------------------------------------------------
# Metric name detection
# ---------------------------------------------------------------------------

_METRIC_MAP: dict[str, str] = {
    "total revenue":       "total_revenue_millions",
    "revenue":             "total_revenue_millions",
    "net income":          "net_income_millions",
    "net margin":          "net_margin_pct",
    "operating margin":    "operating_margin_pct",
    "gross margin":        "gross_margin_pct",
    "operating income":    "operating_income_millions",
    "return on equity":    "return_on_equity_pct",
    "roe":                 "return_on_equity_pct",
    "earnings per share":  "eps_diluted",
    "eps":                 "eps_diluted",
    "free cash flow":      "free_cash_flow_millions",
    "free cash":           "free_cash_flow_millions",
    "fcf":                 "free_cash_flow_millions",
    "cash flow":           "operating_cash_flow_millions",
    "capex":               "capex_millions",
    "total assets":        "total_assets_millions",
    # D/E entries must appear before the bare "debt" entry so that
    # _detect_metric (longest-first scan) matches the specific ratio phrase
    # before falling through to the raw long-term debt figure.
    "debt to equity ratio": "debt_to_equity",
    "debt to equity":       "debt_to_equity",
    "debt-to-equity ratio": "debt_to_equity",
    "debt-to-equity":       "debt_to_equity",
    "debt equity ratio":    "debt_to_equity",
    "leverage ratio":       "debt_to_equity",
    "d/e ratio":            "debt_to_equity",
    "d/e":                  "debt_to_equity",
    "long-term debt":       "long_term_debt_millions",
    "long term debt":       "long_term_debt_millions",
    "debt":                 "long_term_debt_millions",
    "gross profit":         "gross_margin_millions",
}


def _detect_metric(question: str) -> Optional[str]:
    """Return the most specific metric name found in the question, or None."""
    q_lower = question.lower()
    for phrase in sorted(_METRIC_MAP, key=len, reverse=True):
        if phrase in q_lower:
            return _METRIC_MAP[phrase]
    return None


# ---------------------------------------------------------------------------
# SPARQL query templates
# ---------------------------------------------------------------------------

def _sparql_single_metric_all(metric: str) -> str:
    return f"""
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>
SELECT ?ticker ?fiscalYear ?value
WHERE {{
    ?co  a fs:Company ; fs:hasTicker ?ticker ; fs:filedFiling ?f .
    ?f   fs:fiscalYear ?fiscalYear ; fs:reportsMetric ?m .
    ?m   fs:metricName "{metric}" ; fs:metricValue ?value .
}}
ORDER BY DESC(?value)
"""


def _sparql_two_company_single_metric(t1: str, t2: str, metric: str) -> str:
    return f"""
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>
SELECT ?ticker ?fiscalYear ?value
WHERE {{
    ?co  a fs:Company ; fs:hasTicker ?ticker ; fs:filedFiling ?f .
    ?f   fs:fiscalYear ?fiscalYear ; fs:reportsMetric ?m .
    ?m   fs:metricName "{metric}" ; fs:metricValue ?value .
    FILTER(?ticker IN ("{t1}", "{t2}"))
}}
ORDER BY ?ticker ?fiscalYear
"""


def _sparql_two_company_multi_metric(t1: str, t2: str) -> str:
    return f"""
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>
SELECT ?ticker ?fiscalYear ?revenue ?netIncome ?netMargin ?operatingMargin ?roe
WHERE {{
    ?co  a fs:Company ; fs:hasTicker ?ticker ; fs:filedFiling ?f .
    ?f   fs:fiscalYear ?fiscalYear .
    OPTIONAL {{
        ?f fs:reportsMetric ?m1 .
        ?m1 fs:metricName "total_revenue_millions" ; fs:metricValue ?revenue .
    }}
    OPTIONAL {{
        ?f fs:reportsMetric ?m2 .
        ?m2 fs:metricName "net_income_millions" ; fs:metricValue ?netIncome .
    }}
    OPTIONAL {{
        ?f fs:reportsMetric ?m3 .
        ?m3 fs:metricName "net_margin_pct" ; fs:metricValue ?netMargin .
    }}
    OPTIONAL {{
        ?f fs:reportsMetric ?m4 .
        ?m4 fs:metricName "operating_margin_pct" ; fs:metricValue ?operatingMargin .
    }}
    OPTIONAL {{
        ?f fs:reportsMetric ?m5 .
        ?m5 fs:metricName "return_on_equity_pct" ; fs:metricValue ?roe .
    }}
    FILTER(?ticker IN ("{t1}", "{t2}"))
}}
ORDER BY ?ticker ?fiscalYear
"""


def _sparql_single_company(ticker: str, metric: str) -> str:
    return f"""
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>
SELECT ?ticker ?fiscalYear ?value
WHERE {{
    ?co  a fs:Company ; fs:hasTicker ?ticker ; fs:filedFiling ?f .
    ?f   fs:fiscalYear ?fiscalYear ; fs:reportsMetric ?m .
    ?m   fs:metricName "{metric}" ; fs:metricValue ?value .
    FILTER(?ticker = "{ticker}")
}}
ORDER BY DESC(?fiscalYear)
"""


def _sparql_single_company_year(ticker: str, year: str, metric: str) -> str:
    return f"""
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>
SELECT ?ticker ?fiscalYear ?value
WHERE {{
    ?co  a fs:Company ; fs:hasTicker ?ticker ; fs:filedFiling ?f .
    ?f   fs:fiscalYear ?fiscalYear ; fs:reportsMetric ?m .
    ?m   fs:metricName "{metric}" ; fs:metricValue ?value .
    FILTER(?ticker = "{ticker}" && ?fiscalYear = "{year}")
}}
"""


def _build_sparql(question: str, tickers: list[str]) -> str:
    metric = _detect_metric(question)
    year_match = _YEAR_RE.search(question)
    year = re.search(r"20\d{2}", year_match.group()).group() if year_match else None

    # Detect multi-year questions (e.g. "from FY2023 to FY2024", "in 2023 and 2024").
    # When 2+ distinct calendar years appear, return all available years for the
    # company so the LLM can compute the year-over-year change.
    all_years = list(dict.fromkeys(re.findall(r"20\d{2}", question)))  # order-preserving dedupe
    is_multiyear = len(all_years) > 1

    if len(tickers) >= 2:
        t1, t2 = tickers[0], tickers[1]
        return (
            _sparql_two_company_single_metric(t1, t2, metric)
            if metric
            else _sparql_two_company_multi_metric(t1, t2)
        )

    if tickers:
        t = tickers[0]
        if metric:
            # Multi-year question: return all years so LLM can see both endpoints.
            # Single-year question: filter to the requested year for precision.
            if is_multiyear:
                return _sparql_single_company(t, metric)
            elif year:
                return _sparql_single_company_year(t, year, metric)
            else:
                return _sparql_single_company(t, metric)
        return MULTI_METRIC_QUERY  # broad fallback for single-ticker general query

    if metric:
        return _sparql_single_metric_all(metric)

    return MULTI_METRIC_QUERY


# ---------------------------------------------------------------------------
# Graph answer generation (ZERO embeddings)
# ---------------------------------------------------------------------------

_GRAPH_SYSTEM = (
    "You are FinSight, an expert financial analyst. "
    "Answer concisely and factually using ONLY the data table provided. "
    "Cite specific numbers. Format percentages to one decimal place; "
    "dollar amounts in millions as 'M' (e.g. $391,000M = $391B). "
    "If data is missing from the table, say so explicitly."
)


def _answer_from_graph(question: str) -> tuple[str, bool]:
    """
    Run SPARQL against the in-memory graph and generate a grounded NL answer.
    Returns (answer, had_data). No embedding calls.
    """
    from ..data_extract.embeddings import get_genai_client
    from google.genai import types as genai_types

    g = _get_graph()
    if len(g) == 0:
        return "", False

    raw_tickers = _extract_tickers(question)
    known = _graph_tickers()

    if not known:
        return "", False

    # Filter extracted words to tickers that are actually registered.
    available = [t for t in raw_tickers if t in known]

    # If the user mentioned specific companies but none are in the graph,
    # fall back to vector — we don't have their data.
    # If no companies were mentioned (e.g. "which company has highest revenue"),
    # proceed with all companies (available=[]) and let SPARQL return all rows.
    if raw_tickers and not available:
        logger.info("Graph missing tickers %s (have %s) — falling back", raw_tickers, known)
        return "", False

    metric = _detect_metric(question)
    sparql = _build_sparql(question, available)
    try:
        rows = run_sparql(g, sparql)
    except Exception as exc:
        logger.warning("SPARQL failed: %s", exc)
        return "", False

    if not rows:
        logger.info("SPARQL returned 0 rows for: %s", question[:80])
        return "", False

    table = results_to_markdown(rows)
    gen_model = os.getenv("GEMINI_GEN_MODEL", "gemini-1.5-flash")

    # Schema annotations go BEFORE the table so the model understands column
    # semantics before it reads the data rows, and the question lands at the end.
    schema_parts = []
    if metric and "value" in (rows[0] if rows else {}):
        schema_parts.append(f"The 'value' column contains the metric: {metric}.")
    schema_parts.append(
        "Column naming: '_millions' suffix = USD millions, '_pct' suffix = percentage."
    )
    schema_note = " ".join(schema_parts)

    prompt = (
        f"{schema_note}\n\n"
        f"Structured financial data retrieved via SPARQL from an RDF graph of SEC filings:\n\n"
        f"{table}\n\n"
        f"Question: {question}"
    )
    try:
        client = get_genai_client()
        resp = client.models.generate_content(
            model=gen_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=_GRAPH_SYSTEM,
                temperature=0.1,
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            return "", False
        text += "\n\n_Source: structured financial data · SEC EDGAR XBRL metrics_"
        return text, True
    except Exception as exc:
        logger.warning("Graph LLM call failed: %s", exc)
        return "", False


# ---------------------------------------------------------------------------
# Main routing entry point
# ---------------------------------------------------------------------------

def route_question(
    question: str,
    k: int = 5,
    ticker: Optional[str] = None,
    form: Optional[str] = None,
) -> tuple[str, list, str]:
    """
    Route a chat question through the appropriate retrieval path.

    Returns (answer, source_chunks, path) where:
      - answer       NL answer string (never empty; may be NO_CONTEXT_MESSAGE)
      - source_chunks list[FilingChunk] from vector RAG (empty for graph-only)
      - path         "graph" | "vector" | "both" | "none" | "vector_no_graph"

    "vector_no_graph" means the classifier chose the graph path but the in-memory
    graph had no data for the asked company (e.g. not yet registered in this
    session) and the router fell back to vector search transparently.
    """
    from ..data_extract.rag import answer_question, NO_CONTEXT_MESSAGE

    path = classify_question(question)
    logger.info("Router: path=%s | %s", path, question[:80])

    _QUOTA_MSG = (
        "The daily embedding quota is exhausted — vector search is unavailable until "
        "midnight UTC. Try a metrics or comparison question; those use the structured "
        "data graph and have no embedding quota."
    )

    def _vector() -> tuple[str, list, str]:
        from ..data_extract.embeddings import DailyQuotaExceededError
        try:
            ans, chunks = answer_question(question, k=k, ticker=ticker, form=form)
        except DailyQuotaExceededError:
            return _QUOTA_MSG, [], "none"
        if not chunks:
            return NO_CONTEXT_MESSAGE, [], "none"
        return ans, chunks, "vector"

    if path == "vector":
        return _vector()

    if path == "graph":
        graph_ans, had_data = _answer_from_graph(question)
        if had_data:
            return graph_ans, [], "graph"
        logger.info("Graph had no data — falling back to vector (will surface as vector_no_graph)")
        ans, chunks, vpath = _vector()
        # Surface the fallback honestly so the frontend can show a distinct indicator.
        return ans, chunks, "vector_no_graph" if vpath == "vector" else vpath

    # path == "both": run both, merge if possible
    graph_ans, had_graph = _answer_from_graph(question)
    from ..data_extract.embeddings import DailyQuotaExceededError
    try:
        vec_ans, chunks = answer_question(question, k=k, ticker=ticker, form=form)
    except DailyQuotaExceededError:
        vec_ans, chunks = _QUOTA_MSG, []

    if had_graph and chunks:
        merged = (
            f"**From structured financial data (XBRL metrics):**\n\n{graph_ans}"
            f"\n\n---\n\n"
            f"**From SEC filing text:**\n\n{vec_ans}"
        )
        return merged, chunks, "both"

    if had_graph:
        return graph_ans, [], "graph"

    if chunks:
        return vec_ans, chunks, "vector"

    return NO_CONTEXT_MESSAGE, [], "none"
