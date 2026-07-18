"""
analysis/descriptions.py

Deterministic, TEMPLATED natural-language descriptions for the Analysis charts.

Every figure in a description is COMPUTED here, in Python, from the exact same
series the chart plots — direction, % change over the window, CAGR where it is
meaningful, latest/min/max values, a least-squares R² as a fit-confidence, and
any years already flagged as off-trend. The sentence is then assembled from a
fixed template using those figures, so the words can never disagree with the
plotted values. No LLM is involved and there is no per-chart API call or quota
cost — this is pure templating (the strongly-preferred path).

Every description is a STATISTICAL SUMMARY OF HISTORICAL SEC FILINGS, not
investment advice. The wording is deliberately non-normative: series "rise",
"fall", or "hold roughly flat" rather than "improve"/"worsen", so the prose
never implies a buy/sell judgement (the green/red directional convention lives
only in the chart marks, never here). Callers render these next to the chart and
attach them as the chart's accessible text (aria-label / aria-describedby).
"""

from __future__ import annotations

from typing import Optional


# ── value formatting (mirrors the frontend fmtUSD / fmtPct / fmtRatio) ────────

def _fmt(value: float, unit: str) -> str:
    """Format one value the way the chart's axis/tooltip does.

    unit: 'usd'   -> raw dollars scaled to $T / $B / $M
          'usd_m' -> value is already in $millions (compare-metrics layer)
          'pct'   -> one-decimal percent
          'ratio' -> two-decimal multiple (e.g. 1.25×)
    """
    if value is None:
        return "—"
    if unit == "usd_m":
        value = value * 1e6
        unit = "usd"
    if unit == "usd":
        a = abs(value)
        if a >= 1e12:
            return f"${value / 1e12:.2f}T"
        if a >= 1e9:
            return f"${value / 1e9:.2f}B"
        if a >= 1e6:
            return f"${value / 1e6:.1f}M"
        return f"${round(value):,}"
    if unit == "ratio":
        return f"{value:.2f}×"
    # pct (default)
    return f"{value:.1f}%"


def _pct_delta(v: float) -> str:
    """Signed percentage with a plus sign for growth (e.g. '+18.4%')."""
    return f"{v:+.1f}%"


# ── lightweight statistics (no scipy dependency; deterministic) ───────────────

def _ols(ys: list[float]) -> tuple[float, float]:
    """Ordinary least-squares slope + R² of ys against x = 0..n-1.

    Returns (slope, r_squared). r_squared is 0.0 when the series is flat or has
    fewer than two points, so callers can treat it as "no meaningful trend".
    """
    n = len(ys)
    if n < 2:
        return 0.0, 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return 0.0, 0.0
    slope = sxy / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    if ss_tot == 0:
        return slope, 0.0
    y_pred = [slope * (x - mx) + my for x in xs]
    ss_res = sum((y - yp) ** 2 for y, yp in zip(ys, y_pred))
    r2 = 1 - ss_res / ss_tot
    return slope, max(0.0, min(1.0, r2))


def _direction(ys: list[float], slope: float) -> str:
    """Neutral trend word from the fitted slope, with a magnitude dead-band.

    'rises' / 'falls' / 'holds roughly flat' — descriptive only, never
    normative, so margins, debt ratios and costs are all phrased the same way.
    """
    if not ys:
        return "holds roughly flat"
    spread = (max(ys) - min(ys))
    # A slope smaller than ~3% of the total spread per step reads as flat.
    if spread == 0 or abs(slope) < 0.03 * spread:
        return "holds roughly flat"
    return "rises" if slope > 0 else "falls"


def _fy(year_key: str) -> str:
    """Fiscal-year label from a year key or period-end date ('2024-06-30'->'2024')."""
    return str(year_key)[:4]


# ── interpretive layer (backward-looking, operational — NOT advisory) ─────────
#
# These add an ANALYTICAL sentence to the statistical restatement: what the
# level/trend of a metric indicates about operations, and how metrics relate.
# The strict discipline (mirrors the rest of the file):
#   * every figure is computed from the same series the chart plots;
#   * the language describes what the FILINGS show (levels, cost structure,
#     operating leverage) — it never opines on the company as an investment
#     (no "well-positioned", "attractive", "should", buy/sell/valuation framing);
#   * trend words stay neutral (rose/fell/widened/narrowed), consistent with the
#     "not investment advice" line the whole module already holds to.


def _metric_kind(label: str) -> str:
    """Infer which metric a series is, from its human label, for interpretation."""
    l = label.lower()
    if "gross margin" in l:
        return "gross_margin"
    if "operating margin" in l:
        return "operating_margin"
    if "net margin" in l or "net income ÷" in l:
        return "net_margin"
    if "cogs" in l or "cost of revenue" in l or ("cost" in l and "share" in l):
        return "cost_share"
    if "net income" in l:
        return "net_income"
    if "revenue" in l:
        return "revenue"
    return "generic"


def _revenue_shape(pairs: list) -> str:
    """Acceleration/deceleration read: compare late-window vs early-window CAGR."""
    ys = [v for _, v in pairs]
    n = len(ys)
    if n < 4 or ys[0] <= 0 or ys[-1] <= 0:
        return ""
    mid = n // 2

    def _cagr(seg: list):
        s = len(seg) - 1
        if s < 1 or seg[0] <= 0 or seg[-1] <= 0:
            return None
        return (seg[-1] / seg[0]) ** (1 / s) - 1

    ce, cl = _cagr(ys[: mid + 1]), _cagr(ys[mid:])
    if ce is None or cl is None:
        return ""
    diff = cl - ce
    if diff > 0.03:
        shape = "accelerated"
        tail = "a quickening pace of top-line expansion"
    elif diff < -0.03:
        shape = "decelerated"
        tail = "a slowing pace of top-line expansion"
    else:
        shape = "was steady"
        tail = "a consistent pace of top-line expansion"
    return (
        f" Growth {shape}: the later years compounded at ≈{cl * 100:.0f}% versus "
        f"≈{ce * 100:.0f}% earlier in the window, indicating {tail}."
    )


# NOTE ON PRECISION: values that appear on the charts (margin levels, pt-moves)
# are formatted at the SAME precision as the statistical line / chart axis (.1f
# for pt-moves) so the prose can never disagree with the plot. Only DERIVED,
# illustrative figures that aren't plotted directly (the $-per-$100 split, the
# cascade gaps) are rounded and hedged with "about"/"roughly".

def _gross_margin_interp(latest: float, pt_move: float) -> str:
    cost = 100 - latest
    if latest >= 50:
        tier = "a level consistent with substantial pricing power or low relative input cost"
    elif latest >= 30:
        tier = "a level consistent with moderate pricing power alongside meaningful direct-cost intensity"
    else:
        tier = "a thin, cost-of-revenue-heavy level where direct product cost consumes most of each sales dollar"
    s = (
        f" At this level roughly ${cost:.0f} of every $100 of revenue goes to the direct cost of "
        f"goods and about ${latest:.0f} remains as gross profit — {tier}."
    )
    if abs(pt_move) >= 2:
        s += (
            f" The {abs(pt_move):.1f}-pt {'widening' if pt_move > 0 else 'narrowing'} points to "
            f"{'easing' if pt_move > 0 else 'rising'} direct-cost intensity or "
            f"{'firmer' if pt_move > 0 else 'softer'} pricing over the window."
        )
    return s


def _operating_margin_interp(latest: float, pt_move: float) -> str:
    s = (
        " Operating margin is what remains after operating expenses such as SG&A, R&D, and "
        "depreciation, before interest and tax."
    )
    if abs(pt_move) >= 2:
        s += (
            f" Its {abs(pt_move):.1f}-pt {'gain' if pt_move > 0 else 'decline'} indicates operating "
            f"costs grew {'slower' if pt_move > 0 else 'faster'} than revenue over the window "
            f"({'operating leverage' if pt_move > 0 else 'operating deleverage'})."
        )
    return s


def _net_margin_interp(latest: float, pt_move: float) -> str:
    s = (
        " Net margin is the share of each revenue dollar kept as profit after all costs, interest, "
        "and tax — the bottom-line conversion of sales into earnings."
    )
    if abs(pt_move) >= 2:
        s += (
            f" The {abs(pt_move):.1f}-pt {'rise' if pt_move > 0 else 'fall'} is the combined result of "
            f"gross-level and below-the-line (operating, interest, tax) cost changes over the window."
        )
    return s


def _cost_share_interp(latest: float, pt_move: float) -> str:
    s = (
        " Cost of revenue is the mirror image of gross margin: what is not spent on the direct cost "
        "of goods is gross profit."
    )
    if abs(pt_move) >= 2:
        s += (
            f" The {abs(pt_move):.1f}-pt {'rise' if pt_move > 0 else 'fall'} shows "
            f"{'increasing' if pt_move > 0 else 'easing'} direct-cost pressure per dollar of revenue."
        )
    return s


def _interpret_series(kind: str, unit: str, pairs: list, vN: float) -> str:
    """One interpretive clause for a single series (empty for generic/unknowns)."""
    if kind == "revenue":
        return _revenue_shape(pairs)
    if kind == "net_income":
        return (
            " Net income is the bottom-line profit after all costs, interest, and tax; measured "
            "against revenue it sets the net margin shown separately."
        )
    if unit != "pct" or not pairs:
        return ""
    v0 = pairs[0][1]
    pt_move = vN - v0
    if kind == "gross_margin":
        return _gross_margin_interp(vN, pt_move)
    if kind == "operating_margin":
        return _operating_margin_interp(vN, pt_move)
    if kind == "net_margin":
        return _net_margin_interp(vN, pt_move)
    if kind == "cost_share":
        return _cost_share_interp(vN, pt_move)
    return ""


# ── public builders ───────────────────────────────────────────────────────────

_ADVICE = "Statistical summary of historical filings, not investment advice."


def describe_series(
    values_by_year: dict,
    unit: str,
    label: str,
    *,
    subject: Optional[str] = None,
    anomaly_years: Optional[list] = None,
    allow_cagr: bool = True,
    interpret: bool = True,
    kind: Optional[str] = None,
) -> str:
    """One-to-two sentence description of a single time series, plus an
    interpretive clause on what the level/trend indicates operationally.

    values_by_year: {year_or_period_end: value}; None values are ignored.
    unit:           'usd' | 'pct' | 'ratio'
    label:          human metric name, e.g. 'Revenue', 'Net margin'
    subject:        optional ticker/name to lead the sentence
    anomaly_years:  years already de-noised/flagged off-trend (any format)
    allow_cagr:     include a CAGR clause for strictly-positive series over >=2y
    interpret:      append the operational interpretation clause (default True)
    kind:           override the inferred metric kind (revenue/gross_margin/…)
    """
    pairs = sorted(
        ((_fy(k), float(v)) for k, v in values_by_year.items() if v is not None),
        key=lambda p: p[0],
    )
    lead = f"{subject} {label.lower()}" if subject else label
    if not pairs:
        return f"No {label.lower()} history is available. {_ADVICE}"
    if len(pairs) == 1:
        (y0, v0) = pairs[0]
        return (
            f"{lead} is {_fmt(v0, unit)} for the only reported year, FY{y0}. "
            f"{_ADVICE}"
        )

    (y0, v0), (yN, vN) = pairs[0], pairs[-1]
    ys = [v for _, v in pairs]
    slope, r2 = _ols(ys)
    verb = _direction(ys, slope)
    span = int(yN) - int(y0)

    # Window change, phrased per unit so it can't be misread:
    #   pct   -> percentage-POINT move (68.4% -> 69.8% is "+1.4 pts", not "+2%")
    #   ratio -> absolute delta in the multiple
    #   usd*  -> relative % change (guarding divide-by-zero / sign flips)
    change_clause = ""
    if unit == "pct":
        change_clause = f", a {(vN - v0):+.1f} pt move"
    elif unit == "ratio":
        change_clause = f", a {(vN - v0):+.2f}× move"
    elif v0 != 0 and (v0 > 0) == (vN > 0):
        change_clause = f", a {_pct_delta((vN - v0) / abs(v0) * 100)} change"

    # CAGR only for strictly-positive USD series spanning >= 2 fiscal years.
    cagr_clause = ""
    if allow_cagr and unit == "usd" and span >= 2 and v0 > 0 and vN > 0:
        cagr = (vN / v0) ** (1 / span) - 1
        cagr_clause = f" (≈{cagr * 100:.1f}% CAGR)"

    # min / max context, only when the extremes aren't the endpoints.
    hi_y, hi_v = max(pairs, key=lambda p: p[1])
    lo_y, lo_v = min(pairs, key=lambda p: p[1])
    extremes = ""
    if hi_y not in (y0, yN) or lo_y not in (y0, yN):
        extremes = (
            f" It peaked at {_fmt(hi_v, unit)} (FY{hi_y}) and bottomed at "
            f"{_fmt(lo_v, unit)} (FY{lo_y})."
        )

    fit = f"; the {span}-year trend is upward" if verb == "rises" else (
        f"; the {span}-year trend is downward" if verb == "falls"
        else f"; over {span} years it is roughly flat"
    )
    fit += f" (R²={r2:.2f})."

    anomaly_clause = ""
    flagged = [_fy(a) for a in (anomaly_years or [])]
    if flagged:
        n = len(flagged)
        anomaly_clause = (
            f" {n} year{'s' if n > 1 else ''} ({', '.join(flagged)}) "
            f"{'were' if n > 1 else 'was'} flagged off-trend and de-noised before fitting."
        )

    sentence = (
        f"{lead} {verb} from {_fmt(v0, unit)} in FY{y0} to {_fmt(vN, unit)} in "
        f"FY{yN}{change_clause}{cagr_clause}{fit}"
    )

    # Interpretive clause: what this level/trend indicates operationally. Derived
    # only from the computed series (vN = latest, v0 = first), never invented.
    interp = ""
    if interpret:
        interp = _interpret_series(kind or _metric_kind(label), unit, pairs, vN)

    return f"{sentence}{extremes}{anomaly_clause}{interp} {_ADVICE}"


def _cascade_divergence(dG: float, dN: float, dO: float) -> str:
    """The core cross-metric read: how gross vs net margin moved together, and
    what that implies about cost structure and operating leverage. All figures
    are computed pt-moves over the window."""
    thr = 1.0  # pts; smaller moves read as "roughly flat"

    def word(d):
        return "roughly flat" if abs(d) < thr else (f"rose {d:.1f} pts" if d > 0 else f"fell {abs(d):.1f} pts")

    if dG <= -thr and dN >= thr:
        return (
            f"Over the window gross margin fell {abs(dG):.1f} pts while net margin rose {dN:.1f} pts — "
            f"direct cost-of-revenue pressure was more than offset lower in the cascade, with operating "
            f"and below-the-line costs growing slower than revenue (operating leverage and scale)."
        )
    if dG >= thr and dN >= thr:
        return (
            f"Gross margin rose {dG:.1f} pts and net margin rose {dN:.1f} pts, so gains at the gross "
            f"level carried through to the bottom line rather than being absorbed by other costs."
        )
    if dG >= thr and dN <= -thr:
        return (
            f"Gross margin rose {dG:.1f} pts but net margin fell {abs(dN):.1f} pts — below-gross costs "
            f"(operating, interest, or tax) grew faster than the gross-level gain over the window."
        )
    if dG <= -thr and dN <= -thr:
        return (
            f"Gross and net margin both fell (gross {word(dG)}, net {word(dN)}), so direct-cost "
            f"pressure flowed through to the bottom line rather than being offset lower in the cascade."
        )
    # Mixed / flat: describe each leg neutrally and note where the change concentrated.
    leg = "operating expenses" if abs(dO) >= abs(dN) else "interest and tax"
    return (
        f"Over the window gross margin {word(dG)}, operating margin {word(dO)}, and net margin "
        f"{word(dN)} — a comparatively stable cost cascade, with what movement there is "
        f"concentrated in {leg}."
    )


def describe_margin_cascade(
    gross_by_year: dict,
    operating_by_year: dict,
    net_by_year: dict,
    revenue_by_year: Optional[dict] = None,
) -> str:
    """Cross-metric synthesis of the margin cascade (gross → operating → net).

    Computes, from the same series the charts plot:
      * the latest cascade and the pt-gaps it implies (operating-expense burden
        = gross−operating; interest+tax burden = operating−net);
      * how gross and net margin moved over the window, and what that divergence
        says about where cost pressure or operating leverage sat.
    Strictly descriptive of the filings — no forward or investment judgement.
    """
    def _series(d: dict) -> list:
        return sorted(
            ((_fy(k), float(v)) for k, v in (d or {}).items() if v is not None),
            key=lambda p: p[0],
        )

    g, o, n = _series(gross_by_year), _series(operating_by_year), _series(net_by_year)
    if not (g and o and n):
        return ""

    yr = g[-1][0]
    G, O, N = g[-1][1], o[-1][1], n[-1][1]
    opex_gap = G - O          # operating-expense burden, pts of revenue
    belowline_gap = O - N     # interest + tax burden, pts of revenue

    def _pt(seg: list) -> float:
        return seg[-1][1] - seg[0][1] if len(seg) >= 2 else 0.0

    dG, dO, dN = _pt(g), _pt(o), _pt(n)

    snapshot = (
        f"The FY{yr} margin cascade runs gross {G:.1f}% → operating {O:.1f}% → net {N:.1f}%: "
        f"operating expenses absorb about {opex_gap:.0f} pts of each revenue dollar and interest "
        f"plus tax a further {max(belowline_gap, 0):.0f} pts."
    )
    divergence = _cascade_divergence(dG, dN, dO)
    return f"{snapshot} {divergence} {_ADVICE}"


def describe_comparison(
    rows: list[dict],
    label: str,
    ta: str,
    tb: str,
    unit: str,
) -> str:
    """Describe a two-company metric comparison, aligned to a common window.

    rows: [{'year': 'YYYY', 'a': value|None, 'b': value|None}, ...]
    Names the latest fiscal year BOTH companies report, states each value and
    the gap, and — critically for the disjoint-window bug — spells out each
    ticker's covered range and any years where one side is missing, so a
    non-overlapping or gappy comparison is never presented as if it were
    like-for-like.
    """
    a_years = [r["year"] for r in rows if r.get("a") is not None]
    b_years = [r["year"] for r in rows if r.get("b") is not None]

    if not a_years and not b_years:
        return f"No {label.lower()} data is reported for {ta} or {tb}. {_ADVICE}"

    a_span = f"FY{a_years[0]}–FY{a_years[-1]}" if a_years else "no reported years"
    b_span = f"FY{b_years[0]}–FY{b_years[-1]}" if b_years else "no reported years"

    common = [r for r in rows if r.get("a") is not None and r.get("b") is not None]
    if not common:
        return (
            f"{ta} ({a_span}) and {tb} ({b_span}) share no fiscal year with "
            f"{label.lower()} reported by both, so no like-for-like comparison "
            f"is possible for this metric. {_ADVICE}"
        )

    latest = common[-1]
    yr, av, bv = latest["year"], float(latest["a"]), float(latest["b"])
    gap_clause = ""
    if unit == "pct":
        diff = av - bv
        who = ta if diff > 0 else tb
        gap_clause = f"{who} leads by {abs(diff):.1f} pts" if diff != 0 else "the two are level"
    elif av != 0 and bv != 0:
        if abs(av) >= abs(bv):
            gap_clause = f"{ta} is {av / bv:.2f}× {tb}" if bv else ""
        else:
            gap_clause = f"{tb} is {bv / av:.2f}× {ta}" if av else ""

    # Note any years inside the common window where a side is missing.
    common_years = [r["year"] for r in common]
    missing = [
        r["year"] for r in rows
        if common_years[0] <= r["year"] <= common_years[-1]
        and (r.get("a") is None or r.get("b") is None)
    ]
    missing_clause = ""
    if missing:
        missing_clause = (
            f" {len(missing)} year(s) in that window are missing for one company "
            f"({', '.join(missing)}) and are shown as gaps."
        )

    tail = f" ({gap_clause})." if gap_clause else "."
    return (
        f"At the latest common year FY{yr}, {ta} {label.lower()} was "
        f"{_fmt(av, unit)} vs {tb} {_fmt(bv, unit)}{tail} "
        f"{ta} covers {a_span}; {tb} covers {b_span}.{missing_clause} {_ADVICE}"
    )


def describe_quarterly(points: list[dict], metric: str, label: str, fy: str) -> str:
    """Describe a single fiscal year's Q1–Q4 breakdown for one metric."""
    vals = [(p["quarter"], p.get(metric)) for p in points if p.get(metric) is not None]
    if not vals:
        return f"No quarterly {label.lower()} is available for FY{fy}. {_ADVICE}"
    total = sum(v for _, v in vals)
    hi_q, hi_v = max(vals, key=lambda p: p[1])
    lo_q, lo_v = min(vals, key=lambda p: p[1])
    share = f" ({hi_v / total * 100:.0f}% of the year)" if total else ""
    return (
        f"FY{fy} {label.lower()} totals {_fmt(total, 'usd')} across "
        f"{len(vals)} reported quarter(s), strongest in {hi_q} at "
        f"{_fmt(hi_v, 'usd')}{share} and weakest in {lo_q} at {_fmt(lo_v, 'usd')}. "
        f"{_ADVICE}"
    )


def describe_distribution(
    points: list[dict], mean: float, std: float, unit: str, label: str
) -> str:
    """Describe the historical spread + anomalies for a distribution chart."""
    vals = [p["value"] for p in points]
    anomalies = [p["year"] for p in points if p.get("is_anomaly")]
    if not vals:
        return f"No {label.lower()} history to summarise. {_ADVICE}"
    latest = points[-1]
    z = (latest["value"] - mean) / std if std else 0.0
    spread = (
        f"averages {_fmt(mean, unit)} with a ±{_fmt(std, unit)} spread"
        if std else f"is essentially constant at {_fmt(mean, unit)}"
    )
    anomaly_clause = (
        f" {len(anomalies)} year(s) ({', '.join(anomalies)}) sit off the fitted "
        f"trend and are flagged." if anomalies else " No years are flagged off-trend."
    )
    return (
        f"Across {len(vals)} fiscal years {label.lower()} {spread}; the latest "
        f"reading (FY{latest['year']}, {_fmt(latest['value'], unit)}) is "
        f"{abs(z):.1f}σ {'above' if z >= 0 else 'below'} the mean.{anomaly_clause} "
        f"{_ADVICE}"
    )


def describe_forecast(
    history: list[dict],
    predicted: float,
    lo: float,
    hi: float,
    next_label: str,
    trend: str,
    r_squared: float,
    unit: str,
    label: str,
    anomaly_years: Optional[list] = None,
) -> str:
    """Describe one metric's forecast: last actual → projection with band + fit."""
    if not history:
        return f"Not enough {label.lower()} history to project. {_ADVICE}"
    last = history[-1]
    last_v = float(last["value"])
    move = ""
    if last_v != 0 and (last_v > 0) == (predicted > 0):
        move = f", a {_pct_delta((predicted - last_v) / abs(last_v) * 100)} step"
    # 'trend' here is the model's directional label; restate it neutrally.
    trend_word = {"improving": "upward", "declining": "downward"}.get(trend, "flat")
    anomaly_clause = ""
    if anomaly_years:
        n = len(anomaly_years)
        anomaly_clause = (
            f" {n} off-trend year(s) were de-noised before fitting."
        )

    # Interpret the fit + band as a statement about how well the HISTORICAL
    # pattern is established — explicitly NOT confidence the company will perform.
    if r_squared >= 0.7:
        fit_note = (
            "The high R² means the past values line up closely with the fitted line, "
            "so the historical pattern is well established"
        )
    elif r_squared >= 0.3:
        fit_note = "The moderate R² means the historical pattern is only loosely consistent"
    else:
        fit_note = (
            "The low R² means the history is noisy and the pattern is weak, so the "
            "projection rests on a loose fit"
        )
    band_note = ""
    if predicted and lo is not None and hi is not None and predicted != 0:
        rel = abs(hi - lo) / abs(predicted)
        if rel >= 0.4:
            band_note = "; the wide 95% band reflects high year-to-year variability in the history"
        elif rel <= 0.15:
            band_note = "; the narrow 95% band reflects a steady history"
    interp = f" {fit_note}{band_note} — a statement about the historical pattern, not a forecast of company performance."

    return (
        f"Projects {label.lower()} at {_fmt(predicted, unit)} for "
        f"{next_label.replace(' (projected)', '')} (95% CI {_fmt(lo, unit)}–"
        f"{_fmt(hi, unit)}), from {_fmt(last_v, unit)} in FY{_fy(last['year'])}"
        f"{move}. The fitted trend is {trend_word} (R²={r_squared:.2f}).{anomaly_clause}{interp} "
        f"Statistical estimate from historical filings, not investment advice."
    )
