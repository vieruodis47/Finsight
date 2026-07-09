"""
SEC EDGAR client: all raw network access to SEC APIs and filing documents.

This is the low-level I/O layer. Everything here talks to sec.gov; no module
above this one should call ``requests`` directly.
"""

import logging
import os
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# SEC requires a descriptive User-Agent string or requests return 403.
# Set SEC_USER_AGENT in the environment; fall back to a generic placeholder.
SEC_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "FinSight contact@example.com"),
    "Accept-Encoding": "gzip, deflate",
}


def get_sic(cik: str) -> str | None:
    """Return the 4-digit SIC code from submissions metadata, or None on failure."""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers={**SEC_HEADERS, "Host": "data.sec.gov"})
        r.raise_for_status()
        sic = r.json().get("sic")
        return str(sic) if sic else None
    except Exception as e:
        logger.warning("Could not fetch SIC for CIK %s: %s", cik, e)
        return None


def get_company_facts(cik: str) -> dict:
    """All XBRL facts SEC has for a company, in one cached call."""
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        r = requests.get(url, headers={**SEC_HEADERS, "Host": "data.sec.gov"})
        r.raise_for_status()
        return r.json()

    except requests.exceptions.Timeout as e:
        logger.error("Timeout fetching company facts for CIK %s: %s", cik, e)
        raise

    except requests.RequestException as e:
        logger.error("Request error fetching company facts for CIK %s: %s", cik, e)
        raise


def get_cik(ticker: str) -> str:
    """Look up a company's CIK number by ticker symbol."""
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(url, headers={**SEC_HEADERS, "Host": "www.sec.gov"})
        r.raise_for_status()
        data = r.json()
        for entry in data.values():
            if entry["ticker"].upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        raise ValueError(f"Ticker '{ticker}' not found in SEC database")

    except requests.exceptions.Timeout as e:
        logger.error("Request timed out fetching CIK for %s: %s", ticker, e)
        raise

    except requests.exceptions.RequestException as e:
        logger.error("Request failed fetching CIK for %s: %s", ticker, e)
        raise


def get_filings(cik: str, form_type: str = "10-K", limit: int = 5) -> list:
    """Get recent filings of a given type for a company."""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers={**SEC_HEADERS, "Host": "data.sec.gov"})
        r.raise_for_status()
        data = r.json()

        recent = data["filings"]["recent"]
        results = []

        for i, form in enumerate(recent["form"]):
            if form == form_type:
                results.append({
                    "form": form,
                    "date": recent["filingDate"][i],
                    "accession": recent["accessionNumber"][i],
                    "primary_document": recent["primaryDocument"][i],
                })
            if len(results) >= limit:
                break

        return results

    except requests.exceptions.Timeout as e:
        logger.error("Timeout fetching filings for CIK %s: %s", cik, e)
        raise

    except requests.RequestException as e:
        logger.error("Request error fetching filings for CIK %s: %s", cik, e)
        raise


def get_document_url(cik: str, accession: str, primary_doc: str) -> str:
    """Build the full URL to the filing document on SEC EDGAR."""
    accession_clean = accession.replace("-", "")
    cik_int = int(cik)
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{primary_doc}"


def fetch_and_parse(url: str) -> str:
    """Fetch an SEC filing HTML page and return clean plain text."""
    try:
        r = requests.get(url, headers={**SEC_HEADERS, "Host": "www.sec.gov"})
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "lxml")

    except requests.RequestException as e:
        logger.error("Error fetching document %s: %s", url, e)
        raise

    # Remove noise tags
    for tag in soup(["script", "style", "meta", "noscript", "img", "head"]):
        tag.decompose()

    # Strip inline XBRL tags (ix:*) but keep their text content
    for tag in soup.find_all(re.compile(r"^ix:")):
        tag.unwrap()

    # Remove hidden elements (XBRL metadata often lives here)
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    for tag in soup.find_all(attrs={"hidden": True}):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Remove blank lines and lines that are pure XBRL namespace garbage
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^https?://[a-z./]+#", line):
            continue
        if re.match(r"^[a-z]+:[A-Z][a-zA-Z]+$", line):
            continue
        lines.append(line)

    return "\n".join(lines)
