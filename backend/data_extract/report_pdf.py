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

Conventions carried into print:
  - green/red ONLY for the directional forecast trend (improving/declining);
    everything else is neutral/brand.
  - series are distinguished by dash pattern + marker, never hue alone, so the
    charts stay legible in greyscale / on paper.

Route (prefix /analysis, already on the Node forwarder allowlist):
  GET /analysis/report/{ticker}  -> application/pdf (attachment)
"""

from __future__ import annotations

import io
import logging
import textwrap
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")  # headless, thread-safe with the object-oriented API below
# Dollar amounts ("$391.0B") appear all over the descriptions and axis labels;
# without this, matplotlib treats "$...$" as LaTeX math mode and raises on the
# text. We use no intentional mathtext (R²/– are Unicode), so turn it off.
matplotlib.rcParams["text.parse_math"] = False
from matplotlib.figure import Figure
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .analysis_charts import trends as _trends_endpoint
from .prediction import prediction as _forecast_endpoint

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])

# --- Theme (mirrors frontend/theme.ts so print matches the UI) --------------
BRAND = "#2563EB"       # sapphire — primary series / brand
BRAND_LIGHT = "#60A5FA"
AMBER = "#D97706"       # seriesB — the second categorical series
POS = "#16A34A"         # green — DIRECTIONAL only (forecast: improving)
NEG = "#DC2626"         # red   — DIRECTIONAL only (forecast: declining)
PEER = "#C3CEDA"        # neutral grey — COGS / non-subject bars
TEXT = "#16202B"
TEXT2 = "#33414F"
MUTED = "#5D6C7C"
FAINT = "#636F7D"
BORDER = "#DDE4EB"
GRIDCOL = "#E8EDF2"
BRAND_TINT = "#EAF1FC"

DISCLAIMER = "Statistical summary of historical filings — not investment advice."


# --- Value formatting (mirrors frontend/utils/format) -----------------------

def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"${v / 1e12:.1f}T"
    if a >= 1e9:
        return f"${v / 1e9:.1f}B"
    if a >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"${v:,.0f}"


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _usd_axis(v, _pos):
    a = abs(v)
    if a >= 1e12:
        return f"${v / 1e12:.0f}T"
    if a >= 1e9:
        return f"${v / 1e9:.0f}B"
    if a >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:,.0f}"


def _pct_axis(v, _pos):
    return f"{v:.0f}%"


# --- Small chart helpers ----------------------------------------------------

def _series(points: list[dict], field: str) -> tuple[list[int], list[float]]:
    """Return (x-indices, values) skipping missing points."""
    xs, ys = [], []
    for i, p in enumerate(points):
        v = p.get(field)
        if v is not None:
            xs.append(i)
            ys.append(float(v))
    return xs, ys


def _style_axes(ax, years: list[str], usd: bool) -> None:
    n = len(years)
    ax.set_xlim(-0.5, n - 0.5)
    # PDF prints at full width, so label EVERY fiscal year that has data — one
    # tick per real data point (`years` is already per-data-year, so a missing
    # filing year is simply absent, never synthesised into a fake tick). Angle
    # the labels 45° (right-anchored) so ~19 of them don't collide; the compact
    # 'YY format keeps them short. Web/mobile keep their responsive thinning —
    # this thinning-removal is the server-rendered PDF path only.
    ax.set_xticks(list(range(n)))
    ax.set_xticklabels(
        [f"'{y[2:]}" for y in years],
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


def _draw_line(ax, points, years, field, usd, color=BRAND):
    xs, ys = _series(points, field)
    ax.plot(xs, ys, color=color, lw=1.8, marker="o", ms=3.0, mfc=color, mec=color)
    _style_axes(ax, years, usd)


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


# --- Page composition -------------------------------------------------------

PAGE_W, PAGE_H = 8.5, 11.0
MARGIN_L = 0.09          # figure-fraction left margin
CONTENT_W = 0.83


def _rule(fig, y: float) -> None:
    from matplotlib.lines import Line2D
    ln = Line2D([MARGIN_L, 0.95], [y, y], color=BORDER, lw=0.6)
    ln.set_transform(fig.transFigure)
    fig.add_artist(ln)


def _footer(fig, page_no: int) -> None:
    _rule(fig, 0.058)
    fig.text(MARGIN_L, 0.038, DISCLAIMER, fontsize=7.5, color=MUTED, style="italic")
    fig.text(0.95, 0.038, f"FinSight · {page_no}", fontsize=7.5, color=FAINT, ha="right")


def _wrap(text: str, width: int = 118) -> str:
    return "\n".join(textwrap.fill(p, width) for p in text.split("\n"))


def _panel(fig, top: float, title: str, draw, description: str) -> None:
    """One chart panel: title, chart axes, and its deterministic description."""
    fig.text(MARGIN_L, top, title, fontsize=11, color=TEXT, fontweight="bold")
    ax = fig.add_axes([MARGIN_L, top - 0.235, CONTENT_W, 0.205])
    draw(ax)
    desc = _wrap(description)
    # Extra clearance below the axis for the angled x labels before the caption.
    fig.text(MARGIN_L, top - 0.263, desc, fontsize=8.3, color=TEXT2, va="top",
             linespacing=1.35)


def build_report(ticker: str) -> bytes:
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
        fig = Figure(figsize=(PAGE_W, PAGE_H))
        fig.patch.set_facecolor("white")
        fig.text(MARGIN_L, 0.93, "Fin", fontsize=22, color=TEXT, fontweight="bold")
        fig.text(MARGIN_L + 0.052, 0.93, "Sight", fontsize=22, color=BRAND, fontweight="bold")
        fig.text(MARGIN_L, 0.90, "Analysis Report", fontsize=13, color=MUTED)
        _rule(fig, 0.885)
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
            fig = Figure(figsize=(PAGE_W, PAGE_H))
            fig.patch.set_facecolor("white")
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
                fig = Figure(figsize=(PAGE_W, PAGE_H))
                fig.patch.set_facecolor("white")
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
            fig = Figure(figsize=(PAGE_W, PAGE_H))
            fig.patch.set_facecolor("white")
            fig.text(MARGIN_L, 0.945, f"{ticker} · Forecast", fontsize=10, color=MUTED)
            _rule(fig, 0.935)
            fig.text(MARGIN_L, 0.88, "Not enough historical filing data to forecast this company.",
                     fontsize=10, color=TEXT2)
            _footer(fig, page)
            pdf.savefig(fig)

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


@router.get("/report/{ticker}")
def report(ticker: str) -> Response:
    try:
        pdf_bytes = build_report(ticker)
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
