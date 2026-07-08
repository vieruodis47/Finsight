"""
Structured XBRL extraction from SEC ``companyfacts`` data.

Standardized and company-agnostic: every number comes from an official us-gaap
concept, so the same code works for any filer. Pure logic over the facts dict
returned by ``sec_client.get_company_facts``.

Period anchoring
----------------
A company's income statement, balance sheet, and cash flow must all come from the
SAME fiscal year. Selecting each field's "latest" value independently breaks when a
filer migrates an XBRL tag: the old concept's newest value is stale (an earlier year)
while every other line is current, producing impossible margins (>100%). So we first
resolve a single target fiscal year-end from reliably-tagged concepts, then pull every
field at that period.

Stale values
------------
When _pick() cannot find any candidate concept at the target period it falls back to
the concept's latest-ever value, marked stale=True. A stale value is from a prior
fiscal year — emitting it alongside current-year figures creates impossible results
(e.g. prior-year net income paired with current-year operating loss). We therefore
drop stale hits entirely and leave the field absent rather than pollute the output
with cross-year contamination.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

# field -> ordered list of candidate us-gaap concepts. Multiple candidates
# because filers tag the same line differently / older filings use legacy tags.
INCOME_CONCEPTS = {
    "total_revenue_millions": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cost_of_revenue_millions": [
        "CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
    ],
    "gross_margin_millions": ["GrossProfit"],
    "rd_expense_millions": ["ResearchAndDevelopmentExpense"],
    "sga_expense_millions": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "total_opex_millions": ["OperatingExpenses", "CostsAndExpenses"],
    "operating_income_millions": ["OperatingIncomeLoss"],
    "income_tax_millions": ["IncomeTaxExpenseBenefit"],
    # NetIncomeLoss is the standard tag; some filers (e.g. Ford FY2025) omit it
    # and tag only the "available to common stockholders" variant instead.
    # The fallback order guarantees we pick the current-year figure from whichever
    # concept the filer actually populated, rather than a stale prior-year value.
    "net_income_millions": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
    ],
}

INCOME_PER_SHARE = {  # unit "USD/shares"; never scaled to millions
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}

INCOME_RATES = {  # unit "pure"; a decimal ratio reported as a percent
    "effective_tax_rate_pct": ["EffectiveIncomeTaxRateContinuingOperations"],
}

BALANCE_CONCEPTS = {
    "cash_and_equivalents_millions": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_current_assets_millions": ["AssetsCurrent"],
    "total_assets_millions": ["Assets"],
    "total_current_liabilities": ["LiabilitiesCurrent"],
    "total_liabilities_millions": ["Liabilities"],
    "shareholders_equity_millions": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "long_term_debt_millions": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "retained_earnings_millions": ["RetainedEarningsAccumulatedDeficit"],
    "ppe_net_millions": ["PropertyPlantAndEquipmentNet"],
    "inventories_millions": ["InventoryNet"],
    "accounts_receivable_millions": ["AccountsReceivableNetCurrent"],
}

CASHFLOW_CONCEPTS = {
    "operating_cash_flow_millions": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "investing_cash_flow_millions": ["NetCashProvidedByUsedInInvestingActivities"],
    "financing_cash_flow_millions": ["NetCashProvidedByUsedInFinancingActivities"],
    "capex_millions": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "dividends_paid_millions": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "share_repurchases_millions": ["PaymentsForRepurchaseOfCommonStock"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ],
    "share_based_comp_millions": ["ShareBasedCompensation"],
}

# Concepts used to resolve the target fiscal year-end. These are tagged
# consistently by virtually every filer at every period, so their most recent
# 10-K value reliably identifies the current fiscal year.
ANCHOR_CONCEPTS = ["Assets", "Liabilities", "StockholdersEquity", "NetIncomeLoss"]

# Kept for the single-field helper + extension-tag tests.
CONCEPT_MAP = {
    "total_revenue": ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
    "net_income":          ("us-gaap", "NetIncomeLoss", "USD"),
    "total_assets":        ("us-gaap", "Assets", "USD"),
    "total_liabilities":   ("us-gaap", "Liabilities", "USD"),
    "shareholders_equity": ("us-gaap", "StockholdersEquity", "USD"),
    "operating_cash_flow": ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD"),
    "cash_and_equivalents": ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"),
}

EXTENSION_OVERRIDES = {
    "product_revenue": ["RevenueFromProducts", "ProductRevenue"],
}

# Minimum span (days) for a duration fact to count as a full fiscal year.
# Excludes quarterly (~90d), half-year (~180d), and 9-month YTD (~270d) periods,
# while admitting 52/53-week fiscal years (~364d).
_FULL_YEAR_MIN_DAYS = 300
# Tolerance (days) when matching a field's period end to the target year-end.
# Income/balance/cash-flow ends are normally identical, but a small window guards
# against off-by-a-few-days tagging.
_PERIOD_TOLERANCE_DAYS = 45


def _parse(d):
    try:
        return date.fromisoformat(d)
    except Exception:
        return None


def _annual_rows(facts, taxonomy, concept, unit):
    """All full-year 10-K rows for one concept (quarterlies/partials removed)."""
    try:
        rows = facts["facts"][taxonomy][concept]["units"][unit]
    except KeyError:
        return []

    out = []
    for r in rows:
        if r.get("form") != "10-K" or "end" not in r:
            continue
        # Duration facts carry 'start'; require a ~full-year span. Instant facts
        # (balance sheet) have no 'start' and are kept as-is.
        if "start" in r:
            d0, d1 = _parse(r["start"]), _parse(r["end"])
            if d0 and d1 and (d1 - d0).days < _FULL_YEAR_MIN_DAYS:
                continue
        out.append(r)
    return out


def latest_annual(facts, taxonomy, concept, unit):
    """Most recent 10-K (full-year) value for one concept, with its period."""
    rows = _annual_rows(facts, taxonomy, concept, unit)
    if not rows:
        return None
    best = max(rows, key=lambda r: r["end"])
    return {"value": best["val"], "fy": best.get("fy"), "end": best["end"]}


def target_period_end(facts):
    """The company's most recent fiscal year-end, from reliably-tagged concepts.

    Returns an ISO date string (e.g. '2026-01-25') or None.
    """
    ends = set()
    cset = facts.get("facts", {}).get("us-gaap", {})
    for concept in ANCHOR_CONCEPTS:
        for unit in cset.get(concept, {}).get("units", {}):
            for r in _annual_rows(facts, "us-gaap", concept, unit):
                ends.add(r["end"])
    return max(ends) if ends else None


def _pick(facts: dict, concepts: list[str], unit: str = "USD", target_end: Optional[str] = None) -> Optional[dict]:
    """First candidate concept with a value anchored to ``target_end``.

    Resolution order, per the candidate list:
      1. exact match on the target fiscal year-end,
      2. a year-end within tolerance of the target (handles minor tagging drift),
      3. fallback to the concept's latest available value (flagged ``stale``).

    Callers that require a current-year value should reject stale hits.
    """
    rows_by_concept = [(c, _annual_rows(facts, "us-gaap", c, unit)) for c in concepts]

    if target_end:
        t = _parse(target_end)
        # 1) exact period match — check all candidates before giving up
        for concept, rows in rows_by_concept:
            exact = [r for r in rows if r["end"] == target_end]
            if exact:
                best = max(exact, key=lambda r: r.get("filed", ""))
                return {"value": best["val"], "fy": best.get("fy"), "end": best["end"]}
        # 2) near match (same fiscal year, slightly different end date)
        if t:
            for concept, rows in rows_by_concept:
                near = [r for r in rows
                        if _parse(r["end"]) and abs((_parse(r["end"]) - t).days) <= _PERIOD_TOLERANCE_DAYS]
                if near:
                    best = max(near, key=lambda r: r["end"])
                    return {"value": best["val"], "fy": best.get("fy"), "end": best["end"]}

    # 3) last resort: latest available for any candidate
    for concept, rows in rows_by_concept:
        if rows:
            best = max(rows, key=lambda r: r["end"])
            return {"value": best["val"], "fy": best.get("fy"), "end": best["end"], "stale": True}
    return None


def _millions(value):
    """Scale a raw number to millions and round to 2 decimals."""
    return round(value / 1_000_000, 2)


def extract_income_statement(facts: dict) -> dict:
    """Income-statement metrics from XBRL (works for any filer), all anchored to
    the same fiscal year so derived margins are coherent."""
    out = {}
    target = target_period_end(facts)

    for field, concepts in INCOME_CONCEPTS.items():
        hit = _pick(facts, concepts, "USD", target)
        # Reject stale hits: a value from a prior fiscal year mixed with current-year
        # figures produces impossible results (e.g. prior-year net income against a
        # current-year operating loss). Leave the field absent instead.
        if hit and not hit.get("stale"):
            out[field] = _millions(hit["value"])

    for field, concepts in INCOME_PER_SHARE.items():
        hit = _pick(facts, concepts, "USD/shares", target)
        if hit and not hit.get("stale"):
            out[field] = hit["value"]

    for field, concepts in INCOME_RATES.items():
        hit = _pick(facts, concepts, "pure", target)
        if hit and not hit.get("stale"):
            out[field] = round(hit["value"] * 100, 2)

    rev = out.get("total_revenue_millions")
    gp = out.get("gross_margin_millions")
    # Sanity guard: gross profit can't exceed revenue. If it does, the revenue
    # selection is wrong (e.g. an un-anchored stale tag slipped through) — drop
    # revenue and revenue-derived fields rather than render impossible margins.
    if rev and gp and gp > rev * 1.01:
        out.pop("total_revenue_millions", None)
        rev = None

    if gp and rev:
        out["gross_margin_pct"] = round(gp / rev * 100, 2)

    return out


def extract_income_multiyear(facts: dict, n_years: int = 5) -> dict:
    """
    Return income-statement metrics for each available fiscal year.

    Unlike extract_income_statement (which returns only the most recent year),
    this function reads every 10-K annual row from the XBRL facts and groups them
    by period-end year so the caller gets a multi-year dataset suitable for
    year-over-year comparisons.

    Returns a dict keyed by four-digit year string:
        { "2025": { "operating_income_millions": 133050.0, ... },
          "2024": { "operating_income_millions": 123216.0, ... },
          ...  }

    Deduplication: the same period sometimes appears in multiple filings
    (comparative columns).  The most-recently-filed value per period end is kept.
    Only the n_years most recent years are returned.
    """
    from collections import defaultdict

    # field → {period_end → best_row}
    by_field_year: dict = defaultdict(dict)

    for field, concepts in INCOME_CONCEPTS.items():
        for concept in concepts:
            for r in _annual_rows(facts, "us-gaap", concept, "USD"):
                end = r["end"]
                existing = by_field_year[field].get(end)
                if existing is None or r.get("filed", "") > existing.get("filed", ""):
                    by_field_year[field][end] = r
            if by_field_year[field]:
                break  # first candidate concept with any data wins

    # Collect all available period-end dates
    all_ends: set = set()
    for end_map in by_field_year.values():
        all_ends.update(end_map.keys())
    if not all_ends:
        return {}

    # Sort descending and take the n_years most recent period ends
    sorted_ends = sorted(all_ends, reverse=True)[:n_years]

    per_year: dict = {}
    for end in sorted_ends:
        year = end[:4]
        year_data: dict = {}
        for field, end_map in by_field_year.items():
            row = end_map.get(end)
            if row is not None:
                year_data[field] = _millions(row["val"])
        if year_data:
            # Compute gross margin pct if revenue and gross profit are available
            rev = year_data.get("total_revenue_millions")
            gp  = year_data.get("gross_margin_millions")
            if rev and gp and rev > 0:
                year_data["gross_margin_pct"] = round(gp / rev * 100, 2)
            per_year[year] = {"income_statement": year_data}

    return per_year


def extract_balance_multiyear(facts: dict, n_years: int = 5) -> dict:
    """
    Return balance-sheet metrics for each available fiscal year.

    Mirrors extract_income_multiyear but for BALANCE_CONCEPTS (instant facts).
    Returns a dict keyed by four-digit year string:
        { "2025": { "balance_sheet": { "long_term_debt_millions": ..., ... } },
          "2024": { "balance_sheet": { ... } }, ... }
    """
    from collections import defaultdict

    by_field_year: dict = defaultdict(dict)

    for field, concepts in BALANCE_CONCEPTS.items():
        for concept in concepts:
            for r in _annual_rows(facts, "us-gaap", concept, "USD"):
                end = r["end"]
                existing = by_field_year[field].get(end)
                if existing is None or r.get("filed", "") > existing.get("filed", ""):
                    by_field_year[field][end] = r
        # No break: collect from all candidate concepts so that companies that
        # changed XBRL tags across years (e.g. TSLA debt: LongTermDebtNoncurrent
        # → LongTermDebt) still get populated for all years.  The filed-date
        # deduplication above keeps the most-recently-filed value per period end.

    all_ends: set = set()
    for end_map in by_field_year.values():
        all_ends.update(end_map.keys())
    if not all_ends:
        return {}

    # Multiple period-end dates can share the same four-digit year
    # (e.g. "2024-12-31" and "2024-01-01" from a cumulative-effect-adjustment
    # instant fact).  Pick the canonical date per year: the one covered by the
    # most fields; break ties by latest date string.
    field_count = {end: sum(1 for m in by_field_year.values() if end in m)
                   for end in all_ends}
    year_to_canonical: dict = {}
    for end in all_ends:
        year = end[:4]
        prev = year_to_canonical.get(year)
        if prev is None or (field_count[end], end) > (field_count[prev], prev):
            year_to_canonical[year] = end

    sorted_years = sorted(year_to_canonical.keys(), reverse=True)[:n_years]

    per_year: dict = {}
    for year in sorted_years:
        end = year_to_canonical[year]
        year_data: dict = {}
        for field, end_map in by_field_year.items():
            row = end_map.get(end)
            if row is not None:
                year_data[field] = _millions(row["val"])
        if year_data:
            cur_assets = year_data.get("total_current_assets_millions")
            cur_liab = year_data.get("total_current_liabilities")
            if cur_assets and cur_liab:
                year_data["working_capital_millions"] = round(cur_assets - cur_liab, 2)
            per_year[year] = {"balance_sheet": year_data}

    return per_year


def extract_cash_flow_multiyear(facts: dict, n_years: int = 5) -> dict:
    """
    Return cash-flow metrics for each available fiscal year.

    Mirrors extract_income_multiyear but for CASHFLOW_CONCEPTS (duration facts).
    Returns:
        { "2025": { "cash_flow": { "free_cash_flow_millions": ..., ... } },
          "2024": { "cash_flow": { ... } }, ... }

    free_cash_flow_millions is computed as operating_cash_flow - capex when both
    are present. No break between candidate concepts: cash-flow filers sometimes
    switch between tags across years (same as balance sheet).
    """
    from collections import defaultdict

    by_field_year: dict = defaultdict(dict)

    for field, concepts in CASHFLOW_CONCEPTS.items():
        for concept in concepts:
            for r in _annual_rows(facts, "us-gaap", concept, "USD"):
                end = r["end"]
                existing = by_field_year[field].get(end)
                if existing is None or r.get("filed", "") > existing.get("filed", ""):
                    by_field_year[field][end] = r

    all_ends: set = set()
    for end_map in by_field_year.values():
        all_ends.update(end_map.keys())
    if not all_ends:
        return {}

    sorted_ends = sorted(all_ends, reverse=True)[:n_years]

    per_year: dict = {}
    for end in sorted_ends:
        year = end[:4]
        year_data: dict = {}
        for field, end_map in by_field_year.items():
            row = end_map.get(end)
            if row is not None:
                year_data[field] = _millions(row["val"])
        if year_data:
            ocf = year_data.get("operating_cash_flow_millions")
            cap = year_data.get("capex_millions")
            if ocf is not None and cap is not None:
                year_data["free_cash_flow_millions"] = round(ocf - cap, 2)
            per_year[year] = {"cash_flow": year_data}

    return per_year


def extract_balance_sheet(facts: dict) -> dict:
    """Balance-sheet metrics from XBRL, anchored to the target fiscal year-end."""
    out = {}
    target = target_period_end(facts)

    for field, concepts in BALANCE_CONCEPTS.items():
        hit = _pick(facts, concepts, "USD", target)
        if hit and not hit.get("stale"):
            out[field] = _millions(hit["value"])

    if out.get("total_current_assets_millions") and out.get("total_current_liabilities"):
        out["working_capital_millions"] = round(
            out["total_current_assets_millions"] - out["total_current_liabilities"], 2)

    return out


def extract_cash_flow(facts: dict) -> dict:
    """Cash-flow metrics from XBRL, anchored to the target fiscal year-end."""
    out = {}
    target = target_period_end(facts)

    for field, concepts in CASHFLOW_CONCEPTS.items():
        hit = _pick(facts, concepts, "USD", target)
        if hit and not hit.get("stale"):
            out[field] = _millions(hit["value"])

    if out.get("operating_cash_flow_millions") and out.get("capex_millions"):
        out["free_cash_flow_millions"] = round(
            out["operating_cash_flow_millions"] - out["capex_millions"], 2)

    return out


def get_fact(facts, field):
    """Single field: standard us-gaap concept first, then company extension tags."""
    mapped = CONCEPT_MAP.get(field)
    if mapped:
        taxonomy, concept, unit = mapped
        hit = latest_annual(facts, taxonomy, concept, unit)
        if hit:
            return hit

    for tax, concepts in facts.get("facts", {}).items():
        if tax in ("us-gaap", "dei"):
            continue

        for cand in EXTENSION_OVERRIDES.get(field, []):
            if cand in concepts:
                for u in concepts[cand]["units"]:
                    hit = latest_annual(facts, tax, cand, u)
                    if hit:
                        return hit
    return None
