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


def register_filing(result: dict, persist: bool = True) -> None:
    """
    Register one extractor result dict in the graph.
    Called from /extract after run() succeeds. Non-fatal — caller catches exceptions.

    persist=True (default): also writes structured metrics to the FilingMetrics
    RavenDB collection so the graph can be rebuilt on the next server startup.
    persist=False: update the in-memory registry only — used by startup
    rehydration (rebuild_graph_from_ravendb) to avoid re-writing data that was
    just read from RavenDB on every cold start.

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

    if not persist:
        return

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
            fiscal_year_end=result.get("fiscal_year_end", ""),
            period_end=result.get("period_end", ""),
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

def _needs_balance_upgrade(doc) -> bool:
    """True if the doc's metrics_by_year is missing or lacks cash_flow / computed_ratios."""
    by_year = getattr(doc, "metrics_by_year", None) or {}
    if not by_year:
        return True
    # Check the most recent year — if it has both cash_flow and computed_ratios the
    # doc is fully populated.  Older docs have only income+balance (no cash_flow).
    most_recent = by_year.get(max(by_year.keys()), {})
    if not isinstance(most_recent, dict):
        return True
    return "computed_ratios" not in most_recent or "cash_flow" not in most_recent


def _combine_multiyear(
    income_by_year: dict,
    balance_by_year: dict,
    cash_flow_by_year: dict | None = None,
) -> dict:
    """
    Merge per-year income, balance, and cash-flow dicts; add computed_ratios.

    Input format:  {year_str: {"income_statement"|"balance_sheet"|"cash_flow": {...}}}
    Output format: {year_str: {"income_statement": {...}, "balance_sheet": {...},
                                "cash_flow": {...}, "computed_ratios": {...}}}
    """
    from ..data_extract.ratios import compute_ratios

    cf_by_year = cash_flow_by_year or {}
    all_years = sorted(set(income_by_year) | set(balance_by_year) | set(cf_by_year), reverse=True)
    result: dict = {}
    for year in all_years:
        income  = income_by_year.get(year, {}).get("income_statement", {})
        balance = balance_by_year.get(year, {}).get("balance_sheet", {})
        cf      = cf_by_year.get(year, {}).get("cash_flow", {})
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
            result[year] = year_data
    return result


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

    # Check whether any docs are missing balance_sheet / computed_ratios per year
    # (old format with income-only metrics_by_year, or no metrics_by_year at all).
    needs_upgrade = [d for d in docs if _needs_balance_upgrade(d)]
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
                "fiscal_year_end":  getattr(doc, "fiscal_year_end", "") or "",
                "period_end":       getattr(doc, "period_end", "") or "",
                "sector":           doc.sector,
                "metrics":          doc.metrics if isinstance(doc.metrics, dict) else {},
                "metrics_by_year":  by_year if isinstance(by_year, dict) else {},
            }
            # persist=False: data was just read from RavenDB — no need to write it back.
            register_filing(result, persist=False)
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

    # Build the set of tickers that already have complete multi-year data — skip those.
    existing_metrics = load_all_filing_metrics()
    skip_tickers = {
        m.ticker.upper() for m in existing_metrics
        if not _needs_balance_upgrade(m)
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

            # Multi-year income + balance + cash_flow + computed_ratios — enables
            # YoY SPARQL queries (FCF, revenue, D/E, etc.) without re-fetching
            # from EDGAR on each restart.
            income_by_year    = xbrl.extract_income_multiyear(facts, n_years=5)
            balance_by_year   = xbrl.extract_balance_multiyear(facts, n_years=5)
            cash_flow_by_year = xbrl.extract_cash_flow_multiyear(facts, n_years=5)
            metrics_by_year   = _combine_multiyear(income_by_year, balance_by_year, cash_flow_by_year)

            # Fiscal year from XBRL period-end, not the filing date.  A Dec-FY
            # company filed in Jan 2026 has fiscal_year_end "2025", not "2026".
            period_end = xbrl.target_period_end(facts) or ""
            fiscal_year_end = period_end[:4] if period_end else ""

            result = {
                "ticker":           ticker,
                "form":             manifest.form or "10-K",
                "accession_number": accession,
                "filing_date":      manifest.filing_date or "",
                "fiscal_year_end":  fiscal_year_end,
                "period_end":       period_end,
                "sector":           "Unknown",   # not critical for graph queries
                "metrics": {
                    "income_statement": income,
                    "balance_sheet":    balance,
                    "cash_flow":        cash_flow,
                    "computed_ratios":  ratios,
                },
                "metrics_by_year": metrics_by_year,
            }

            # persist=True (default): migration computes fresh data — write it to RavenDB.
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

# Phrasing that signals a direct factual lookup rather than narrative exploration.
# Used to override false-positive narrative classification when the user asks a
# time-anchored metric question that happens to contain a narrative keyword
# (e.g. "What was Apple's product revenue in FY2024?" — 'product' ∈ _NARRATIVE_KW
# but the question is clearly a structured data lookup, not an MD&A question).
_DIRECT_METRIC_RE = re.compile(
    r"\b(what\s+(was|is|were|are)|how\s+(much|many)|show\s+me|give\s+me|"
    r"what'?s|tell\s+me)\b",
    re.IGNORECASE,
)


def classify_question(question: str) -> str:
    """
    Return one of: 'graph', 'vector', 'both'.

    Decision logic:
      - Direct factual lookup + metric + year     → graph (overrides narrative signal)
      - Narrative trigger with no structure/year  → vector (or both if metric mentioned)
      - Narrative + structured/year               → both
      - Structured comparison or metric + year    → graph
      - Metric alone (no narrative)               → graph
      - No clear signal                           → vector (safer: prose fallback)
    """
    has_metric        = bool(_METRIC_KW.search(question))
    has_structured    = bool(_STRUCTURED_KW.search(question))
    has_narrative     = bool(_NARRATIVE_KW.search(question))
    has_year          = bool(_YEAR_RE.search(question))
    has_direct_lookup = bool(_DIRECT_METRIC_RE.search(question))

    # A time-anchored direct metric question ("What was Apple's product revenue in
    # FY2024?") should always go to graph even when a narrative keyword fires.
    # Rationale: 'product', 'segment', 'international', etc. appear in _NARRATIVE_KW
    # to catch MD&A questions, but they also appear in plain metric questions.
    # The combination of direct-lookup phrasing + metric keyword + a specific year
    # is an unambiguous signal for a structured data retrieval.
    if has_direct_lookup and has_metric and has_year:
        return "graph"

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


def _extract_tickers(question: str, known_tickers: set[str] | None = None) -> list[str]:
    """
    Extract ticker symbols from a question.

    Scans uppercase letter sequences (2–5 chars) against the stop-word list,
    plus a name→ticker lookup for common company names.

    Single-letter tickers (e.g. F for Ford) are only accepted when they appear
    in known_tickers — this prevents false-positives on stray letters like "I"
    or "A" that would otherwise match \b[A-Z]\b everywhere.

    Returns tickers in mention order, deduplicated.
    """
    seen: set[str] = set()
    result: list[str] = []

    # 2–5 character uppercase sequences (standard tickers)
    for word in re.findall(r"\b([A-Z]{2,5})\b", question.upper()):
        if word not in _ENGLISH_STOP and word not in seen:
            seen.add(word)
            result.append(word)

    # Single-letter tickers — only accept if the letter is actually a registered ticker.
    # Without this gate, \b[A-Z]\b matches sentence-initial capitals, "I", "A", etc.
    if known_tickers:
        for word in re.findall(r"\b([A-Z])\b", question.upper()):
            if word in known_tickers and word not in seen:
                seen.add(word)
                result.append(word)

    # Company name lookup
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


def _sparql_single_company_multi_metric(ticker: str) -> str:
    """
    Multi-metric summary for one company across all stored fiscal years.
    Mirrors MULTI_METRIC_QUERY but adds FILTER(?ticker = "...") so it never
    returns rows from other companies in the graph.
    """
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
    FILTER(?ticker = "{ticker}")
}}
ORDER BY ?fiscalYear
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
        # No specific metric detected: return a multi-metric summary filtered to
        # this ticker only.  MULTI_METRIC_QUERY has no ticker filter and would
        # return every company in the graph.
        return _sparql_single_company_multi_metric(t)

    # No ticker identified — return data for all companies.
    if metric:
        return _sparql_single_metric_all(metric)

    return MULTI_METRIC_QUERY


# ---------------------------------------------------------------------------
# Fix 5 helpers: period-end disclosure + deterministic partial-data note
# ---------------------------------------------------------------------------

def _clean_metric_label(metric: str | None) -> str:
    """'net_margin_pct' → 'net margin'; 'total_revenue_millions' → 'total revenue'."""
    if not metric:
        return "data"
    label = metric.replace("_", " ")
    for suffix in (" pct", " millions"):
        if label.endswith(suffix):
            label = label[: -len(suffix)]
    return label


def _fmt_period_end(iso_date: str) -> str:
    """
    Format a period-end ISO date as 'Sep 27 2025'.

    Only formats the stored date as-is — no year substitution.  The registry
    holds the actual period-end from XBRL; fabricating dates for other years
    (e.g. swapping 2025 → 2024 while keeping Sep 27) produces wrong results
    because the actual date may differ (AAPL FY2025: Sep 27 vs FY2024: Sep 28).
    """
    _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    try:
        from datetime import date
        d = date.fromisoformat(iso_date)
        return f"{_MONTHS[d.month - 1]} {d.day} {d.year}"
    except Exception:
        return iso_date or "unknown"


def _period_end_note(tickers: list[str], year: str | None) -> str:
    """
    Return a disclosure note when the given tickers have different fiscal year-end
    months.  Only emitted for multi-company comparisons where the FY-end months
    differ (e.g. AAPL Sep vs META Dec).  Period-end dates come from the in-memory
    registry (stored as the XBRL target_period_end date — never hardcoded).

    When a specific year is queried, the note is only shown for tickers whose
    stored period_end falls in that exact year — fabricating per-year dates for
    other years produces wrong values (actual day can shift year-to-year).
    """
    if len(tickers) < 2:
        return ""

    with _lock:
        raw_ends = {t: _registry.get(t, {}).get("period_end", "") for t in tickers}

    valid = {t: pe for t, pe in raw_ends.items() if pe}
    if len(valid) < 2:
        return ""

    # When a specific year is queried, restrict to tickers whose stored period_end
    # is from that year.  If fewer than 2 tickers match we have no actual data to
    # show — emit nothing rather than fabricate dates.
    if year:
        valid = {t: pe for t, pe in valid.items() if pe[:4] == year}
        if len(valid) < 2:
            return ""

    def _month(pe: str) -> int:
        try:
            from datetime import date
            return date.fromisoformat(pe).month
        except Exception:
            return 0

    if len({_month(pe) for pe in valid.values()}) <= 1:
        return ""  # same fiscal year-end month for all — no disclosure needed

    parts = [
        f"{t} FY{year} ended {_fmt_period_end(pe)}"
        if year else
        f"{t} ended {_fmt_period_end(pe)}"
        for t, pe in [(t, valid[t]) for t in tickers if t in valid]
    ]
    if len(parts) < 2:
        return ""

    return (
        "_Note: " + "; ".join(parts)
        + " — these are overlapping but not identical periods._"
    )


def _partial_data_note(
    missing_tickers: list[str],
    metric: str | None,
    year: str | None,
) -> str:
    """
    Deterministic gap notice for requested tickers absent from SPARQL results.
    Same structural gap → identical phrasing on every call (no LLM variance).
    """
    if not missing_tickers:
        return ""
    label = _clean_metric_label(metric)
    fy = f" FY{year}" if year else ""
    parts = [f"{t}: no {label} data available for{fy}" for t in missing_tickers]
    plural = "s" if len(parts) > 1 else ""
    return f"_Data gap{plural}: {'; '.join(parts)}._"


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

    known = _graph_tickers()

    if not known:
        return "", False

    # Pass the known-ticker set so single-letter tickers (e.g. F for Ford) are
    # matched only when they are actually registered in the graph.
    raw_tickers = _extract_tickers(question, known_tickers=known)

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

    # Tickers present in SPARQL results (order-preserving dedup)
    tickers_with_data = list(dict.fromkeys(
        r.get("ticker", "") for r in rows if r.get("ticker")
    ))

    # Queried year (used for both notes below)
    year_match = _YEAR_RE.search(question)
    queried_year = re.search(r"20\d{2}", year_match.group()).group() if year_match else None

    # Deterministic gap note: requested tickers absent from results
    missing = [t for t in available if t not in tickers_with_data] if available else []
    partial_note = _partial_data_note(missing, metric, queried_year)

    # Period-end disclosure: only when FY-end months differ across compared companies
    period_note = _period_end_note(tickers_with_data, queried_year)

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
        # Append deterministic structured notes after the LLM answer.
        # These are always templated — never LLM-generated — so the phrasing
        # is identical across repeated calls for the same structural gap.
        if partial_note:
            text += f"\n\n{partial_note}"
        if period_note:
            text += f"\n\n{period_note}"
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
    _PER_MINUTE_QUOTA_MSG = (
        "The per-minute embedding rate limit was hit — vector search is temporarily "
        "unavailable. Please try again in about 60 seconds, or rephrase as a metrics "
        "question (e.g. 'Apple gross margin FY2024') to use the structured data graph "
        "instead (zero embedding calls)."
    )

    def _vector() -> tuple[str, list, str]:
        from ..data_extract.embeddings import DailyQuotaExceededError, PerMinuteQuotaError
        try:
            ans, chunks = answer_question(question, k=k, ticker=ticker, form=form)
        except DailyQuotaExceededError:
            return _QUOTA_MSG, [], "none"
        except PerMinuteQuotaError:
            return _PER_MINUTE_QUOTA_MSG, [], "none"
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
    from ..data_extract.embeddings import DailyQuotaExceededError, PerMinuteQuotaError
    try:
        vec_ans, chunks = answer_question(question, k=k, ticker=ticker, form=form)
    except DailyQuotaExceededError:
        vec_ans, chunks = _QUOTA_MSG, []
    except PerMinuteQuotaError:
        vec_ans, chunks = _PER_MINUTE_QUOTA_MSG, []

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
