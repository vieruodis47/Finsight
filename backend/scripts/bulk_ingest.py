"""
backend/scripts/bulk_ingest.py

Sequential, quota-aware bulk-ingest of SEC filings into RavenDB.

Designed to run unattended overnight and resume across days:
  - Skips filings already in IngestManifests (zero embedding calls, zero quota).
  - Stops cleanly on daily Gemini quota exhaustion (exit 0, not a crash).
  - Per-minute 429 rate limits are retried automatically inside embed_texts().
  - Logs every outcome to both stderr and a timestamped log file.

Invocation (from repo root):
    python -m backend.scripts.bulk_ingest --tickers AAPL,MSFT,NVDA
    python -m backend.scripts.bulk_ingest --file tickers.txt
    python -m backend.scripts.bulk_ingest --from-registry --limit 50
    python -m backend.scripts.bulk_ingest --tickers AAPL,MSFT --dry-run

Or directly:
    python backend/scripts/bulk_ingest.py --tickers AAPL
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — makes the script work regardless of invocation style.
# Adds repo root to sys.path so `from backend.data_extract.*` resolves.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]   # .../repo/backend/scripts/bulk_ingest.py → repo root
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Load .env.python before any project module touches os.getenv.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / "backend" / ".env.python")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Project imports (after path bootstrap so relative package resolution works)
# ---------------------------------------------------------------------------
from backend.data_extract.extractor import run as edgar_run          # EDGAR fetch + parse
from backend.data_extract import embeddings as _emb                  # RavenDB config + ops
from backend.data_extract.embeddings import (
    ingest,
    check_already_indexed,
    DailyQuotaExceededError,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("bulk_ingest")
_LOG_FMT = logging.Formatter(
    "%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _setup_logging(log_path: Path, verbose: bool) -> None:
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(_LOG_FMT)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_LOG_FMT)
    logger.addHandler(fh)

    logger.info("Logging to: %s", log_path.resolve())


# ---------------------------------------------------------------------------
# Ticker loading
# ---------------------------------------------------------------------------

_REGISTRY = _REPO / "backend" / "company_name" / "sec_companies.json"


def _load_registry() -> list[str]:
    if not _REGISTRY.exists():
        raise FileNotFoundError(f"SEC registry not found at {_REGISTRY}")
    data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    companies = data.get("companies", data) if isinstance(data, dict) else data
    return [c["ticker"].upper() for c in companies if c.get("ticker")]


def _load_file(path: Path) -> list[str]:
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip()   # strip inline # comments
        if t:
            tickers.append(t.upper())
    return tickers


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _sections_to_text(sections: dict) -> str:
    """Concatenate all non-header sections with Markdown headings for embedding."""
    parts = []
    for key, text in sections.items():
        if text and key != "header":
            parts.append(f"## {key.replace('_', ' ').title()}\n\n{text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Per-ticker processing
# ---------------------------------------------------------------------------

_OUTCOME = dict  # type alias for readability


def _process_ticker(
    ticker: str,
    form: str,
    delay: float,
    dry_run: bool,
    verbose: bool,
) -> _OUTCOME:
    """
    Full pipeline for one ticker. Returns a dict:
      status: "indexed" | "skipped" | "would_index" | "failed" | "quota_stop"
      chunks: int
      error:  str | None
    """
    extractor_buf = io.StringIO()
    suppress_ctx = (
        contextlib.nullcontext()
        if verbose
        else contextlib.redirect_stdout(extractor_buf)
    )

    # ── 1. EDGAR extract ────────────────────────────────────────────────────
    # run() hits data.sec.gov for CIK, filings list, HTML document, XBRL facts.
    # SEC_HEADERS in sec_client.py sets the required User-Agent automatically.
    try:
        logger.debug("  edgar_run(%s, %s) …", ticker, form)
        with suppress_ctx:
            result = edgar_run(ticker, form)
    except DailyQuotaExceededError as e:
        # Shouldn't originate from the extractor, but guard anyway.
        return {"status": "quota_stop", "chunks": 0, "error": str(e)}
    except Exception as e:
        logger.debug("  Extractor exception:", exc_info=True)
        return {"status": "failed", "chunks": 0, "error": str(e)}

    if verbose and extractor_buf.getvalue().strip():
        logger.debug("  [extractor]\n%s", extractor_buf.getvalue().strip())

    accession    = result.get("accession_number", "")
    source_url   = result.get("source_url", "")
    sections     = result.get("sections", {})
    filing_date  = result.get("filing_date", "")

    # ── 2. Already-indexed check ────────────────────────────────────────────
    # accession is fully resolved from the EDGAR response, so the fast
    # IngestManifests/{TICKER}-{form}-{accession} lookup is always tried first.
    # Source-URL fallback handles pre-manifest ingests.
    try:
        is_indexed, n_existing = check_already_indexed(
            ticker, form, accession, source_url=source_url,
        )
    except Exception as e:
        logger.debug("  check_already_indexed error (will proceed): %s", e)
        is_indexed, n_existing = False, 0

    if is_indexed:
        return {"status": "skipped", "chunks": n_existing, "error": None}

    # ── 3. Dry-run short-circuit ────────────────────────────────────────────
    if dry_run:
        return {"status": "would_index", "chunks": 0, "error": None}

    # ── 4. Build embedding text ─────────────────────────────────────────────
    text = _sections_to_text(sections)
    if not text.strip():
        return {
            "status": "failed", "chunks": 0,
            "error": "No section text extracted from filing",
        }

    # ── 5. Embed + store ────────────────────────────────────────────────────
    # embed_texts() inside ingest() retries per-minute 429s up to 3 times
    # (with ~60s sleeps) automatically. DailyQuotaExceededError propagates up.
    try:
        n = ingest(
            ticker, form, text, source_url,
            accession_number=accession,
            filing_date=filing_date,
        )
    except DailyQuotaExceededError as e:
        return {"status": "quota_stop", "chunks": 0, "error": str(e)}
    except Exception as e:
        logger.debug("  ingest() exception:", exc_info=True)
        return {"status": "failed", "chunks": 0, "error": str(e)}

    # ── 6. Inter-company delay (SEC politeness) ─────────────────────────────
    if delay > 0:
        logger.debug("  Sleeping %.1fs before next ticker…", delay)
        time.sleep(delay)

    return {"status": "indexed", "chunks": n, "error": None}


# ---------------------------------------------------------------------------
# Storage guard + ETA
# ---------------------------------------------------------------------------

def _db_size_bytes() -> int | None:
    """
    Current on-disk size of the target RavenDB database via /stats.
    Returns bytes, or None if the check fails (never blocks ingest on a
    transient stats error — the guard just can't act that iteration).
    """
    try:
        import requests
        base = _emb.RAVENDB_URLS[0].rstrip("/")
        kw = {"timeout": 30}
        if _emb.RAVENDB_CERT_PATH:
            kw["cert"] = _emb.RAVENDB_CERT_PATH
        r = requests.get(f"{base}/databases/{_emb.RAVENDB_DATABASE}/stats", **kw)
        r.raise_for_status()
        return int(r.json()["SizeOnDisk"]["SizeInBytes"])
    except Exception as e:
        logger.debug("DB size check failed (proceeding): %s", e)
        return None


def _fmt_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bulk_ingest",
        description=(
            "Bulk-index SEC filings into RavenDB. "
            "Skips already-indexed tickers (zero quota). "
            "Stops cleanly on daily Gemini quota exhaustion."
        ),
    )

    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--tickers", metavar="A,B,C",
        help="Comma-separated ticker symbols",
    )
    src.add_argument(
        "--file", type=Path, metavar="PATH",
        help="Text file with one ticker per line (# comments ignored)",
    )
    src.add_argument(
        "--from-registry", action="store_true",
        help=f"Load all ~10 k tickers from {_REGISTRY.relative_to(_REPO)}",
    )

    parser.add_argument(
        "--form", default="10-K", choices=["10-K", "10-Q"],
        help="SEC filing form to index (default: 10-K)",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0, metavar="SECS",
        help="Seconds to pause between companies (default: 2.0)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Process at most N tickers (default: unlimited)",
    )
    parser.add_argument(
        "--max-db-gb", type=float, default=9.5, metavar="GB",
        help="HALT before the DB grows past this size, checked each ticker "
             "(free-tier cap is 10GB; default 9.5 leaves headroom for the "
             "in-flight write). Set higher only on a paid tier.",
    )
    parser.add_argument(
        "--log-file", type=Path, metavar="PATH",
        default=Path(f"bulk_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        help="Append-mode log file (default: bulk_ingest_<timestamp>.log)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Check already-indexed status only; no embedding calls",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show extractor [1/5]… output (default: suppressed)",
    )

    args = parser.parse_args()
    _setup_logging(args.log_file, args.verbose)

    # ── Load ticker list ────────────────────────────────────────────────────
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.file:
        tickers = _load_file(args.file)
        logger.info("Loaded %d tickers from %s", len(tickers), args.file)
    else:
        tickers = _load_registry()
        logger.info("Loaded %d tickers from SEC registry", len(tickers))

    if not tickers:
        logger.error("No tickers to process — exiting.")
        sys.exit(1)

    if args.limit:
        tickers = tickers[: args.limit]
        logger.info("Capped to %d tickers (--limit %d)", len(tickers), args.limit)

    total = len(tickers)
    mode_tag = "[DRY RUN] " if args.dry_run else ""
    logger.info(
        "%sStarting bulk ingest — %d tickers, form=%s, delay=%.1fs",
        mode_tag, total, args.form, args.delay,
    )
    logger.info("─" * 60)

    # ── Process ─────────────────────────────────────────────────────────────
    n_indexed  = 0
    n_skipped  = 0
    n_would    = 0
    n_failed   = 0
    failed_list: list[str] = []
    stopped_at: str | None = None
    max_bytes = args.max_db_gb * 1024 ** 3
    t_start = time.time()

    try:
        for idx, ticker in enumerate(tickers, 1):
            prefix = f"[{idx}/{total}] {ticker}"

            # ── Storage guard — HALT before the free-tier cap, not mid-write ──
            if not args.dry_run:
                size = _db_size_bytes()
                if size is not None and size >= max_bytes:
                    logger.warning(
                        "HALT: %s is %.2f GB (>= --max-db-gb %.1f GB). Stopping "
                        "BEFORE the 10GB free-tier cap so no write fails mid-flight. "
                        "Re-run after freeing space or upgrading tier; already-indexed "
                        "tickers skip automatically.",
                        _emb.RAVENDB_DATABASE, size / 1024 ** 3, args.max_db_gb,
                    )
                    stopped_at = ticker
                    break
                if size is not None and idx % 25 == 1:
                    logger.info("   DB size: %.2f GB / cap %.1f GB",
                                size / 1024 ** 3, args.max_db_gb)

            logger.info("%s  →  fetching…", prefix)

            outcome = _process_ticker(ticker, args.form, args.delay, args.dry_run, args.verbose)
            status = outcome["status"]

            if status == "indexed":
                n_indexed += 1
                elapsed = time.time() - t_start
                eta = (total - idx) * (elapsed / idx)
                logger.info(
                    "%s  INDEXED  (%d chunks)  ·  %d/%d done, %d indexed, ETA %s",
                    prefix, outcome["chunks"], idx, total, n_indexed, _fmt_eta(eta),
                )
            elif status == "skipped":
                n_skipped += 1
                logger.info(
                    "%s  SKIPPED  (already indexed, %d chunks, 0 quota used)",
                    prefix, outcome["chunks"],
                )
            elif status == "would_index":
                n_would += 1
                logger.info("%s  WOULD INDEX  (dry run — not embedded)", prefix)
            elif status == "quota_stop":
                stopped_at = ticker
                logger.warning(
                    "%s  QUOTA STOP — daily Gemini embedding quota exhausted",
                    prefix,
                )
                logger.warning("  Detail: %s", outcome["error"])
                logger.warning(
                    "  Re-run tomorrow; already-indexed tickers will be skipped automatically.",
                )
                break
            elif status == "failed":
                n_failed += 1
                failed_list.append(ticker)
                logger.error("%s  FAILED  — %s", prefix, outcome["error"])

    except KeyboardInterrupt:
        logger.info("Interrupted (Ctrl+C) — writing summary…")
        stopped_at = stopped_at or "(interrupted)"

    # ── Summary ──────────────────────────────────────────────────────────────
    logger.info("─" * 60)
    logger.info("SUMMARY%s", " — stopped early" if stopped_at else "")
    if args.dry_run:
        logger.info("  Would index   : %d", n_would)
        logger.info("  Already done  : %d  (already indexed)", n_skipped)
        logger.info("  Failed        : %d  (extractor/EDGAR error)", n_failed)
    else:
        logger.info("  Indexed       : %d", n_indexed)
        logger.info("  Skipped       : %d  (already indexed, 0 quota used)", n_skipped)
        logger.info("  Failed        : %d", n_failed)
    if failed_list:
        logger.info("  Failed list   : %s", ", ".join(failed_list))
    if stopped_at and stopped_at != "(interrupted)":
        logger.info(
            "  Stopped at    : %s  (re-run tomorrow to continue from here)",
            stopped_at,
        )
    elif stopped_at == "(interrupted)":
        logger.info("  Stopped       : keyboard interrupt")
    logger.info("  Log file      : %s", args.log_file.resolve())

    # Always exit 0 — quota stop is a planned stop, not a crash.
    sys.exit(0)


if __name__ == "__main__":
    main()
