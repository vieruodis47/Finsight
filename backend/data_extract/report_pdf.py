"""
data_extract/report_pdf.py

Server-side PDF export for the Analysis view (Option B).

Composes a vector, print-ready PDF from the SAME data + deterministic
descriptions the Analysis page renders:
  - analysis_charts.trends()   -> multi-year revenue / net income / margins +
                                  cost structure + revenue-vs-income, each with a
                                  templated (non-LLM) description.
  - prediction.prediction()    -> denoised forecast per metric: predicted value,
                                  95% CI, R², trend, reliability + description.

Why server-side (vs html2canvas): the Analysis charts live in a carousel, so a
screen capture would depend on which slide is visible; and the descriptions are
deterministically computed here already, so the PDF is reproducible, viewport-
independent, and can never re-narrate/hallucinate. Charts are drawn with
matplotlib's vector PDF backend (crisp in print), text with matplotlib text —
one dependency, no reportlab.

The theme, typography, page geometry, footer/disclaimer and chart primitives are
shared with the two-company Comparison report via report_pdf_common — one export
pipeline, two report shapes. See report_pdf_compare.py for the comparison report.

Conventions carried into print:
  - green/red ONLY for the directional forecast trend (improving/declining);
    everything else is neutral/brand.
  - series are distinguished by dash pattern + marker, never hue alone, so the
    charts stay legible in greyscale / on paper.

Routes (prefix /analysis, already on the Node forwarder allowlist):
  GET  /analysis/report/{ticker}   -> application/pdf (single-company Analysis)
  POST /analysis/compare-report    -> application/pdf (two-company Comparison)
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .analysis_charts import trends as _trends_endpoint
from .analysis_charts import peer_distribution as _peer_dist_endpoint
from .prediction import prediction as _forecast_endpoint

# Shared PDF foundation (theme, formatters, page composition, chart primitives).
from .report_pdf_common import (
    BRAND, BRAND_LIGHT, AMBER, POS, NEG, PEER, TEXT, TEXT2, MUTED, FAINT,
    BORDER, GRIDCOL, BRAND_TINT,
    _fmt_usd, _fmt_pct, _usd_axis, _pct_axis,
    _series, _style_axes, _draw_line,
    PAGE_W, PAGE_H, MARGIN_L, CONTENT_W,
    new_figure, _rule, _masthead, _footer, _wrap, _panel,
)
from .report_pdf_compare import build_compare_report, CompareReportRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


# --- Analysis-specific chart drawers ----------------------------------------

def _draw_rev_vs_income(ax, points, years):
    # Revenue (sapphire, solid, circles) on the left; net income (amber, dashed,
    # squares) on the right. Dash + marker differentiate them without hue alone.
    xr, yr = _series(points, "revenue")
    ax.plot(xr, yr, color=BRAND, lw=1.8, marker="o", ms=3.0, label="Revenue")
    _style_axes(ax, years, usd=True)
    ax2 = ax.twinx()
    xn, yn = _series(points, "net_income")
    ax2.plot(xn, yn, color=AMBER, lw=1.8, ls=(0, (5, 3)), marker="s", ms=3.0, label="Net income")
    ax2.yaxis.set_major_formatter(FuncFormatter(_usd_axis))
    ax2.tick_params(axis="y", labelsize=7, colors=MUTED, length=0)
    for spine in ("top", "left"):
        ax2.spines[spine].set_visible(False)
    ax2.spines["right"].set_color(BORDER)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7, frameon=False)


def _draw_cost_structure(ax, points, years):
    # Stacked bars: COGS (neutral grey, hatched) + gross profit (sapphire).
    # Hatch gives a non-hue cue so the split reads in greyscale.
    x = list(range(len(points)))
    cogs = [p.get("cogs") for p in points]
    gp = [p.get("gross_profit") for p in points]
    cogs0 = [v if v is not None else 0 for v in cogs]
    gp0 = [v if v is not None else 0 for v in gp]
    ax.bar(x, cogs0, color=PEER, edgecolor="#9AA9B8", lw=0.4, hatch="////", label="COGS")
    ax.bar(x, gp0, bottom=cogs0, color=BRAND, label="Gross profit")
    _style_axes(ax, years, usd=True)
    ax.legend(loc="upper left", fontsize=7, frameon=False)


def _draw_forecast(ax, metric: dict):
    usd = metric.get("unit") == "usd"
    hist = metric.get("history") or []
    # history "year" can be a full period-end date ("2007-09-29"); the UI slices
    # it to the fiscal year — mirror that so the axis reads '07, not '07-09-29.
    years = [str(h["year"])[:4] for h in hist]
    vals = [h["value"] for h in hist]
    n = len(hist)
    x = list(range(n))
    ax.plot(x, vals, color=BRAND, lw=1.8, marker="o", ms=3.0, label="Actual")
    pv = metric.get("predicted_value")
    lo = metric.get("confidence_low")
    hi = metric.get("confidence_high")
    labels = list(years)
    if pv is not None:
        px = n  # projected point one step to the right
        # Dashed bridge from last actual to the projection + distinct marker.
        ax.plot([n - 1, px], [vals[-1], pv], color=BRAND_LIGHT, lw=1.8, ls=(0, (4, 3)),
                marker="D", ms=4.0, markevery=[1], label="Projected")
        if lo is not None and hi is not None:
            ax.fill_between([px - 0.25, px + 0.25], [lo, lo], [hi, hi],
                            color=BRAND_LIGHT, alpha=0.18, lw=0, label="95% CI")
        labels.append(str(metric.get("next_label", "Next")).replace(" (projected)", ""))
    total = n + (1 if pv is not None else 0)
    ax.set_xlim(-0.5, total - 0.5)
    # Label every point — all historical years plus the projected column (FY2026);
    # no thinning in the PDF. Rotated 45° so the full-density labels don't collide.
    idx = list(range(total))
    ax.set_xticks(idx)
    ax.set_xticklabels(
        [f"'{labels[i][2:]}" if labels[i][:2] == "20" else labels[i] for i in idx],
        fontsize=7, color=MUTED, rotation=45, ha="right", rotation_mode="anchor",
    )
    ax.yaxis.set_major_formatter(FuncFormatter(_usd_axis if usd else _pct_axis))
    ax.tick_params(axis="y", labelsize=7, colors=MUTED, length=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color=GRIDCOL, lw=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)
    ax.legend(loc="upper left", fontsize=6.5, frameon=False)


# --- Analysis report --------------------------------------------------------

def build_report(ticker: str, peers: list[str] | None = None) -> bytes:
    ticker = ticker.upper()
    data = _trends_endpoint(ticker)          # raises HTTPException on bad ticker
    points = data["points"]
    descs = data["descriptions"]
    years = [p["year"] for p in points]
    coverage = f"FY{years[0]}–FY{years[-1]} · {len(years)} fiscal years · Form 10-K · SEC EDGAR XBRL"

    try:
        forecast = _forecast_endpoint(ticker).get("metrics", [])
    except HTTPException:
        forecast = []

    generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    buf = io.BytesIO()
    page = 0
    with PdfPages(buf) as pdf:
        # ---- Cover ---------------------------------------------------------
        page += 1
        fig = new_figure()
        _masthead(fig, "Analysis Report")
        fig.text(MARGIN_L, 0.83, ticker, fontsize=40, color=TEXT, fontweight="bold")
        fig.text(MARGIN_L, 0.795, coverage, fontsize=10, color=TEXT2)
        fig.text(MARGIN_L, 0.775, f"Generated {generated}", fontsize=9, color=FAINT)
        # Cross-metric synthesis paragraph: what the margin cascade describes.
        synthesis = descs.get("synthesis", "")
        rev_top = 0.71
        if synthesis:
            fig.text(MARGIN_L, 0.745, "What these trends describe", fontsize=11, color=TEXT, fontweight="bold")
            fig.text(MARGIN_L, 0.728, _wrap(synthesis), fontsize=8.6, color=TEXT2, va="top", linespacing=1.4)
            rev_top = 0.60  # push the Revenue chart down to make room
        # Cover carries the Revenue chart; Revenue-vs-Net-income moves to the trend pages.
        _panel(fig, rev_top, "Revenue", lambda ax: _draw_line(ax, points, years, "revenue", True), descs.get("revenue", ""))
        _footer(fig, page)
        pdf.savefig(fig)

        # ---- Trend panels (2 per page) ------------------------------------
        panels = [
            ("Revenue vs Net income", lambda ax: _draw_rev_vs_income(ax, points, years), descs.get("revenue_vs_income", "")),
            ("Net income", lambda ax: _draw_line(ax, points, years, "net_income", True), descs.get("net_income", "")),
            ("Cost structure — COGS + Gross profit", lambda ax: _draw_cost_structure(ax, points, years), descs.get("cost_structure", "")),
            ("Gross margin", lambda ax: _draw_line(ax, points, years, "gross_margin_pct", False), descs.get("gross_margin_pct", "")),
            ("Operating margin", lambda ax: _draw_line(ax, points, years, "operating_margin_pct", False), descs.get("operating_margin_pct", "")),
            ("Net margin", lambda ax: _draw_line(ax, points, years, "net_margin_pct", False), descs.get("net_margin_pct", "")),
        ]
        for i in range(0, len(panels), 2):
            page += 1
            fig = new_figure()
            fig.text(MARGIN_L, 0.945, f"{ticker} · Trends", fontsize=10, color=MUTED)
            _rule(fig, 0.935)
            tops = [0.86, 0.42]
            for j, (title, draw, desc) in enumerate(panels[i:i + 2]):
                _panel(fig, tops[j], title, draw, desc)
            _footer(fig, page)
            pdf.savefig(fig)

        # ---- Forecast ------------------------------------------------------
        if forecast:
            for i in range(0, len(forecast), 2):
                page += 1
                fig = new_figure()
                fig.text(MARGIN_L, 0.945, f"{ticker} · Forecast", fontsize=10, color=MUTED)
                fig.text(0.95, 0.945, "Denoised weighted-linear-trend · 95% CI", fontsize=8, color=FAINT, ha="right")
                _rule(fig, 0.935)
                tops = [0.86, 0.42]
                for j, m in enumerate(forecast[i:i + 2]):
                    _forecast_panel(fig, tops[j], m)
                _footer(fig, page)
                pdf.savefig(fig)
        else:
            page += 1
            fig = new_figure()
            fig.text(MARGIN_L, 0.945, f"{ticker} · Forecast", fontsize=10, color=MUTED)
            _rule(fig, 0.935)
            fig.text(MARGIN_L, 0.88, "Not enough historical filing data to forecast this company.",
                     fontsize=10, color=TEXT2)
            _footer(fig, page)
            pdf.savefig(fig)

        # ---- Loaded-peer distribution -------------------------------------
        # Only when enough peers were passed for a real box (target + ≥2 others).
        # Non-fatal: a peer-fetch hiccup must never sink the whole report.
        if peers:
            try:
                pd = _peer_dist_endpoint(ticker, list(peers))
                sufficient = [m for m in pd.get("metrics", []) if m.get("sufficient")]
                if sufficient:
                    page = _peer_dist_page(pdf, ticker, page, sufficient)
            except HTTPException:
                pass
            except Exception as e:
                logger.warning("peer-distribution page skipped for %s: %s", ticker, e)

        d = pdf.infodict()
        d["Title"] = f"FinSight Analysis Report — {ticker}"
        d["Author"] = "FinSight"
        d["Subject"] = "Statistical summary of historical SEC filings — not investment advice"

    return buf.getvalue()


_TREND_WORD = {"improving": (POS, "Improving"), "declining": (NEG, "Declining"), "stable": (MUTED, "Stable")}
_METRIC_TITLE = {
    "revenue": "Revenue", "gross_margin_pct": "Gross margin",
    "operating_margin_pct": "Operating margin", "net_margin_pct": "Net margin",
}


def _forecast_panel(fig, top: float, m: dict) -> None:
    usd = m.get("unit") == "usd"
    title = _METRIC_TITLE.get(m.get("metric", ""), str(m.get("metric", "Metric")))
    fig.text(MARGIN_L, top, title, fontsize=11, color=TEXT, fontweight="bold")
    # Directional trend chip — the ONE place green/red is allowed.
    tcolor, tword = _TREND_WORD.get(m.get("trend"), (MUTED, "Stable"))
    fig.text(MARGIN_L + 0.20, top, tword, fontsize=9, color=tcolor, fontweight="bold")

    ax = fig.add_axes([MARGIN_L, top - 0.235, CONTENT_W, 0.205])
    _draw_forecast(ax, m)

    pv = _fmt_usd(m.get("predicted_value")) if usd else _fmt_pct(m.get("predicted_value"))
    lo = _fmt_usd(m.get("confidence_low")) if usd else _fmt_pct(m.get("confidence_low"))
    hi = _fmt_usd(m.get("confidence_high")) if usd else _fmt_pct(m.get("confidence_high"))
    r2 = m.get("r_squared")
    rel = str(m.get("reliability", "unknown"))
    stat = (f"{m.get('next_label', 'Next period')}:  {pv}      95% CI  {lo} – {hi}      "
            f"R²  {r2:.2f}      Reliability: {rel}" if isinstance(r2, (int, float))
            else f"{m.get('next_label', 'Next period')}:  {pv}      95% CI  {lo} – {hi}      Reliability: {rel}")
    # Extra clearance below the axis for the angled x labels before the stat line.
    fig.text(MARGIN_L, top - 0.264, stat, fontsize=8.6, color=TEXT, va="top", fontweight="bold")
    desc = m.get("description")
    if desc:
        fig.text(MARGIN_L, top - 0.282, _wrap(desc), fontsize=8.3, color=TEXT2, va="top", linespacing=1.35)


# --- Loaded-peer distribution (box plots) -----------------------------------
# Mirrors the Analysis "Peer distribution" slide: the target vs the other loaded
# companies, real data only. Distribution is NOT directional, so it stays on the
# sapphire/neutral palette (no green/red) — target is a sapphire diamond, peers
# are grey dots. matplotlib has a native box primitive (bxp), used here.

def _peer_axis_fmt(unit: str):
    if unit == "pct":
        return FuncFormatter(_pct_axis)
    return FuncFormatter(lambda v, _pos: f"{v:.1f}×")


def _draw_peer_box(ax, m: dict) -> None:
    stat = {
        "med": m["median"], "q1": m["q1"], "q3": m["q3"],
        "whislo": m["min"], "whishi": m["max"], "fliers": [],
    }
    ax.bxp(
        [stat], vert=False, widths=0.55, showfliers=False, patch_artist=True,
        boxprops=dict(facecolor=BRAND_TINT, edgecolor=BRAND, linewidth=1.1),
        medianprops=dict(color=BRAND, linewidth=1.8),
        whiskerprops=dict(color=MUTED, linewidth=1.0),
        capprops=dict(color=MUTED, linewidth=1.0),
    )
    # Peer dots (grey) then the target (sapphire diamond) on top.
    for cpy in m["companies"]:
        if cpy["is_target"]:
            continue
        ax.plot(cpy["value"], 1, marker="o", ms=4.5, color=PEER,
                mec="white", mew=0.6, zorder=5)
    tgt = next((c for c in m["companies"] if c["is_target"]), None)
    if tgt is not None:
        ax.plot(tgt["value"], 1, marker="D", ms=8, color=BRAND,
                mec="white", mew=1.0, zorder=6)

    ax.set_yticks([])
    ax.xaxis.set_major_formatter(_peer_axis_fmt(m["unit"]))
    ax.tick_params(axis="x", labelsize=7, colors=MUTED, length=0)
    ax.grid(axis="x", color=GRIDCOL, lw=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)


def _peer_box_panel(fig, top: float, m: dict) -> None:
    unit = m["unit"]
    tv = m.get("target_value")
    tv_str = (_fmt_pct(tv) if unit == "pct" else (f"{tv:.2f}×" if tv is not None else "—"))
    fig.text(MARGIN_L, top, m["label"], fontsize=11, color=TEXT, fontweight="bold")
    tgt = next((c for c in m["companies"] if c["is_target"]), None)
    if tgt is not None:
        fig.text(0.95, top, f"{tgt['ticker']}  {tv_str}", fontsize=9, color=BRAND,
                 fontweight="bold", ha="right")
    ax = fig.add_axes([MARGIN_L, top - 0.105, CONTENT_W, 0.072])
    _draw_peer_box(ax, m)
    fig.text(MARGIN_L, top - 0.128, _wrap(m.get("description", "")), fontsize=8.3,
             color=TEXT2, va="top", linespacing=1.35)


def _peer_dist_page(pdf, ticker: str, page: int, metrics: list[dict]) -> int:
    """One page of loaded-peer box plots. Returns the (incremented) page number."""
    page += 1
    fig = new_figure()
    fig.text(MARGIN_L, 0.945, f"{ticker} · Peer distribution", fontsize=10, color=MUTED)
    fig.text(0.95, 0.945, "vs loaded companies · ◆ = this company · real data",
             fontsize=8, color=FAINT, ha="right")
    _rule(fig, 0.935)
    tops = [0.85, 0.56, 0.27]
    for j, m in enumerate(metrics[:3]):
        _peer_box_panel(fig, tops[j], m)
    _footer(fig, page)
    pdf.savefig(fig)
    return page


# --- Routes -----------------------------------------------------------------

@router.get("/report/{ticker}")
def report(ticker: str, peers: list[str] = Query(default=[])) -> Response:
    try:
        pdf_bytes = build_report(ticker, peers=peers)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("PDF report failed for %s", ticker)
        raise HTTPException(status_code=500, detail=f"Could not build the report: {e}")
    fname = f"FinSight_{ticker.upper()}_Analysis.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/compare-report")
def compare_report(req: CompareReportRequest) -> Response:
    """Two-company Comparison PDF.

    POST (not GET) because the on-screen 'AI-generated analysis' narrative is
    carried in the body and embedded VERBATIM — the export must match the UI
    exactly and must never re-run an LLM at export time. Charts + captions are
    recomputed deterministically server-side (compare_metrics), so they are
    identical to what the page rendered.
    """
    try:
        pdf_bytes = build_compare_report(req)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Compare PDF failed for %s vs %s", req.a, req.b)
        raise HTTPException(status_code=500, detail=f"Could not build the comparison: {e}")
    fname = f"FinSight_{req.a.upper()}_vs_{req.b.upper()}_Comparison.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
