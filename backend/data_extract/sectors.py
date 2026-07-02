"""
backend/data_extract/sectors.py

Maps SEC SIC codes (from EDGAR) to the 11 GICS sectors used by the State Street
Select Sector SPDR ETFs.

IMPORTANT — this mapping is APPROXIMATE. SIC is an older, finer-grained taxonomy
than GICS and the two do not line up cleanly, so this groups SIC ranges into the
closest sector. Some codes are genuine judgment calls (e.g. internet/media firms
straddle Information Technology vs. Communication Services; electrical equipment
straddles IT vs. Industrials). Treat the result as a strong hint, not ground
truth, and verify the sectors that matter for your comparisons.

EDGAR exposes the SIC code in the submissions metadata
(https://data.sec.gov/submissions/CIK##########.json -> "sic" / "sicDescription").
Capture it during ingestion, resolve it here, and store the sector on the filing.
"""

from __future__ import annotations

from typing import Optional

# (id, label, SPDR ETF ticker). Label uses the official GICS name
# ("Information Technology"); the XLK ETF is branded "Technology".
SECTORS: list[tuple[str, str, str]] = [
    ("communication_services", "Communication Services", "XLC"),
    ("consumer_discretionary", "Consumer Discretionary", "XLY"),
    ("consumer_staples",       "Consumer Staples",       "XLP"),
    ("energy",                 "Energy",                 "XLE"),
    ("financials",             "Financials",             "XLF"),
    ("health_care",            "Health Care",            "XLV"),
    ("industrials",            "Industrials",            "XLI"),
    ("materials",              "Materials",              "XLB"),
    ("real_estate",            "Real Estate",            "XLRE"),
    ("information_technology", "Information Technology",  "XLK"),
    ("utilities",              "Utilities",              "XLU"),
]

SECTOR_LABELS: dict[str, str] = {sid: label for sid, label, _ in SECTORS}
SECTOR_ETF: dict[str, str] = {sid: etf for sid, _, etf in SECTORS}


def _in_any(code: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= code <= hi for lo, hi in ranges)


def sic_to_sector(sic) -> Optional[str]:
    """
    Resolve a 4-digit SIC code to a GICS sector id, or None if unmapped.
    Accepts int or str. Order matters: narrower carve-outs are checked before
    the broad manufacturing/services bands so they aren't swallowed.
    """
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return None

    # Energy — oil & gas extraction, coal, petroleum refining
    if _in_any(code, [(1200, 1241), (1300, 1399), (2900, 2999)]):
        return "energy"

    # Real Estate — operators, lessors, REITs (carved out of Financials)
    if _in_any(code, [(6500, 6599), (6798, 6798)]):
        return "real_estate"

    # Financials — banks, insurance, securities, holding companies
    if _in_any(code, [(6000, 6499), (6700, 6799)]):
        return "financials"

    # Utilities — electric, gas, water, sanitary services
    if _in_any(code, [(4900, 4999)]):
        return "utilities"

    # Health Care — pharmaceuticals, medical devices, health services
    if _in_any(code, [(2830, 2836), (3840, 3851), (8000, 8099)]):
        return "health_care"

    # Information Technology — computers, semiconductors, electronics, software
    if _in_any(code, [(3570, 3579), (3600, 3674), (3677, 3699), (7370, 7379)]):
        return "information_technology"

    # Communication Services — publishing, telecom, broadcasting, entertainment
    if _in_any(code, [(2700, 2799), (4800, 4899), (7800, 7849), (7900, 7999)]):
        return "communication_services"

    # Consumer Staples — food, beverages, tobacco, household products, food/drug retail
    if _in_any(code, [(2000, 2099), (2100, 2199), (2840, 2844), (5400, 5499), (5912, 5912)]):
        return "consumer_staples"

    # Consumer Discretionary — apparel, autos, general/apparel retail, restaurants, hotels
    if _in_any(code, [(2300, 2399), (3710, 3716), (5200, 5399), (5500, 5911), (5913, 5999), (7000, 7299)]):
        return "consumer_discretionary"

    # Materials — chemicals, metals & mining, paper, building materials, glass
    if _in_any(code, [(1000, 1099), (1400, 1499), (2600, 2699), (2800, 2829), (2850, 2899), (3200, 3399)]):
        return "materials"

    # Industrials — construction, machinery, aerospace, transport services
    if _in_any(code, [(1500, 1799), (3400, 3569), (3580, 3599), (3700, 3709), (3720, 3799), (4000, 4799)]):
        return "industrials"

    return None


def sector_label(sector_id: Optional[str]) -> Optional[str]:
    """Human-readable label for a sector id, or None."""
    return SECTOR_LABELS.get(sector_id) if sector_id else None


if __name__ == "__main__":
    # Quick sanity check against a few well-known filers' SIC codes.
    samples = {
        "Gap (apparel retail)": 5651,
        "Apple (electronic computers)": 3571,
        "JPMorgan (national commercial banks)": 6021,
        "ExxonMobil (petroleum refining)": 2911,
        "Pfizer (pharmaceutical preparations)": 2834,
        "Simon Property (REIT)": 6798,
        "Duke Energy (electric services)": 4911,
        "Verizon (telephone communications)": 4813,
    }
    for name, sic in samples.items():
        sid = sic_to_sector(sic)
        print(f"{sic}  {name:42s} -> {sector_label(sid) or 'UNMAPPED'}")