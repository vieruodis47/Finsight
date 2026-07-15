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
) -> str:
    """One-to-two sentence description of a single time series.

    values_by_year: {year_or_period_end: value}; None values are ignored.
    unit:           'usd' | 'pct' | 'ratio'
    label:          human metric name, e.g. 'Revenue', 'Net margin'
    subject:        optional ticker/name to lead the sentence
    anomaly_years:  years already de-noised/flagged off-trend (any format)
    allow_cagr:     include a CAGR clause for strictly-positive series over >=2y
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
    return f"{sentence}{extremes}{anomaly_clause} {_ADVICE}"


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
    return (
        f"Projects {label.lower()} at {_fmt(predicted, unit)} for "
        f"{next_label.replace(' (projected)', '')} (95% CI {_fmt(lo, unit)}–"
        f"{_fmt(hi, unit)}), from {_fmt(last_v, unit)} in FY{_fy(last['year'])}"
        f"{move}. The fitted trend is {trend_word} (R²={r_squared:.2f}).{anomaly_clause} "
        f"Statistical estimate from historical filings, not investment advice."
    )
