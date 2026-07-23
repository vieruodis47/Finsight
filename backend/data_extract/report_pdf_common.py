"""
data_extract/report_pdf_common.py

Shared foundation for the server-side, vector, print-ready PDF reports.

Both report builders — the single-company Analysis report (report_pdf.py) and
the two-company Comparison report (report_pdf_compare.py) — compose their PDFs
from THIS one pipeline: same matplotlib vector backend, same theme/typography,
same page geometry, header masthead, footer + disclaimer, and the same
deterministic per-chart caption layout. There is exactly one export path; the
two reports differ only in which panels they place, never in how they are drawn.

Factored out of the original report_pdf.py (which was Analysis-only):
  - theme constants + DISCLAIMER
  - value formatters + axis tick formatters ($, $M, %, ratio)
  - page geometry, _masthead / _rule / _footer / _wrap / _panel
  - single-series helpers (_series, _style_axes, _draw_line)
  - NEW: two-series drawers (_draw_two_series_line / _draw_two_series_bar) for
         anchor-vs-peer comparison charts — distinguishable by hue AND
         dash/marker (or hatch), with a legend naming both companies, and
         explicit gaps where a company lacks data for a year (never a fake 0).
"""

from __future__ import annotations

import textwrap

import numpy as np
import matplotlib

matplotlib.use("Agg")  # headless, thread-safe with the object-oriented API below
# Dollar amounts ("$391.0B") appear all over the descriptions and axis labels;
# without this, matplotlib treats "$...$" as LaTeX math mode and raises on the
# text. We use no intentional mathtext (R²/– are Unicode), so turn it off.
matplotlib.rcParams["text.parse_math"] = False
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

# --- Theme (mirrors frontend/theme.ts so print matches the UI) --------------
BRAND = "#2563EB"       # sapphire — series A / anchor / brand
BRAND_LIGHT = "#60A5FA"
AMBER = "#D97706"       # series B — the second categorical series / peer
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

# Categorical two-company series palette (matches theme.ts series[0]/series[1]).
# Hue is the primary cue; dash pattern (lines) / hatch (bars) + marker shape are
# the redundant non-hue cue so the two series stay distinct in greyscale / print
# and for colour-vision-deficient readers (WCAG 1.4.1). NEVER green/red here —
# those stay reserved for the directional forecast trend only.
SERIES_A = BRAND        # anchor — sapphire
SERIES_A_INK = "#1D4ED8"
SERIES_B = AMBER        # peer — amber
SERIES_B_INK = "#B45309"
SERIES_A_DASH = "-"                 # solid
SERIES_B_DASH = (0, (5, 3))         # dashed
SERIES_A_MARKER = "o"               # circle
SERIES_B_MARKER = "s"               # square
SERIES_B_HATCH = "////"             # bar pattern (bars can't dash)

DISCLAIMER = "Statistical summary of historical filings — not investment advice."


# --- Value formatting (mirrors frontend/utils/format) -----------------------

def _fmt_usd(v: float | None) -> str:
    """Raw dollars → $T/$B/$M/$."""
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


def _fmt_usd_m(v: float | None) -> str:
    """Value already in $millions (compare-metrics layer) → $T/$B/$M."""
    return _fmt_usd(None if v is None else v * 1e6)


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _fmt_ratio(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def _usd_axis(v, _pos):
    a = abs(v)
    if a >= 1e12:
        return f"${v / 1e12:.0f}T"
    if a >= 1e9:
        return f"${v / 1e9:.0f}B"
    if a >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:,.0f}"


def _usd_m_axis(v, _pos):
    """Axis ticks for a series stored in $millions."""
    return _usd_axis(v * 1e6, _pos)


def _pct_axis(v, _pos):
    return f"{v:.0f}%"


def _ratio_axis(v, _pos):
    return f"{v:.1f}"


# unit label (from compare_metrics _SERIES_META / analysis) → (axis fmt, value fmt)
def resolve_unit(unit: str):
    if unit == "usd_m":
        return _usd_m_axis, _fmt_usd_m
    if unit == "pct":
        return _pct_axis, _fmt_pct
    if unit == "ratio":
        return _ratio_axis, _fmt_ratio
    return _usd_axis, _fmt_usd


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


def _style_axes_fmt(ax, years: list[str], axis_fmt) -> None:
    """Common axis styling with an explicit y tick formatter.

    Labels EVERY fiscal year that has data — one tick per real data point
    (`years` is already per-data-year, so a missing filing year is simply
    absent, never synthesised into a fake tick). Labels are angled 45°
    (right-anchored) and compacted to 'YY so ~19 of them don't collide.
    """
    n = len(years)
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_xticks(list(range(n)))
    ax.set_xticklabels(
        [f"'{str(y)[2:4]}" for y in years],
        fontsize=7, color=MUTED, rotation=45, ha="right", rotation_mode="anchor",
    )
    ax.yaxis.set_major_formatter(FuncFormatter(axis_fmt))
    ax.tick_params(axis="y", labelsize=7, colors=MUTED, length=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color=GRIDCOL, lw=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)


def _style_axes(ax, years: list[str], usd: bool) -> None:
    """Back-compat single-company styling (usd flag → $ or % ticks)."""
    _style_axes_fmt(ax, years, _usd_axis if usd else _pct_axis)


def _draw_line(ax, points, years, field, usd, color=BRAND):
    xs, ys = _series(points, field)
    ax.plot(xs, ys, color=color, lw=1.8, marker="o", ms=3.0, mfc=color, mec=color)
    _style_axes(ax, years, usd)


# --- Two-series (anchor vs peer) drawers ------------------------------------
# `points` rows are {year, a, b} exactly as compare_metrics returns them; a/b
# may be None where that company has no filing for the year.

def _two_legend(ax) -> None:
    ax.legend(loc="best", fontsize=7, frameon=False)


def _draw_two_series_line(
    ax, points: list[dict], unit: str, label_a: str, label_b: str,
    ref_lines: tuple[float, ...] = (),
) -> None:
    years = [p["year"] for p in points]
    axis_fmt, _ = resolve_unit(unit)
    xs = list(range(len(points)))
    # None -> np.nan so the LINE BREAKS at a missing year (a gap, never an
    # interpolated/implied value); markers still render at every real point, so
    # an isolated data year shows as a lone marker rather than vanishing.
    ya = [np.nan if p.get("a") is None else float(p["a"]) for p in points]
    yb = [np.nan if p.get("b") is None else float(p["b"]) for p in points]
    for ref in ref_lines:
        # A non-zero reference (e.g. current-ratio = 1.0) is dashed to read as a
        # benchmark; a zero baseline is a solid axis rule.
        ax.axhline(ref, color=BORDER, lw=0.8, ls=(0, (4, 4)) if ref else "-")
    ax.plot(xs, ya, color=SERIES_A, lw=1.8, ls=SERIES_A_DASH,
            marker=SERIES_A_MARKER, ms=3.2, mfc=SERIES_A, mec=SERIES_A, label=label_a)
    ax.plot(xs, yb, color=SERIES_B, lw=1.8, ls=SERIES_B_DASH,
            marker=SERIES_B_MARKER, ms=3.2, mfc=SERIES_B, mec=SERIES_B, label=label_b)
    _style_axes_fmt(ax, years, axis_fmt)
    _two_legend(ax)


def _draw_two_series_bar(
    ax, points: list[dict], unit: str, label_a: str, label_b: str,
    zero_line: bool = False,
) -> None:
    years = [p["year"] for p in points]
    axis_fmt, _ = resolve_unit(unit)
    x = np.arange(len(points))
    w = 0.4
    # A missing value is SKIPPED, never drawn as a 0-height bar — a gap must read
    # as "no data", not "zero". Grouped side-by-side bars (A left, B right).
    xa = [i - w / 2 for i, p in zip(x, points) if p.get("a") is not None]
    va = [float(p["a"]) for p in points if p.get("a") is not None]
    xb = [i + w / 2 for i, p in zip(x, points) if p.get("b") is not None]
    vb = [float(p["b"]) for p in points if p.get("b") is not None]
    if zero_line:
        ax.axhline(0, color=BORDER, lw=0.8)
    ax.bar(xa, va, width=w, color=SERIES_A, label=label_a, zorder=3)
    # Series B carries a hatch so the two bars separate in greyscale (bars can't
    # dash); hatch is drawn in the darker amber ink so it reads on paper.
    ax.bar(xb, vb, width=w, color=SERIES_B, label=label_b, zorder=3,
           hatch=SERIES_B_HATCH, edgecolor=SERIES_B_INK, linewidth=0.0)
    _style_axes_fmt(ax, years, axis_fmt)
    _two_legend(ax)


# --- Page composition -------------------------------------------------------

PAGE_W, PAGE_H = 8.5, 11.0
MARGIN_L = 0.09          # figure-fraction left margin
CONTENT_W = 0.83


def new_figure() -> Figure:
    fig = Figure(figsize=(PAGE_W, PAGE_H))
    fig.patch.set_facecolor("white")
    return fig


def _rule(fig, y: float) -> None:
    ln = Line2D([MARGIN_L, 0.95], [y, y], color=BORDER, lw=0.6)
    ln.set_transform(fig.transFigure)
    fig.add_artist(ln)


def _masthead(fig, subtitle: str) -> None:
    """The 'FinSight' wordmark + report subtitle + hairline, atop a cover page."""
    fig.text(MARGIN_L, 0.93, "Fin", fontsize=22, color=TEXT, fontweight="bold")
    fig.text(MARGIN_L + 0.052, 0.93, "Sight", fontsize=22, color=BRAND, fontweight="bold")
    fig.text(MARGIN_L, 0.90, subtitle, fontsize=13, color=MUTED)
    _rule(fig, 0.885)


def _footer(fig, page_no: int) -> None:
    """Disclaimer + page number on EVERY page."""
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
