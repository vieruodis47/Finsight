"""Regression tests for the fiscal-year SCOPE of FinChat graph answers.

These lock three closely-related demo bugs that shared one root cause: a
multi-year graph SPARQL deliberately returns the FULL available series (so the
model can compute a year-over-year change), and the chart + citation cards used
to consume that UNSCOPED series. The fix (backend.graph.router) clips rows to
the fiscal-year window the question asks about — via `_asked_year_range` +
`_row_fy` — BEFORE the table, references and chart are built.

Bug 1  citation cards must reference the SAME fiscal years as the claim
Bug 2  the chart x-range must match the asked years (no extra / no forecast year)
Bug 3  chart values must equal the answer-table values (one source of truth)

The clip itself lives inline in `_graph_prompt` (which needs a populated graph +
an LLM, so it isn't unit-friendly); these tests exercise the exact pure helpers
that clip composes, plus the chart/reference builders that consume the result,
using the same expression `_graph_prompt` uses.
"""

import pytest

# The router module imports the graph/embeddings stack (rdflib, numpy, …).
pytest.importorskip("rdflib")
pytest.importorskip("numpy")

from backend.graph import router as R  # noqa: E402


# A full ascending single-company series, exactly the shape a multi-year SPARQL
# returns (ORDER BY ?ticker ?fiscalYear). FY2026 stands in for the "real filed
# but outside the asked window" year from the demo report.
FULL_SERIES = [
    {"ticker": "NVDA", "fiscalYear": str(y), "value": float(v)}
    for y, v in [
        (2021, 10.0), (2022, 20.0), (2023, 30.0),
        (2024, 40.0), (2025, 50.0), (2026, 60.0),
    ]
]


def _clip(question, rows):
    """The exact clip `_graph_prompt` applies (kept in lock-step with it)."""
    yr = R._asked_year_range(question)
    if not yr:
        return rows
    lo, hi = yr
    scoped = [
        r for r in rows
        if R._row_fy(r) is not None
        and lo <= R._row_fy(r) <= (hi if hi is not None else 9999)
    ]
    return scoped or rows  # never clip away everything


class TestAskedYearRange:
    @pytest.mark.parametrize("q,expected", [
        ("operating income from FY2023 to FY2024", (2023, 2024)),   # bounded range
        ("total revenue in 2023 and 2024", (2023, 2024)),           # two named years
        ("operating income in FY2024", (2024, 2024)),               # one specific year
        ("revenue since 2021", (2021, None)),                       # open-ended start
        ("net income trend since 2020", (2020, None)),              # open-ended (trend)
        ("revenue trend", None),                                    # no year -> full series
        ("how did revenue change year over year", None),            # no year -> full series
    ])
    def test_range(self, q, expected):
        assert R._asked_year_range(q) == expected


class TestChartYearRangeNoOverreach:
    """Bug 2 — the chart plots ONLY the asked years; no leading years, and no
    trailing (e.g. FY2026) year rendered as if it were reported data."""

    def test_bounded_range_clips_both_ends(self):
        q = "operating income from FY2023 to FY2024 for NVDA"
        chart = R.build_graph_chart(
            _clip(q, FULL_SERIES), "operating_income_millions", q, requested=["NVDA"]
        )
        assert chart is not None
        assert chart["years"] == ["2023", "2024"]      # no FY2021/FY2022 (lead-in)
        assert "2026" not in chart["years"]            # no FY2026 (outside window)
        assert "2025" not in chart["years"]

    def test_two_point_named_range_is_a_line(self):
        # An explicit from->to change is a 2-point time series (line), not a bar.
        q = "operating income from FY2023 to FY2024 for NVDA"
        chart = R.build_graph_chart(
            _clip(q, FULL_SERIES), "operating_income_millions", q, requested=["NVDA"]
        )
        assert chart["kind"] == "line"
        assert [p["year"] for p in chart["series"][0]["points"]] == ["2023", "2024"]

    def test_single_pinned_year_is_not_overreached(self):
        q = "operating income in FY2024 for NVDA"
        rows = _clip(q, FULL_SERIES)
        assert [r["fiscalYear"] for r in rows] == ["2024"]

    def test_open_ended_since_keeps_only_from_year_onward(self):
        q = "operating income since 2023 for NVDA"
        rows = _clip(q, FULL_SERIES)
        assert [r["fiscalYear"] for r in rows] == ["2023", "2024", "2025", "2026"]


class TestCitationYearsMatchClaim:
    """Bug 1 — citation cards reference the SAME fiscal years as the figure they
    support, not the earliest available year."""

    def test_reference_covers_only_asked_years(self):
        q = "operating income from FY2023 to FY2024 for NVDA"
        refs = R.build_graph_references(
            _clip(q, FULL_SERIES), "operating_income_millions", ["NVDA"]
        )
        assert len(refs) == 1
        ref = refs[0]
        # The card preview (collapsed one-liner) is an asked year, never FY2021.
        assert ref["preview"].startswith("FY2023")
        assert "FY2021" not in ref["text"] and "FY2022" not in ref["text"]
        assert "FY2025" not in ref["text"] and "FY2026" not in ref["text"]
        assert "FY2023" in ref["text"] and "FY2024" in ref["text"]


class TestChartValuesEqualTableValues:
    """Bug 3 — the inline chart is driven by the SAME rows that format the answer
    table, so a chart point can never diverge from the text figure."""

    def test_chart_points_equal_formatted_table_cells(self):
        q = "operating income from FY2023 to FY2024 for NVDA"
        rows = _clip(q, FULL_SERIES)
        metric = "operating_income_millions"
        chart = R.build_graph_chart(rows, metric, q, requested=["NVDA"])
        table = R._format_graph_table(rows, metric)

        points = {p["year"]: p["value"] for p in chart["series"][0]["points"]}
        assert points == {"2023": 30.0, "2024": 40.0}
        # Both figures the chart plots are present verbatim in the answer table.
        assert "$30.0M" in table and "$40.0M" in table
        # And nothing outside the window leaked into either surface.
        assert "$60.0M" not in table  # FY2026
        assert 60.0 not in points.values()
