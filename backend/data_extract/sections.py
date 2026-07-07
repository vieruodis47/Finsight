"""
Narrative section extraction from filing documents.

The prose sections (business, risk factors, MD&A) are NOT in XBRL, so they are
parsed out of the filing HTML. This module depends on ``sec_client`` for the
raw document fetch.
"""

import re

from .sec_client import get_filings, get_document_url, fetch_and_parse


def extract_sections(text: str) -> dict:
    """
    Rule-based section extraction using known 10-K/10-Q header keywords.
    Handles TOC false-matches by requiring sections to have substantial content.
    Many filings (e.g. MSFT) have a TOC where Item headers appear with just page
    numbers, then again in the body with real content. We collect ALL matches per
    section key and keep the one with the most content.
    """
    section_names = {
        "Item 1.": "business",
        "Item 1A.": "risk_factors",
        "Item 1B.": "unresolved_staff_comments",
        "Item 1C.": "cybersecurity",
        "Item 2.": "properties",
        "Item 3.": "legal_proceedings",
        "Item 4.": "mine_safety",
        "Item 5.": "market_for_equity",
        "Item 6.": "reserved",
        "Item 7.": "mda",
        "Item 7A.": "market_risk",
        "Item 8.": "financial_statements",
        "Item 9.": "accountant_changes",
        "Item 9A.": "controls_procedures",
        "Item 9B.": "other_information",
    }

    section_keywords = list(section_names.keys())
    # Pre-compute uppercase versions once for O(1) per-line comparison.
    section_keywords_upper = [kw.upper() for kw in section_keywords]

    # Collect all occurrences of each section
    # sections_all maps section_key -> list of content strings
    sections_all: dict[str, list[str]] = {}
    lines = text.splitlines()
    current_key = "header"
    buffer: list[str] = []

    for line in lines:
        # Normalize non-breaking spaces (\xa0) to regular spaces before matching.
        # Some filers (e.g. Nike) emit "ITEM\xa01." in uppercase — both the case
        # difference and the non-breaking space would prevent startswith from matching.
        stripped_norm = line.strip().replace("\xa0", " ").upper()
        matched_kw = next(
            (kw for kw, kw_up in zip(section_keywords, section_keywords_upper)
             if stripped_norm.startswith(kw_up) and len(line) < 120),
            None
        )
        if matched_kw:
            # Save current buffer under current key
            content = "\n".join(buffer).strip()
            if content:
                sections_all.setdefault(current_key, []).append(content)
            current_key = section_names.get(matched_kw, matched_kw)
            buffer = [line]
        else:
            buffer.append(line)

    # Save last buffer
    content = "\n".join(buffer).strip()
    if content:
        sections_all.setdefault(current_key, []).append(content)

    # For each section keep the occurrence with the most content (skips TOC stubs)
    sections: dict[str, str] = {}
    for key, occurrences in sections_all.items():
        best = max(occurrences, key=len)
        # Only keep if it has at least 200 chars of real content
        if len(best) >= 200:
            sections[key] = best

    # Drop header if it's mostly XBRL noise
    if "header" in sections:
        header = sections["header"]
        if len(re.findall(r"[.!?]", header)) < 5:
            del sections["header"]

    return sections


def get_narrative(cik: str) -> dict:
    """
    XBRL has no MD&A, risk factors, or business description — that prose is what the AI summarizes and answers questions
    against. This reuses the existing document fetch + section splitter, and keep only the sections the model needs
    """
    filing = get_filings(cik, form_type="10-K", limit=1)[0]
    url = get_document_url(cik, filing["accession"], filing["primary_document"])
    sections = extract_sections(fetch_and_parse(url))

    return {k: sections[k] for k in ("business", "risk_factors", "mda")
            if k in sections}
