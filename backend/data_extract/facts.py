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
"""

from datetime import date

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
    "net_income_millions": ["NetIncomeLoss"],
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


def _pick(facts, concepts, unit="USD", target_end=None):
    """First candidate concept with a value anchored to ``target_end``.

    Resolution order, per the candidate list:
      1. exact match on the target fiscal year-end,
      2. a year-end within tolerance of the target (handles minor tagging drift),
      3. fallback to the concept's latest available value (flagged ``stale``),
         so a filer with an unusual period still yields *something*.
    """
    rows_by_concept = [(c, _annual_rows(facts, "us-gaap", c, unit)) for c in concepts]

    if target_end:
        t = _parse(target_end)
        # 1) exact period match
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
        if hit:
            out[field] = _millions(hit["value"])

    for field, concepts in INCOME_PER_SHARE.items():
        hit = _pick(facts, concepts, "USD/shares", target)
        if hit:
            out[field] = hit["value"]

    for field, concepts in INCOME_RATES.items():
        hit = _pick(facts, concepts, "pure", target)
        if hit:
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


def extract_balance_sheet(facts: dict) -> dict:
    """Balance-sheet metrics from XBRL, anchored to the target fiscal year-end."""
    out = {}
    target = target_period_end(facts)

    for field, concepts in BALANCE_CONCEPTS.items():
        hit = _pick(facts, concepts, "USD", target)
        if hit:
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
        if hit:
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