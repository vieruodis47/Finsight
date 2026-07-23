"""
data_extract/report_pdf_compare.py

Two-company Comparison PDF — the print-ready export for the Analysis "Compare
documents" view (anchor vs peer). Built on the SAME pipeline as the Analysis
report (report_pdf_common): identical theme, typography, page geometry, footer +
disclaimer, and caption layout. This module only adds the comparison-specific
composition; there is no second export path.

Data provenance (why the PDF matches the UI exactly):
  - Charts + per-chart captions are recomputed here via compare_metrics(a, b) —
    the SAME deterministic XBRL read + templated describe_comparison the view
    renders. No LLM, no viewport dependency, so every plotted point and caption
    is identical to the screen.
  - The 'AI-generated analysis' narrative is NOT regenerated at export time
    (that would risk different / hallucinated figures). The exact markdown shown
    on screen is passed in the request body and embedded VERBATIM.

Every comparison chart is exported — independent of which carousel slide happens
to be visible in the browser.
"""

from __future__ import annotations

import io
import textwrap
from datetime import datetime, timezone

from pydantic import BaseModel
from matplotlib.backends.backend_pdf import PdfPages

from .compare_metrics import compare_metrics as _compare_metrics
from .report_pdf_common import (
    TEXT, TEXT2, MUTED, FAINT, SERIES_A_INK, SERIES_B_INK,
    MARGIN_L,
    new_figure, _rule, _masthead, _footer, _wrap, _panel,
    _draw_two_series_line, _draw_two_series_bar,
)


class CompareReportRequest(BaseModel):
    """Body for POST /analysis/compare-report.

    a / b are the two tickers (required). The rest are on-screen context passed
    from the client so the PDF reproduces the view exactly:
      - company_a / company_b : display names (fall back to the ticker)
      - sector_a / sector_b   : GICS sector labels (may be absent)
      - analysis              : the on-screen 'AI-generated analysis' markdown,
                                embedded verbatim (never re-generated here).
    """
    a: str
    b: str
    company_a: str | None = None
    company_b: str | None = None
    sector_a: str | None = None
    sector_b: str | None = None
    analysis: str | None = None


# (series key, panel title, kind, unit, extra) — mirrors the frontend
# CompareCharts carousel exactly, in the same order. `extra` is the y reference
# line(s) for lines, or the zero-baseline flag for bars.
_CHART_SPECS: list[tuple] = [
    ("revenue",              "Revenue",            "bar",  "usd_m", False),
    ("net_income",           "Net Income",         "bar",  "usd_m", True),
    ("gross_margin_pct",     "Gross Margin %",     "line", "pct",   (0.0,)),
    ("operating_margin_pct", "Operating Margin %", "line", "pct",   (0.0,)),
    ("net_margin_pct",       "Net Margin %",       "line", "pct",   (0.0,)),
    ("revenue_growth_pct",   "Revenue Growth %",   "bar",  "pct",   True),
    ("free_cash_flow",       "Free Cash Flow",     "bar",  "usd_m", True),
    ("debt_to_equity",       "Debt-to-Equity",     "line", "ratio", ()),
    ("current_ratio",        "Current Ratio",      "line", "ratio", (1.0,)),
]


def _draw_for(spec: tuple, points: list[dict], ta: str, tb: str):
    """Return a draw(ax) closure for one comparison chart."""
    _key, _title, kind, unit, extra = spec
    if kind == "bar":
        return lambda ax: _draw_two_series_bar(ax, points, unit, ta, tb, zero_line=bool(extra))
    return lambda ax: _draw_two_series_line(ax, points, unit, ta, tb, ref_lines=tuple(extra))


def _coverage(revenue_points: list[dict], side: str) -> str:
    """Fiscal-year coverage string for one company from the revenue series."""
    yrs = [p["year"] for p in revenue_points if p.get(side) is not None]
    if not yrs:
        return "no reported fiscal years"
    if len(yrs) == 1:
        return f"FY{yrs[0]} · 1 fiscal year"
    return f"FY{yrs[0]}–FY{yrs[-1]} · {len(yrs)} fiscal years"


# --- AI-analysis narrative: markdown → flat, single-line render list --------

def _clean_inline(s: str) -> str:
    # matplotlib text can't do inline bold/code spans; strip the markers so the
    # verbatim figures still read cleanly (we never alter numbers, only markup).
    return s.replace("**", "").replace("`", "")


def _narrative_lines(md: str) -> list[tuple[str, str]]:
    """Flatten narrative markdown into (style, text) single lines for paginated
    layout. Body/bullets are pre-wrapped so every entry is exactly one visual
    line (predictable height → correct page breaks)."""
    out: list[tuple[str, str]] = []
    for raw in md.split("\n"):
        s = raw.strip()
        if s == "":
            out.append(("blank", ""))
            continue
        # Markdown table row → monospace; drop |---|--- separator rows.
        if s.startswith("|"):
            body = s.strip("|")
            if set(body.replace("|", "").replace(":", "").replace("-", "").strip()) == set():
                continue
            cells = [_clean_inline(c.strip()) for c in body.split("|")]
            out.append(("mono", "   ".join(cells)))
            continue
        if s.startswith("### "):
            out.append(("heading", _clean_inline(s[4:])))
            continue
        if s.startswith("## "):
            out.append(("heading", _clean_inline(s[3:])))
            continue
        if s.startswith("# "):
            out.append(("heading", _clean_inline(s[2:])))
            continue
        if s.startswith("- ") or s.startswith("* "):
            wrapped = textwrap.wrap(_clean_inline(s[2:]), 104) or [""]
            out.append(("bullet", wrapped[0]))
            out.extend(("bulletcont", w) for w in wrapped[1:])
            continue
        for w in (textwrap.wrap(_clean_inline(s), 110) or [""]):
            out.append(("body", w))
    return out


_LINE_H = {"heading": 0.026, "body": 0.0195, "bullet": 0.0195,
           "bulletcont": 0.0195, "mono": 0.0185, "blank": 0.011}
_NARR_TOP = 0.90
_NARR_BOTTOM = 0.10


def _render_narrative(pdf, header: str, lines: list[tuple[str, str]], page: int) -> int:
    """Lay the narrative out across as many pages as needed; footer on each."""
    state: dict = {"fig": None, "y": _NARR_TOP, "page": page}

    def start():
        state["page"] += 1
        fig = new_figure()
        fig.text(MARGIN_L, 0.945, header, fontsize=10, color=MUTED)
        fig.text(0.95, 0.945, "grounded in your filings · figures match the on-screen analysis",
                 fontsize=8, color=FAINT, ha="right")
        _rule(fig, 0.935)
        state["fig"], state["y"] = fig, _NARR_TOP

    def finish():
        if state["fig"] is not None:
            _footer(state["fig"], state["page"])
            pdf.savefig(state["fig"])

    start()
    for style, text in lines:
        h = _LINE_H[style]
        if state["y"] - h < _NARR_BOTTOM:
            finish()
            start()
        fig, y = state["fig"], state["y"]
        if style == "heading":
            fig.text(MARGIN_L, y - 0.006, text, fontsize=11, color=TEXT, fontweight="bold", va="top")
        elif style in ("bullet", "bulletcont"):
            prefix = "•  " if style == "bullet" else "   "
            fig.text(MARGIN_L + 0.012, y, prefix + text, fontsize=8.6, color=TEXT2, va="top")
        elif style == "mono":
            fig.text(MARGIN_L, y, text, fontsize=7.6, color=TEXT2, va="top", family="monospace")
        elif style != "blank":
            fig.text(MARGIN_L, y, text, fontsize=8.6, color=TEXT2, va="top")
        state["y"] = y - h
    finish()
    return state["page"]


# --- Report -----------------------------------------------------------------

def build_compare_report(req: CompareReportRequest) -> bytes:
    a, b = req.a.upper().strip(), req.b.upper().strip()
    # Deterministic recompute — identical to the on-screen charts + captions.
    data = _compare_metrics(a=a, b=b)  # raises HTTPException(404/502) on bad ticker
    descs: dict = data.get("descriptions", {}) or {}
    name_a = (req.company_a or a).strip()
    name_b = (req.company_b or b).strip()
    generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    revenue = data.get("revenue", [])
    cov_a = _coverage(revenue, "a")
    cov_b = _coverage(revenue, "b")

    buf = io.BytesIO()
    page = 0
    with PdfPages(buf) as pdf:
        # ---- Cover ---------------------------------------------------------
        page += 1
        fig = new_figure()
        _masthead(fig, "Comparison Report")
        fig.text(MARGIN_L, 0.83, f"{a}  vs  {b}", fontsize=34, color=TEXT, fontweight="bold")

        # Two company blocks (name + ticker, sector, fiscal-year coverage, form).
        def _company_block(x_left: bool, ticker: str, name: str, sector: str | None,
                           coverage: str, ink: str) -> None:
            x = MARGIN_L if x_left else 0.52
            fig.text(x, 0.775, f"{name}", fontsize=12, color=ink, fontweight="bold")
            fig.text(x, 0.756, ticker, fontsize=10, color=MUTED)
            fig.text(x, 0.738, f"Sector: {sector}" if sector else "Sector: —", fontsize=9, color=TEXT2)
            fig.text(x, 0.722, coverage, fontsize=9, color=TEXT2)
            fig.text(x, 0.706, "Form 10-K · SEC EDGAR XBRL", fontsize=9, color=FAINT)

        _company_block(True, a, name_a, req.sector_a, cov_a, SERIES_A_INK)
        _company_block(False, b, name_b, req.sector_b, cov_b, SERIES_B_INK)
        fig.text(MARGIN_L, 0.682, f"Generated {generated}", fontsize=9, color=FAINT)
        fig.text(MARGIN_L, 0.664,
                 "Multi-year XBRL comparison aligned to a common fiscal-year axis. "
                 "Captions are statistical descriptions of historical filings.",
                 fontsize=8.6, color=TEXT2, va="top")

        # Cover carries the first comparison chart (Revenue); the rest follow.
        spec0 = _CHART_SPECS[0]
        _panel(fig, 0.60, spec0[1], _draw_for(spec0, data.get(spec0[0], []), a, b),
               descs.get(spec0[0], ""))
        _footer(fig, page)
        pdf.savefig(fig)

        # ---- Every remaining comparison chart (2 per page) ----------------
        rest = _CHART_SPECS[1:]
        for i in range(0, len(rest), 2):
            page += 1
            fig = new_figure()
            fig.text(MARGIN_L, 0.945, f"{a} vs {b} · Comparison charts", fontsize=10, color=MUTED)
            _rule(fig, 0.935)
            tops = [0.86, 0.42]
            for j, spec in enumerate(rest[i:i + 2]):
                _panel(fig, tops[j], spec[1], _draw_for(spec, data.get(spec[0], []), a, b),
                       descs.get(spec[0], ""))
            _footer(fig, page)
            pdf.savefig(fig)

        # ---- AI-generated analysis (verbatim, never re-narrated) ----------
        narrative = (req.analysis or "").strip()
        if narrative:
            lines: list[tuple[str, str]] = [("heading", "AI-generated analysis — grounded in your filings")]
            lines.append(("blank", ""))
            lines.extend(_narrative_lines(narrative))
        else:
            lines = [
                ("heading", "AI-generated analysis"),
                ("blank", ""),
                ("body", "No AI-generated analysis was produced for this comparison. "
                         "Generate it on the Compare view, then export again to include it."),
            ]
        page = _render_narrative(pdf, f"{a} vs {b} · AI-generated analysis", lines, page)

        d = pdf.infodict()
        d["Title"] = f"FinSight Comparison Report — {a} vs {b}"
        d["Author"] = "FinSight"
        d["Subject"] = "Statistical summary of historical SEC filings — not investment advice"

    return buf.getvalue()
