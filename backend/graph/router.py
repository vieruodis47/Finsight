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
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from rdflib import Graph

from .rdf_graph import build_graph, run_sparql, results_to_markdown, MULTI_METRIC_QUERY, _metric_unit
from ..data_extract.embeddings import DailyQuotaExceededError, PerMinuteQuotaError

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

    # Cache invalidation fan-out. register_filing() is the single signal that a
    # ticker's XBRL/ingest state may have changed, so it must invalidate every
    # in-process cache derived from that data. THREE caches subscribe here, each
    # invalidated independently (one failing must not skip the others):
    #   1. /compare-metrics  -- per-ticker XBRL comparison results
    #   2. /indexed          -- IngestManifest presence (single cached set)
    #   3. /metrics          -- per-ticker single-filing dashboard metrics
    # Each has a 60s TTL as its own backstop, so a missed invalidation self-heals
    # within a minute; the hook just tightens that window on the common path.

    # 1. /compare-metrics -- fail closed: if the targeted per-ticker invalidation
    # can't be trusted to have run, drop the whole cache rather than risk serving
    # a stale comparison.
    try:
        from ..data_extract.compare_metrics import invalidate_ticker
        invalidate_ticker(ticker)
    except Exception as e:
        try:
            from ..data_extract.compare_metrics import clear_cache
            clear_cache()
        except Exception:
            logger.error(
                "compare-metrics cache invalidation AND fail-safe clear both "
                "failed for %s -- cache may now be stale: %s", ticker, e,
            )
        else:
            logger.warning(
                "compare-metrics cache invalidation failed for %s -- cleared "
                "entire cache as a fail-safe: %s", ticker, e,
            )

    # 2. /indexed -- single cached set; invalidate() already clears everything,
    # so on failure the 60s TTL is the only fallback (no redundant second clear).
    try:
        from ..data_extract.indexed import invalidate as invalidate_indexed_cache
        invalidate_indexed_cache()
    except Exception as e:
        logger.warning(
            "indexed-ticker cache invalidation failed for %s -- will self-heal "
            "within the 60s TTL: %s", ticker, e,
        )

    # 3. /metrics -- per-ticker; drop just this ticker's entry, TTL backs it up.
    try:
        from ..data_extract.filing_metrics import invalidate_ticker as invalidate_metrics_ticker
        invalidate_metrics_ticker(ticker)
    except Exception as e:
        logger.warning(
            "metrics cache invalidation failed for %s -- will self-heal "
            "within the 60s TTL: %s", ticker, e,
        )

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


def _refresh_computed_ratios(metrics_by_year: dict) -> dict:
    """Recompute `computed_ratios` for each year from the stored income / balance /
    cash-flow dicts using the CURRENT ratios.py definitions, overriding any ratios
    that were persisted under an older definition.

    This is what lets a ratio-definition fix (e.g. debt-to-equity switching from
    long-term-debt/equity to total-liabilities/equity) take effect on the live
    in-memory graph WITHOUT re-ingesting every filing: the graph derives ratios
    from the stored balance-sheet facts at load time rather than trusting a
    possibly-stale stored number. The underlying facts (Liabilities, equity, …)
    are already persisted, so this is a pure recompute — no network, no embeddings.
    """
    from ..data_extract.ratios import compute_ratios
    if not isinstance(metrics_by_year, dict):
        return metrics_by_year
    for _year, ym in metrics_by_year.items():
        if not isinstance(ym, dict):
            continue
        income  = ym.get("income_statement") or {}
        balance = ym.get("balance_sheet") or {}
        cf      = ym.get("cash_flow") or {}
        if income or balance:
            fresh = compute_ratios(income, balance, cf)
            if fresh:
                ym["computed_ratios"] = {**(ym.get("computed_ratios") or {}), **fresh}
    return metrics_by_year


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
        # Re-derive ratios from the stored balance-sheet facts so the graph always
        # reflects the CURRENT ratio definitions (e.g. the corrected D/E), even for
        # filings persisted under an older definition — no re-ingest required.
        if isinstance(by_year, dict):
            by_year = _refresh_computed_ratios(by_year)
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
    # Bare risk/uncertainty vocabulary (risks?, concern, headwind, uncertaint…)
    # sits alongside "risk factor" so a risk-factors question is ALWAYS treated
    # as narrative — even when it also names a metric ("What risks did X flag
    # about revenue in FY2024?"). Without the bare terms such a question skips
    # this branch and hits the has_metric→graph catch-all, sending a prose-only
    # risk question to SPARQL. This phrasing is advertised on the Help page.
    r"\b(risks?|risk factor|concerns?|headwinds?|uncertaint(y|ies)"
    r"|summarize|summary|business overview|strategy|management"
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

# --- Multi-fact / coverage signals (E-4 router fix) -------------------------
# The graph path answers from a single SPARQL lookup over XBRL numeric metrics.
# E-2 showed it collapsing on the multi-hop/aggregation slices (graph multi-hop
# 0.29 vs naive 0.92) because three kinds of question got routed graph-only:
#   1. multiple metrics requested — the single-metric SPARQL returns just one;
#   2. facts the graph does not store — R&D, segment / Products-vs-Services,
#      dividends/buybacks, cost of revenue (these live in filing prose);
#   3. cross-entity "who spent more" comparisons needing per-company prose.
# For all three the vector prose must be in the loop, so they route to `both`
# (when a graph-backed metric is also present) or `vector`. Only clean single
# covered-metric lookups (single-hop, single-metric temporal) stay graph-only.

# Concepts NOT in the XBRL metric graph (income_statement, balance_sheet,
# cash_flow, computed_ratios) — presence forces a prose backstop.
_UNCOVERED_METRIC_RE = re.compile(
    r"\b(research and development|r&d|cost of (revenue|goods|sales)"
    r"|sg&a|selling,? general|depreciation|amortization|inventory|backlog"
    r"|dividends?|repurchases?|buybacks?|capital return|operating expenses?"
    r"|products?|services?)\b",
    re.IGNORECASE,
)

# Cross-entity comparison cues that need per-company prose, not one table.
_COMPARISON_RE = re.compile(
    r"\b(which\s+(company|one|firm)|who\s+(spent|earned|had|has|paid|reported)"
    r"|each\s+(company|spend|spent|report|reported)|respectively?"
    r"|comparing\s+their|spent\s+more|more\s+than|higher\s+than|lower\s+than)\b",
    re.IGNORECASE,
)

# Derivation cues — the answer combines multiple retrieved facts.
_IMPLIED_RE = re.compile(
    r"\b(impl(y|ies|ied)|how\s+far\s+apart|difference\s+between)\b",
    re.IGNORECASE,
)


def classify_question(question: str) -> str:
    """
    Return one of: 'graph', 'vector', 'both'.

    Graph-only is reserved for questions the single-shot SPARQL path can fully
    answer: a clean lookup of one graph-backed metric (single-hop) or one metric
    across years (temporal). Everything needing prose or multiple facts gets the
    vector backstop. Decision order (first match wins):

      1. Narrative intent (MD&A, risk factors, "according to", segments, …)
         → never graph-only: `both` if a metric is also asked, else `vector`.
      2. Multi-fact — >=2 graph-backed metrics, an uncovered metric, a
         cross-entity comparison, or a derived quantity ("what margin does that
         imply", "how far apart") → `both` if a graph metric is present, else
         `vector`.
      3. Clean single-metric lookup (direct phrasing, or metric + year, or a
         bare metric, or a structured comparison) → `graph`.
      4. No structured signal → `vector` (prose fallback).

    Rationale: E-2 graph misroutes sent multi-hop/aggregation questions to the
    graph-only path, which returned confident partial answers. Gating graph-only
    to single covered-metric questions keeps its ~2.3x cost/ingest win where it
    is accurate and routes the rest through the vector path that already scores
    well there. See .claude/EXPERIMENTS.md (E-4).
    """
    has_metric        = bool(_METRIC_KW.search(question))
    has_structured    = bool(_STRUCTURED_KW.search(question))
    has_narrative     = bool(_NARRATIVE_KW.search(question))
    has_year          = bool(_YEAR_RE.search(question))
    has_direct_lookup = bool(_DIRECT_METRIC_RE.search(question))

    # Multi-fact / coverage signals — see the regex definitions above.
    n_metrics      = _count_covered_metrics(question)
    has_uncovered  = bool(_UNCOVERED_METRIC_RE.search(question))
    has_comparison = bool(_COMPARISON_RE.search(question))
    has_implied    = bool(_IMPLIED_RE.search(question))
    multi_fact = (
        n_metrics >= 2
        or has_comparison
        or has_implied
        or (has_metric and has_uncovered)
    )

    # 1. Narrative intent always needs filing prose — never route graph-only.
    #    (Fixes the E-2 bug where the direct-lookup + metric + year override sent
    #    MD&A/segment questions such as "…drivers of revenue growth across
    #    segments" to the graph, which has no narrative to answer from.)
    if has_narrative:
        return "both" if has_metric else "vector"

    # 2. Multi-fact / uncovered / comparison / derived → add the vector backstop.
    #    `both` when a graph-backed metric is also present (authoritative XBRL
    #    number + prose), else pure `vector`.
    if multi_fact:
        return "both" if _detect_metric(question) else "vector"

    # 3. Clean single graph-backed-metric lookup — the cheap, accurate path.
    if has_direct_lookup and has_metric and has_year:
        return "graph"

    if has_structured or (has_metric and has_year):
        return "graph"

    if has_metric:
        return "graph"

    # 4. No structured signal — prose fallback.
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
        upper = question.upper()
        for m in re.finditer(r"\b([A-Z])\b", upper):
            word = m.group(1)
            # Skip a letter glued to an apostrophe — the "S" in "Apple's" is a
            # possessive, not a ticker mention (it otherwise resolves to a real
            # single-letter ticker like S and corrupts the scope/answer/chart).
            start = m.start(1)
            if start > 0 and upper[start - 1] in "'’":
                continue
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


def _count_covered_metrics(question: str) -> int:
    """Number of DISTINCT graph-backed metrics explicitly named in the question.

    Distinct by canonical metric name, so 'revenue' and 'total revenue' count
    once. Used by classify_question to spot multi-metric questions (e.g.
    'total revenue and operating income') that the single-metric SPARQL path
    would answer only partially.
    """
    q_lower = question.lower()
    return len({canon for phrase, canon in _METRIC_MAP.items() if phrase in q_lower})


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


def _ticker_in(tickers: list[str]) -> str:
    """SPARQL `?ticker IN ("A", "B", ...)` over ALL requested companies, so every
    company mentioned in a comparison is looked up independently — not just the
    first two. (The old two-company templates hard-coded t1/t2 and silently
    dropped a 3rd+ company, which surfaced as a peer reading "not disclosed".)"""
    inner = ", ".join(f'"{t}"' for t in tickers)
    return f"FILTER(?ticker IN ({inner}))"


def _sparql_multi_company_single_metric(tickers: list[str], metric: str) -> str:
    return f"""
PREFIX fs:  <http://finsight.io/ontology#>
PREFIX fsd: <http://finsight.io/data/>
SELECT ?ticker ?fiscalYear ?value
WHERE {{
    ?co  a fs:Company ; fs:hasTicker ?ticker ; fs:filedFiling ?f .
    ?f   fs:fiscalYear ?fiscalYear ; fs:reportsMetric ?m .
    ?m   fs:metricName "{metric}" ; fs:metricValue ?value .
    {_ticker_in(tickers)}
}}
ORDER BY ?ticker ?fiscalYear
"""


def _sparql_multi_company_multi_metric(tickers: list[str]) -> str:
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
    {_ticker_in(tickers)}
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
        # ALL mentioned companies are looked up independently (not just the first
        # two), so a 3-way comparison — e.g. "AAPL vs NVDA vs MSFT" — returns every
        # company's figure rather than dropping the rest as "not disclosed".
        return (
            _sparql_multi_company_single_metric(tickers, metric)
            if metric
            else _sparql_multi_company_multi_metric(tickers)
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

# The graph value is authoritative and EXACT. The single biggest hallucination
# seam on the graph path was the old prompt telling the model to rescale/reformat
# numbers ("$391,000M = $391B") — i.e. do arithmetic on the figures. Instead we
# now pre-format every value in the table with its correct unit/scale so the
# model only has to COPY it verbatim, and the prompt forbids any recomputation,
# any number not in the table, and any guessing when a figure is absent.
_GRAPH_SYSTEM = (
    "You are FinSight, a financial-data assistant. Answer the question using ONLY "
    "the DATA TABLE provided — it is exact structured data extracted from SEC XBRL "
    "filings, and every value is already shown with its correct unit and scale.\n"
    "\n"
    "Strict rules:\n"
    "1. Use ONLY numbers that appear in the table. Copy each figure VERBATIM — the "
    "exact digits, scale, and unit as written (e.g. write \"$391.04B\" if the table "
    "says \"$391.04B\"). Do NOT recompute, re-scale, convert, or re-round any value.\n"
    "2. Every number in your answer must be one that appears in the table. Never "
    "introduce a figure from prior knowledge, memory, or estimation.\n"
    "3. If the table does not contain a figure the question asks for, say exactly: "
    "\"That figure is not disclosed in the available filings.\" Do NOT guess, "
    "approximate, or fill the gap from general knowledge.\n"
    "4. Fiscal-year labels (e.g. FY2024) are given in the table — use them as-is; "
    "do not relabel or shift years.\n"
    "5. Be concise and state the fiscal year for each figure you cite."
)


# --- Exact, verbatim-ready value formatting (Seam 3: grounded generation) ----
# Values reach the model already formatted so it never has to do arithmetic.
_MULTIMETRIC_COLUMN_UNIT = {
    "revenue": "usd_millions", "netIncome": "usd_millions",
    "netMargin": "percent", "operatingMargin": "percent", "roe": "percent",
}


def _column_unit(col: str, metric: Optional[str]) -> Optional[str]:
    if col == "ticker":
        return "ticker"
    if col in ("fiscalYear", "fy", "year"):
        return "year"
    if col in _MULTIMETRIC_COLUMN_UNIT:
        return _MULTIMETRIC_COLUMN_UNIT[col]
    if col == "value" and metric:
        return _metric_unit(metric)
    return None


def _fmt_cell(unit: Optional[str], v) -> str:
    if v is None:
        return "n/a"
    if unit == "ticker":
        return str(v)
    if unit == "year":
        return f"FY{str(v).split('.')[0]}"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if unit == "usd_millions":
        # Show both billions (friendly) and exact millions so the model can copy
        # either verbatim; both are the graph's exact value, not a re-derivation.
        return f"${x / 1000:,.2f}B (${x:,.0f}M)" if abs(x) >= 1000 else f"${x:,.1f}M"
    if unit == "percent":
        return f"{x:.2f}%"
    if unit == "ratio":
        return f"{x:.3f}"
    if unit == "usd_per_share":
        return f"${x:.2f}"
    return str(v)


def _format_graph_table(rows: list[dict], metric: Optional[str]) -> str:
    """Markdown table with every metric value pre-formatted to its exact
    unit/scale, so the model copies figures verbatim instead of rescaling them."""
    if not rows:
        return "_No results._"
    cols = list(rows[0].keys())
    units = {c: _column_unit(c, metric) for c in cols}
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for r in rows:
        lines.append("| " + " | ".join(_fmt_cell(units[c], r.get(c)) for c in cols) + " |")
    return "\n".join(lines)


# --- Numeric grounding check (Seam 3e) --------------------------------------
# Extract "financial-looking" numbers (has a decimal, a $/%, or is large) and
# ignore bare small integers and 4-digit years, which are labels not claims.
_NUM_RE = re.compile(r"\$?\s?-?\d[\d,]*\.?\d*\s?%?")


def _financial_numbers(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group()
        # Normalise first (incl. a trailing period from end-of-sentence, e.g.
        # "FY2024." -> "2024") so the year/size filters below see a clean number.
        core = raw.replace("$", "").replace("%", "").replace(",", "").replace(" ", "").strip("-").rstrip(".")
        if not core or core == ".":
            continue
        # Skip 4-digit years (labels) and tiny bare integers (list markers, "one").
        if re.fullmatch(r"(19|20)\d{2}", core):
            continue
        if "." not in core and "%" not in raw and "$" not in raw and len(core) < 3:
            continue
        out.add(core)
    return out


def _unsupported_numbers(answer: str, context: str) -> list[str]:
    """Numbers asserted in `answer` that do not appear in `context`. Prefix
    matching both ways tolerates a provided value being cited at coarser
    precision (391 vs 391.04) but still catches an invented figure."""
    ctx = _financial_numbers(context)
    bad: list[str] = []
    for n in _financial_numbers(answer):
        if any(n == c or c.startswith(n) or n.startswith(c) for c in ctx):
            continue
        bad.append(n)
    return bad


# ---------------------------------------------------------------------------
# Graph citations — the SAME reference cards vector answers use, built from the
# XBRL facts a graph/structured answer is grounded in (company, form/accession,
# fiscal period, metric + value). Unifies citations across retrieval paths so a
# graph answer is never given a lesser "just an italic line" treatment.
# ---------------------------------------------------------------------------

_GRAPH_COL_LABEL = {
    "revenue": "Revenue", "netIncome": "Net income", "netMargin": "Net margin",
    "operatingMargin": "Operating margin", "roe": "ROE",
}


def _edgar_filing_url(ticker: str, accession: str) -> str:
    """Best-effort EDGAR filing-index URL from the company CIK + accession.
    Correct for self-filed filings (the extracted large-caps); returns "" when
    the CIK or accession is unknown so the citation card simply omits the link."""
    if not accession:
        return ""
    try:
        from ..data_extract.sec_client import cik_for_ticker
        cik = cik_for_ticker(ticker)
    except Exception:
        cik = None
    if not cik:
        return ""
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{accession}-index.htm"


def build_graph_references(rows: list[dict], metric: Optional[str], tickers: list[str]) -> list[dict]:
    """One reference card per company in the SPARQL result, shaped exactly like a
    vector reference (same fields, same UI). `text` is the per-year XBRL fact(s)
    the answer copied; `preview` is a one-line summary; `url` links the filing."""
    try:
        from ..data_extract.sec_client import company_name_for_ticker
    except Exception:
        company_name_for_ticker = lambda _t: None  # noqa: E731

    metric_label = _clean_metric_label(metric) if metric else "financial statements"
    section = (metric_label[:1].upper() + metric_label[1:]) if metric else "XBRL financial statements"

    refs: list[dict] = []
    for tk in tickers:
        with _lock:
            reg = dict(_registry.get(tk, {}))
        trows = [r for r in rows if r.get("ticker") == tk]

        lines: list[str] = []
        for r in trows:
            fy = str(r.get("fiscalYear", "")).split(".")[0]
            cells = []
            for col, val in r.items():
                if col in ("ticker", "fiscalYear"):
                    continue
                label = _GRAPH_COL_LABEL.get(col) or (metric_label if col == "value" else col)
                cells.append(f"{label}: {_fmt_cell(_column_unit(col, metric), val)}")
            if cells:
                lines.append((f"FY{fy} — " if fy else "") + "; ".join(cells))

        text = "\n".join(lines) if lines else metric_label
        refs.append({
            "number": 0,
            "ticker": tk,
            "company": company_name_for_ticker(tk) or tk,
            "form": reg.get("form", "10-K"),
            "section": section,
            "url": _edgar_filing_url(tk, reg.get("accession_number", "")),
            "accession_number": reg.get("accession_number", ""),
            "filing_date": reg.get("filing_date", ""),
            "chunk_index": 0,
            "source": "",
            "preview": (lines[0] if lines else metric_label)[:240],
            "text": text[:6000],
        })
    return refs


# ---------------------------------------------------------------------------
# Inline chat chart — built from the SAME SPARQL rows that ground the answer, so
# the chart and the text can never disagree (never a separately computed number).
# Only produced for chartable structured data: >=2 companies for a metric, or one
# metric over >=2 years. A genuine per-company/per-year gap is carried as a null
# value (rendered as a labeled gap client-side), never a 0 and never dropped.
# ---------------------------------------------------------------------------

def _chart_unit(metric: str) -> str:
    if metric.endswith("_pct"):
        return "pct"
    if metric.endswith("_millions"):
        return "usd_m"
    if metric in ("eps_basic", "eps_diluted"):
        return "per_share"
    if metric in ("debt_to_equity", "current_ratio", "quick_ratio"):
        return "ratio"
    return "num"


def _chart_fmt(value, unit: str) -> str:
    if value is None:
        return "not disclosed"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "pct":
        return f"{v:.1f}%"
    if unit == "ratio":
        return f"{v:.2f}"
    if unit == "per_share":
        return f"${v:.2f}"
    if unit == "usd_m":
        a = abs(v)
        if a >= 1e6:
            return f"${v / 1e6:.1f}T"
        if a >= 1e3:
            return f"${v / 1e3:.1f}B"
        return f"${v:.0f}M"
    return f"{v:g}"


def build_graph_chart(
    rows: list[dict], metric: Optional[str], question: str,
    requested: Optional[list[str]] = None,
) -> Optional[dict]:
    """Build a compact inline-chart spec from SPARQL rows, or None when the data
    isn't chartable. Shape (JSON-serialisable, mirrored by the frontend):

      {kind:"bar",  metric, label, unit, year, bars:[{label, value|None}], caption}
      {kind:"line", metric, label, unit, years:[...],
                    series:[{ticker, points:[{year, value|None}]}], caption}

    `requested` names the companies the question explicitly asked about. A
    requested company with NO data for the metric is carried as an explicit gap
    (value None) rather than silently dropped, so the chart discloses the gap the
    same way the text does.
    """
    if not metric or not rows or "value" not in rows[0]:
        return None

    by_ticker: dict[str, dict[str, float]] = {}
    for r in rows:
        t = (r.get("ticker") or "").upper()
        y = str(r.get("fiscalYear") or "").split(".")[0][:4]
        if not t or not y:
            continue
        try:
            by_ticker.setdefault(t, {})[y] = float(r["value"])
        except (TypeError, ValueError):
            continue

    data_tickers = [t for t in by_ticker if by_ticker[t]]
    if not data_tickers:
        return None

    # Companies to display: the explicitly-requested set (in mention order) when
    # the question named companies — so a data-less requested company shows as a
    # gap — otherwise just the companies that have data (e.g. "which company…").
    req = [t.upper() for t in (requested or []) if t]
    tickers = req if req else data_tickers

    unit = _chart_unit(metric)
    label = (_clean_metric_label(metric) or metric).strip()
    label = label[:1].upper() + label[1:]

    wants_time = len(re.findall(r"20\d{2}", question)) > 1 or bool(
        re.search(r"\b(over time|trend|history|by year|year[- ]over[- ]year|yoy|each year|since)\b",
                  question, re.IGNORECASE)
    )
    # A single specific fiscal year in the question (e.g. "FY2025") pins the
    # answer to one value per company → a snapshot (bar), never a trend line.
    pinned_year = len(set(re.findall(r"20\d{2}", question))) == 1
    max_years = max((len(v) for v in by_ticker.values()), default=0)

    # LINE — a metric over >=3 fiscal years (single or multi company), when the
    # question isn't pinned to one specific fiscal year. Two-point or single-year
    # data never becomes a line; a one-year multi-company ask is a bar (below).
    # A requested company with no data becomes an all-null (gap) series.
    if max_years >= 3 and not pinned_year and (len(tickers) == 1 or wants_time):
        years = sorted({y for v in by_ticker.values() for y in v})
        series = [
            {"ticker": t, "points": [{"year": y, "value": by_ticker.get(t, {}).get(y)} for y in years]}
            for t in tickers
        ]
        latest = years[-1]
        summary = ", ".join(f"{t} {_chart_fmt(by_ticker.get(t, {}).get(latest), unit)}" for t in tickers)
        caption = f"{label} by fiscal year — FY{latest}: {summary}."
        return {"kind": "line", "metric": metric, "label": label, "unit": unit,
                "years": years, "series": series, "caption": caption}

    # BAR — >=2 companies compared at a single fiscal year (the latest the
    # companies-with-data share, else the latest reported overall). A requested
    # company with no data for that metric is carried as an explicit gap (None).
    if len(tickers) >= 2:
        display_with_data = [t for t in tickers if by_ticker.get(t)]
        if display_with_data:
            shared = set.intersection(*(set(by_ticker[t]) for t in display_with_data))
            year = max(shared) if shared else max({y for t in display_with_data for y in by_ticker[t]})
        else:
            year = None
        bars = [{"label": t, "value": (by_ticker.get(t, {}).get(year) if year else None)} for t in tickers]
        yr_txt = f"FY{year}" if year else "latest reported year"
        summary = ", ".join(f"{b['label']} {_chart_fmt(b['value'], unit)}" for b in bars)
        caption = f"{label} by company ({yr_txt}): {summary}."
        return {"kind": "bar", "metric": metric, "label": label, "unit": unit,
                "year": year, "bars": bars, "caption": caption}

    return None


def _graph_prompt(question: str) -> tuple[Optional[str], str, list[dict], Optional[dict]]:
    """
    Retrieval-only graph preparation (NO LLM call, no embeddings).

    Runs SPARQL against the in-memory graph and builds the generation prompt plus
    the deterministic tail (data-gap / period-end notes + source line) that is
    appended verbatim AFTER the model's answer. Split out from _answer_from_graph
    so the streaming path can do this retrieval work up front (the "bird" phase)
    and then stream the generation.

    Returns (prompt, tail): prompt is None when the graph has no usable data for
    the question (caller falls back to vector). `tail` is templated text — never
    LLM-generated — so phrasing is identical across calls for the same gap.
    """
    g = _get_graph()
    if len(g) == 0:
        return None, "", []

    known = _graph_tickers()
    if not known:
        return None, "", []

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
        return None, "", []

    metric = _detect_metric(question)
    sparql = _build_sparql(question, available)
    try:
        rows = run_sparql(g, sparql)
    except Exception as exc:
        logger.warning("SPARQL failed: %s", exc)
        return None, "", []

    if not rows:
        logger.info("SPARQL returned 0 rows for: %s", question[:80])
        return None, "", []

    # Pre-format every value to its exact unit/scale so the model copies figures
    # verbatim (no rescaling/rounding — the old $391,000M→$391B seam).
    table = _format_graph_table(rows, metric)

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

    # A short lead-in names the metric (for the single-'value'-column queries) so
    # the model knows what the column is; values themselves are pre-formatted.
    lead = ""
    if metric and rows and "value" in rows[0]:
        lead = f"The 'value' column is the metric: {metric}.\n\n"

    prompt = (
        "DATA TABLE — exact figures from SEC XBRL filings, each already shown with "
        "its correct unit and scale. Use these values verbatim.\n\n"
        f"{lead}{table}\n\n"
        f"Question: {question}"
    )

    tail = ""
    if partial_note:
        tail += f"\n\n{partial_note}"
    if period_note:
        tail += f"\n\n{period_note}"
    tail += "\n\n_Source: structured financial data · SEC EDGAR XBRL metrics_"
    # `available` = the companies the question explicitly named that exist in the
    # graph. Passing it lets the chart show a genuinely data-less requested
    # company as an explicit gap (not silently omit it).
    chart = build_graph_chart(rows, metric, question, requested=available)
    return prompt, tail, build_graph_references(rows, metric, tickers_with_data), chart


def _answer_from_graph(question: str) -> tuple[str, bool, list[dict]]:
    """
    Run SPARQL against the in-memory graph and generate a grounded NL answer.
    Returns (answer, had_data, graph_refs). No embedding calls. Used by the
    non-streaming /chat path; the streaming path uses _graph_prompt + streaming
    generation. `graph_refs` are citation cards for the XBRL facts cited.
    """
    from ..data_extract.embeddings import get_genai_client
    from google.genai import types as genai_types

    prompt, tail, graph_refs, _chart = _graph_prompt(question)
    if prompt is None:
        return "", False, []

    gen_model = os.getenv("GEMINI_GEN_MODEL", "gemini-3.1-flash-lite")

    def _generate(extra: str = "") -> str:
        client = get_genai_client()
        resp = client.models.generate_content(
            model=gen_model,
            contents=prompt + extra,
            config=genai_types.GenerateContentConfig(
                system_instruction=_GRAPH_SYSTEM,
                temperature=0.1,
            ),
        )
        return (resp.text or "").strip()

    try:
        text = _generate()
        if not text:
            return "", False, []
        # Numeric grounding check (Seam 3e): every figure asserted must appear in
        # the table. If one doesn't, the model invented/derived it — regenerate
        # once with a pointed reminder; if it still can't ground, keep the answer
        # but log the unsupported figures for visibility.
        unsupported = _unsupported_numbers(text, prompt)
        if unsupported:
            logger.warning("Graph answer had unsupported numbers %s — regenerating once", unsupported)
            retry = _generate(
                "\n\nIMPORTANT: your previous answer used a number that is NOT in the "
                "table. Use ONLY the exact figures shown above, copied verbatim; if a "
                "figure is absent, say it is not disclosed in the available filings."
            )
            if retry and not _unsupported_numbers(retry, prompt):
                text = retry
            else:
                still = _unsupported_numbers(retry or text, prompt)
                logger.warning("Graph answer STILL unsupported after retry: %s", still)
                if retry:
                    text = retry
        # Deterministic templated tail appended verbatim after the LLM answer.
        return text + tail, True, graph_refs
    except Exception as exc:
        logger.warning("Graph LLM call failed: %s", exc)
        return "", False, []


# ---------------------------------------------------------------------------
# Main routing entry point
# ---------------------------------------------------------------------------

def route_question(
    question: str,
    k: int = 5,
    ticker: Optional[str] = None,
    tickers: Optional[list[str]] = None,
    form: Optional[str] = None,
) -> tuple[str, list, list, str]:
    """
    Route a chat question through the appropriate retrieval path.

    Returns (answer, source_chunks, graph_sources, path) where:
      - answer        NL answer string (never empty; may be NO_CONTEXT_MESSAGE)
      - source_chunks list[FilingChunk] from vector RAG (empty for graph-only)
      - graph_sources list[dict] XBRL-fact citation cards (empty for vector-only)
      - path          "graph" | "vector" | "both" | "none" | "vector_no_graph"

    "vector_no_graph" means the classifier chose the graph path but the in-memory
    graph had no data for the asked company (e.g. not yet registered in this
    session) and the router fell back to vector search transparently.
    """
    from ..data_extract.rag import answer_question, NO_CONTEXT_MESSAGE

    path = classify_question(question)
    logger.info("Router: path=%s | %s", path, question[:80])

    # Vector-scope resolution. Scope the vector search to the companies the
    # question actually names, so an unscoped question about a company with zero
    # chunks can't silently retrieve ANOTHER company's filing text (the graph
    # and vector halves must agree on scope; the graph path already resolves a
    # specific company from the text, the vector path historically searched
    # globally). Precedence, highest first:
    #   1. an explicit caller ticker LIST (e.g. the compare-view FinChat strip,
    #      which always sends [anchor, peer]) wins outright over anything the
    #      question does or doesn't name -- "which has better margins?" names no
    #      company, and this is exactly the case that must NOT fall to global
    #      scope. Filters to `ticker IN (...)`, an OR over the list, so a chunk
    #      from a third company can never be retrieved.
    #   2. else a single caller ticker (e.g. FinChat single-select);
    #   3. else the companies named in the question that we actually have data
    #      for (same _extract_tickers resolution the graph path uses, filtered
    #      to registered tickers so stray uppercase words don't false-scope);
    #   4. else None -> global search, the correct behavior for a genuinely
    #      corpus-wide question ("which of my companies flags supply-chain risk?").
    known = _graph_tickers()
    mentioned = [t for t in _extract_tickers(question, known_tickers=known) if t in known]
    explicit = [t.strip().upper() for t in (tickers or []) if t and t.strip()]
    if explicit:
        vector_scope: Optional[list[str]] = explicit
    elif ticker:
        vector_scope = [ticker.strip().upper()]
    elif mentioned:
        vector_scope = mentioned
    else:
        vector_scope = None

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
        try:
            ans, chunks = answer_question(question, k=k, tickers=vector_scope, form=form)
        except DailyQuotaExceededError:
            return _QUOTA_MSG, [], "none"
        except PerMinuteQuotaError:
            return _PER_MINUTE_QUOTA_MSG, [], "none"
        except Exception as exc:
            # Any other vector-infra failure (e.g. the vector store is
            # unreachable) must degrade to an honest "not found" rather than
            # crash the whole request — especially on the graph-miss fallback,
            # where a factual question should end in "no data", not a 500.
            logger.warning("Vector retrieval failed: %s", exc)
            return NO_CONTEXT_MESSAGE, [], "none"
        if not chunks:
            return NO_CONTEXT_MESSAGE, [], "none"
        return ans, chunks, "vector"

    if path == "vector":
        ans, chunks, vpath = _vector()
        return ans, chunks, [], vpath

    if path == "graph":
        graph_ans, had_data, grefs = _answer_from_graph(question)
        if had_data:
            return graph_ans, [], grefs, "graph"
        logger.info("Graph had no data — falling back to vector (will surface as vector_no_graph)")
        ans, chunks, vpath = _vector()
        # Surface the fallback honestly so the frontend can show a distinct indicator.
        return ans, chunks, [], "vector_no_graph" if vpath == "vector" else vpath

    # path == "both": run both retrieval paths concurrently. Both are read-only
    # w.r.t. the rdflib graph within a single request — the only writer is
    # register_filing(), called from /extract, not from either function here.
    # See _answer_from_graph / answer_question for the read-only trace.
    def _run_vector() -> tuple[str, list]:
        try:
            return answer_question(question, k=k, tickers=vector_scope, form=form)
        except DailyQuotaExceededError:
            return _QUOTA_MSG, []
        except PerMinuteQuotaError:
            return _PER_MINUTE_QUOTA_MSG, []
        except Exception as exc:
            logger.warning("Vector retrieval failed (both path): %s", exc)
            return "", []

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_graph = pool.submit(_answer_from_graph, question)
        fut_vector = pool.submit(_run_vector)
        graph_ans, had_graph, grefs = fut_graph.result()
        vec_ans, chunks = fut_vector.result()

    if had_graph and chunks:
        # Coverage-qualified filing-text header. The graph half answers on every
        # company in scope, but the vector half only returns chunks for the
        # companies that actually have indexed filing text AND surfaced in the
        # top-k. When the requested scope named more companies than the returned
        # chunks cover, qualify the header so a "both" answer can't imply filing
        # text for a company it never read. We name the COVERED companies, NOT a
        # reason: at this point we can't distinguish "not indexed" from "indexed
        # but no top-k passages" (a company can be indexed yet absent here), and
        # asserting "not indexed" would be wrong in exactly the both-indexed case
        # the compare-view strip runs in. Badge stays "both" -- both paths ran;
        # the header, not the badge, carries coverage.
        text_header = "**From SEC filing text:**"
        if vector_scope:
            requested = list(dict.fromkeys(vector_scope))  # de-dup, preserve order
            covered = {c.ticker.upper() for c in chunks}    # always a subset (IN filter)
            if len(covered) < len(requested):
                shown = [t for t in requested if t in covered]
                names = (
                    f"{shown[0]} only" if len(shown) == 1
                    else f"{', '.join(shown[:-1])} and {shown[-1]} only"
                )
                text_header = f"**From SEC filing text ({names}):**"
        merged = (
            f"**From structured financial data (XBRL metrics) — the authoritative exact figures:**\n\n{graph_ans}"
            f"\n\n---\n\n"
            f"{text_header}\n\n{vec_ans}"
        )
        return merged, chunks, grefs, "both"

    if had_graph:
        return graph_ans, [], grefs, "graph"

    if chunks:
        return vec_ans, chunks, [], "vector"

    return NO_CONTEXT_MESSAGE, [], [], "none"


# Quota messages, shared by route_question (non-streaming) and prepare_chat_stream.
_QUOTA_MSG_TXT = (
    "The daily embedding quota is exhausted — vector search is unavailable until "
    "midnight UTC. Try a metrics or comparison question; those use the structured "
    "data graph and have no embedding quota."
)
_PER_MINUTE_QUOTA_MSG_TXT = (
    "The per-minute embedding rate limit was hit — vector search is temporarily "
    "unavailable. Please try again in about 60 seconds, or rephrase as a metrics "
    "question (e.g. 'Apple gross margin FY2024') to use the structured data graph "
    "instead (zero embedding calls)."
)


def prepare_chat_stream(
    question: str,
    k: int = 5,
    ticker: Optional[str] = None,
    tickers: Optional[list[str]] = None,
    form: Optional[str] = None,
) -> tuple[list[dict], list, list, str, Optional[dict]]:
    """
    Streaming counterpart to route_question. Does ONLY the pre-generation work
    (classification + retrieval), then returns an ordered list of `segments` to
    emit, the source chunks, the graph-fact citation cards, and the retrieval path.

    Each segment is one of:
      {"kind": "llm",  "system": str, "prompt": str, "temperature": float}
          -> the caller streams generate_content_stream token-by-token
      {"kind": "text", "text": str}
          -> emitted verbatim (deterministic headers / notes / "no context")

    Splitting retrieval from generation is what makes real streaming possible:
    the router's keyword classification + graph/vector retrieval run first (the
    "bird" phase, nothing to stream yet), then the model output streams. The
    graph/both deterministic tails and merge headers are plain `text` segments,
    so the streamed answer is byte-for-byte the same shape as the non-streaming
    /chat answer.
    """
    from ..data_extract.rag import (
        search, _format_context, SYSTEM_PROMPT, NO_CONTEXT_MESSAGE,
    )

    def _llm(system: str, prompt: str, temp: float) -> dict:
        return {"kind": "llm", "system": system, "prompt": prompt, "temperature": temp}

    def _text(text: str) -> dict:
        return {"kind": "text", "text": text}

    # --- Vector scope resolution (identical precedence to route_question) ------
    known = _graph_tickers()
    mentioned = [t for t in _extract_tickers(question, known_tickers=known) if t in known]
    explicit = [t.strip().upper() for t in (tickers or []) if t and t.strip()]
    if explicit:
        vector_scope: Optional[list[str]] = explicit
    elif ticker:
        vector_scope = [ticker.strip().upper()]
    elif mentioned:
        vector_scope = mentioned
    else:
        vector_scope = None

    path = classify_question(question)
    logger.info("Router(stream): path=%s | %s", path, question[:80])

    def _vector_prep_raw() -> tuple[Optional[str], list, Optional[str]]:
        """Retrieve chunks + build the prompt. Returns (prompt, chunks, err_text)."""
        try:
            chunks = search(question, k=k, tickers=vector_scope, form=form)
        except DailyQuotaExceededError:
            return None, [], _QUOTA_MSG_TXT
        except PerMinuteQuotaError:
            return None, [], _PER_MINUTE_QUOTA_MSG_TXT
        except Exception as exc:
            # Vector store unreachable etc. — degrade to "no data" (None err ->
            # NO_CONTEXT_MESSAGE) rather than crash the stream.
            logger.warning("Vector retrieval failed (stream): %s", exc)
            return None, [], None
        if not chunks:
            return None, [], None
        prompt = f"Context:\n{_format_context(chunks)}\n\nQuestion:\n{question}"
        return prompt, chunks, None

    def _vector_segments() -> tuple[list[dict], list, str]:
        prompt, chunks, err = _vector_prep_raw()
        if err:
            return [_text(err)], [], "none"
        if prompt is None:
            return [_text(NO_CONTEXT_MESSAGE)], [], "none"
        return [_llm(SYSTEM_PROMPT, prompt, 0.2)], chunks, "vector"

    if path == "vector":
        segs, chunks, vpath = _vector_segments()
        return segs, chunks, [], vpath, None

    if path == "graph":
        gprompt, gtail, grefs, gchart = _graph_prompt(question)
        if gprompt is not None:
            segs = [_llm(_GRAPH_SYSTEM, gprompt, 0.1)]
            if gtail:
                segs.append(_text(gtail))
            return segs, [], grefs, "graph", gchart
        segs, chunks, vpath = _vector_segments()
        return segs, chunks, [], ("vector_no_graph" if vpath == "vector" else vpath), None

    # path == "both": retrieve both halves concurrently (the bird phase), then
    # stream graph generation followed by vector generation.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_graph = pool.submit(_graph_prompt, question)
        fut_vector = pool.submit(_vector_prep_raw)
        gprompt, gtail, grefs, gchart = fut_graph.result()
        vprompt, chunks, verr = fut_vector.result()

    had_graph = gprompt is not None

    if had_graph and chunks:
        # Coverage-qualified filing-text header (mirrors route_question's "both").
        text_header = "**From SEC filing text:**"
        if vector_scope:
            requested = list(dict.fromkeys(vector_scope))
            covered = {c.ticker.upper() for c in chunks}
            if len(covered) < len(requested):
                shown = [t for t in requested if t in covered]
                names = (
                    f"{shown[0]} only" if len(shown) == 1
                    else f"{', '.join(shown[:-1])} and {shown[-1]} only"
                )
                text_header = f"**From SEC filing text ({names}):**"
        segs = [
            _text("**From structured financial data (XBRL metrics) — the authoritative exact figures:**\n\n"),
            _llm(_GRAPH_SYSTEM, gprompt, 0.1),
        ]
        if gtail:
            segs.append(_text(gtail))
        segs.append(_text(f"\n\n---\n\n{text_header}\n\n"))
        segs.append(_llm(SYSTEM_PROMPT, vprompt, 0.2))
        return segs, chunks, grefs, "both", gchart

    if had_graph:
        segs = [_llm(_GRAPH_SYSTEM, gprompt, 0.1)]
        if gtail:
            segs.append(_text(gtail))
        return segs, [], grefs, "graph", gchart

    if chunks:
        return [_llm(SYSTEM_PROMPT, vprompt, 0.2)], chunks, [], "vector", None

    if verr:
        return [_text(verr)], [], [], "none", None

    return [_text(NO_CONTEXT_MESSAGE)], [], [], "none", None
