"""
data_extract/search.py

Company name/ticker search over the SEC registry (~10 k entries).

GET /search?q=<text>  →  [{name, ticker}, …]  (up to 8 results, ranked)

Ranking tiers (lower = better match):
  0  exact ticker
  1  ticker prefix
  2  name prefix
  3  ticker substring
  4  any word in name starts with q
  5  name substring
"""

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])

_JSON = Path(__file__).parent.parent / "company_name" / "sec_companies.json"


def _load() -> list[dict]:
    if not _JSON.exists():
        return []
    try:
        with _JSON.open(encoding="utf-8") as f:
            return json.load(f).get("companies", [])
    except Exception:
        return []


_COMPANIES = _load()


def _score(name: str, ticker: str, q: str) -> int | None:
    ql, tl, nl = q.lower(), ticker.lower(), name.lower()
    if tl == ql:                                   return 0
    if tl.startswith(ql):                          return 1
    if nl.startswith(ql):                          return 2
    if ql in tl:                                   return 3
    if any(w.startswith(ql) for w in nl.split()): return 4
    if ql in nl:                                   return 5
    return None


@router.get("")
def search(q: str = "", limit: int = 8) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    scored = []
    for company in _COMPANIES:
        ticker = company.get("ticker", "")
        name   = company.get("name", "")
        if not ticker:
            continue
        s = _score(name, ticker, q)
        if s is not None:
            scored.append((s, name, ticker.upper()))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [{"name": r[1].title(), "ticker": r[2]} for r in scored[:limit]]
