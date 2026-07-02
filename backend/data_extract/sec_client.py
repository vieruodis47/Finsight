"""
SEC EDGAR client: all raw network access to SEC APIs and filing documents.

This is the low-level I/O layer. Everything here talks to sec.gov; no module
above this one should call ``requests`` directly.
"""

from bs4 import BeautifulSoup

import re
import requests


# SEC requires a descriptive User-Agent or you'll get 403s
# Replace with your name and UW email
SEC_HEADERS = {
    "User-Agent": "FinSight rahmansyah@wisc.edu",
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
        print(f"Warning: could not fetch SIC for CIK {cik}: {e}")
        return None


def get_company_facts(cik: str) -> dict:
    """All XBRL facts SEC has for a company, in one cached call."""
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        r = requests.get(url, headers={**SEC_HEADERS, "Host": "data.sec.gov"})
        r.raise_for_status()
        return r.json()

    except requests.exceptions.Timeout as e:
        print(f"Timeout error fetching company facts for CIK {cik}: {e}")
        raise

    except requests.RequestException as e:
        print(f"Error fetching company facts for CIK {cik}: {e}")
        raise

    except Exception as e:
        print(f"Unexpected error fetching company facts for CIK {cik}: {e}")
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
        print(f"Request timed out: {e}")
        raise

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        raise

    except Exception as e:
        print(f"An error occurred: {e}")
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
        print(f"Timeout error fetching filings for CIK {cik}: {e}")
        raise

    except requests.RequestException as e:
        print(f"Error fetching filings for CIK {cik}: {e}")
        raise

    except Exception as e:
        print(f"Unexpected error fetching filings for CIK {cik}: {e}")
        raise


def get_document_url(cik: str, accession: str, primary_doc: str) -> str:
    """Build the full URL to the filing document on SEC EDGAR."""
    try:
        accession_clean = accession.replace("-", "")
        cik_int = int(cik)
        return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{primary_doc}"
    
    except Exception as e:
        print(f"Error constructing document URL for CIK {cik}, accession {accession}: {e}")
        raise


def fetch_and_parse(url: str) -> str:
    """Fetch an SEC filing HTML page and return clean plain text."""
    try:
        r = requests.get(url, headers={**SEC_HEADERS, "Host": "www.sec.gov"})
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "lxml")
    
    except Exception as e:
        print(f"Error fetching document for URL {url}: {e}")
        raise

    # Remove noise tags
    for tag in soup(["script", "style", "meta", "noscript", "img", "head"]):
        tag.decompose()

    # Strip inline XBRL tags but keep their text content
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
