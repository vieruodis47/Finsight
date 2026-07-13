"""
SEC EDGAR client: all raw network access to SEC APIs and filing documents.

This is the low-level I/O layer. Everything here talks to sec.gov; no module
above this one should call ``requests`` directly.
"""

import json
import logging
import os
import random
import re
import threading
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# --- SEC User-Agent (single source of truth) --------------------------------
# SEC requires a descriptive User-Agent with contact info ("AppName
# contact@email.com") or it returns 403/429. Prefer the SEC_USER_AGENT env var;
# the default is an institutional (.edu) contact, which fares far better than
# the widely-reused "example.com" placeholder that SEC throttles first. Every
# module that talks to sec.gov should import SEC_USER_AGENT / SEC_HEADERS from
# here rather than defining its own literal.
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT", "FinSight (SAIL UW-Madison) rarunachala2@wisc.edu"
)
SEC_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}


class SecRateLimitError(requests.exceptions.HTTPError):
    """
    Raised when SEC EDGAR keeps returning 429/503 after all retries.

    Subclasses requests.exceptions.HTTPError so existing ``except
    requests.RequestException`` handlers still catch it, while the API layer can
    catch this specific type to tell the user "SEC rate-limited us, retry
    shortly" instead of surfacing a generic 502.
    """

# --- SEC fair-access rate limiting ------------------------------------------
# SEC's published limit is 10 requests/second. We self-throttle well under that
# with a global minimum interval between ANY two SEC requests (shared across
# threads), and retry 429/503 with backoff. This is the single knob that keeps
# us "within boundaries" no matter how many extracts run back-to-back.
_SEC_MIN_INTERVAL = float(os.getenv("SEC_MIN_INTERVAL", "0.2"))   # 0.2s => <=5 req/s
_SEC_MAX_RETRIES = int(os.getenv("SEC_MAX_RETRIES", "4"))
_SEC_TIMEOUT = float(os.getenv("SEC_TIMEOUT", "30"))

_sec_lock = threading.Lock()
_last_request_ts = 0.0


def _throttle() -> None:
    """Block until at least _SEC_MIN_INTERVAL has elapsed since the last SEC hit."""
    global _last_request_ts
    with _sec_lock:
        wait = _SEC_MIN_INTERVAL - (time.monotonic() - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _sec_get(url: str, host: str) -> requests.Response:
    """
    Single choke point for every SEC GET: global throttle + 429/503 backoff.

    Honors the server's Retry-After header when present; otherwise uses capped
    exponential backoff. Raises for non-retryable HTTP errors (4xx/5xx) so
    callers keep their existing error handling.
    """
    last_exc = None
    for attempt in range(_SEC_MAX_RETRIES):
        _throttle()
        r = requests.get(
            url, headers={**SEC_HEADERS, "Host": host}, timeout=_SEC_TIMEOUT
        )
        if r.status_code in (429, 503):
            retry_after = (r.headers.get("Retry-After") or "").strip()
            delay = (
                float(retry_after)
                if retry_after.isdigit()
                else min(2 ** attempt, 30)
            )
            logger.warning(
                "SEC %s on %s (attempt %d/%d) — backing off %.1fs",
                r.status_code, url, attempt + 1, _SEC_MAX_RETRIES, delay,
            )
            last_exc = SecRateLimitError(
                f"{r.status_code} Too Many Requests for url: {url}", response=r
            )
            # Jitter so multiple instances sharing one egress IP don't retry in
            # lockstep and re-trip the limit together.
            time.sleep(delay + random.uniform(0, 0.4))
            continue
        r.raise_for_status()
        return r
    # Exhausted retries on 429/503 — surface a typed rate-limit error so the API
    # layer can distinguish "SEC throttled us" from a real upstream 5xx.
    raise last_exc if last_exc is not None else RuntimeError(
        f"SEC request to {url} failed after {_SEC_MAX_RETRIES} attempts"
    )


# --- Local ticker -> CIK registry (avoids hammering company_tickers.json) ----
# The full SEC ticker list is bundled in the repo. Resolving CIK locally means
# a normal ingest makes ZERO calls to www.sec.gov/files/company_tickers.json
# (the ~1MB file that was returning 429). Only tickers newer than the bundled
# snapshot fall through to a single, cached network lookup.
_TICKER_MAP_PATH = (
    Path(__file__).resolve().parents[1] / "company_name" / "sec_companies.json"
)
_ticker_map_lock = threading.Lock()
_local_ticker_map: dict | None = None
_remote_ticker_map: dict | None = None


def _load_local_ticker_map() -> dict:
    """Lazily load and cache the bundled ticker->CIK map. Fails soft to {}."""
    global _local_ticker_map
    if _local_ticker_map is not None:
        return _local_ticker_map
    with _ticker_map_lock:
        if _local_ticker_map is None:
            m: dict = {}
            try:
                data = json.loads(_TICKER_MAP_PATH.read_text())
                for c in data.get("companies", []):
                    t = (c.get("ticker") or "").upper()
                    if t:
                        m[t] = str(c["cik"]).zfill(10)
                logger.info("Loaded %d tickers from local SEC registry", len(m))
            except Exception as e:
                logger.warning("Could not load local ticker map: %s", e)
            _local_ticker_map = m
    return _local_ticker_map


def get_sic(cik: str) -> str | None:
    """Return the 4-digit SIC code from submissions metadata, or None on failure."""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = _sec_get(url, host="data.sec.gov")
        sic = r.json().get("sic")
        return str(sic) if sic else None
    except Exception as e:
        logger.warning("Could not fetch SIC for CIK %s: %s", cik, e)
        return None


def get_company_facts(cik: str) -> dict:
    """All XBRL facts SEC has for a company, in one cached call."""
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        r = _sec_get(url, host="data.sec.gov")
        return r.json()

    except requests.exceptions.Timeout as e:
        logger.error("Timeout fetching company facts for CIK %s: %s", cik, e)
        raise

    except requests.RequestException as e:
        logger.error("Request error fetching company facts for CIK %s: %s", cik, e)
        raise


def get_cik(ticker: str) -> str:
    """
    Look up a company's CIK by ticker.

    Resolves from the bundled local registry first (no network); only tickers
    newer than the bundled snapshot fall through to a single cached fetch of
    company_tickers.json. This keeps normal ingests off the endpoint that was
    returning 429.
    """
    t = ticker.upper()

    local = _load_local_ticker_map()
    if t in local:
        return local[t]

    # Fallback for tickers not in the local snapshot: fetch once, cache, reuse.
    global _remote_ticker_map
    try:
        if _remote_ticker_map is None:
            with _ticker_map_lock:
                if _remote_ticker_map is None:
                    url = "https://www.sec.gov/files/company_tickers.json"
                    data = _sec_get(url, host="www.sec.gov").json()
                    _remote_ticker_map = {
                        entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
                        for entry in data.values()
                    }
                    logger.info(
                        "Cached %d tickers from SEC company_tickers.json",
                        len(_remote_ticker_map),
                    )
        if t in _remote_ticker_map:
            return _remote_ticker_map[t]
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
        r = _sec_get(url, host="data.sec.gov")
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
        r = _sec_get(url, host="www.sec.gov")
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
