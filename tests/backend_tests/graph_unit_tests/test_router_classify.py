"""Routing-classification regression tests for backend.graph.router.classify_question.

Focus: a risk-factors question must never be routed to the graph-only (SPARQL)
path, because risk factors live in filing prose, not the XBRL metric graph. This
regression guards the narrative-keyword gap where `_NARRATIVE_KW` matched
"risk factor" but not bare "risks"/"risk", so a risk question carrying a metric
word ("...about revenue in FY2024?") fell through to the has_metric→graph
catch-all. The exact phrasing below is advertised on the Help page.
"""

import pytest

# The router module imports the graph/embeddings stack (rdflib, numpy, …).
# Skip cleanly if those optional deps aren't installed in the test env.
pytest.importorskip("rdflib")
pytest.importorskip("numpy")

from backend.graph import router  # noqa: E402

classify = router.classify_question


class TestRiskQuestionsNeverGraphOnly:
    # A metric word alone previously forced these to "graph". They must route to
    # the narrative side (both|vector) so the prose backstop is always in the loop.
    RISK_WITH_METRIC = [
        "What risks did Lululemon flag about revenue in FY2024?",
        "What risks did Apple flag about its net income?",
        "What uncertainties did Apple note about revenue?",
        "What concerns did Apple raise about operating margin?",
    ]

    @pytest.mark.parametrize("q", RISK_WITH_METRIC)
    def test_risk_plus_metric_is_never_graph(self, q):
        assert classify(q) != "graph", f"{q!r} routed to graph (SPARQL has no prose)"

    @pytest.mark.parametrize("q", RISK_WITH_METRIC)
    def test_risk_plus_metric_keeps_prose_backstop(self, q):
        # With a graph-backed metric present, the narrative branch yields `both`
        # (authoritative number + prose); the key invariant is simply "not graph".
        assert classify(q) in ("both", "vector")

    def test_help_page_recommended_phrasing_routes_to_prose(self):
        # Advertised in HelpView.tsx as a recommended question — the router must
        # handle it rather than send it to the metric graph.
        q = "What risks did PVH flag related to inventory in their FY2024 10-K?"
        assert classify(q) in ("both", "vector")

    def test_bare_risk_question_is_narrative(self):
        assert classify("What are Apple's risks around margins?") in ("both", "vector")


class TestExistingRoutingUnchanged:
    """Guardrails so the narrative-keyword widening doesn't over-capture pure
    metric lookups."""

    @pytest.mark.parametrize("q,expected", [
        ("What was Apple's net income in FY2024?", "graph"),
        ("What is Apple's net income?", "graph"),
        ("What were Apple's total revenue and operating income in 2024?", "both"),
        ("What are the main risk factors Apple disclosed?", "vector"),
        ("How much did Apple spend on research and development?", "vector"),
    ])
    def test_route(self, q, expected):
        assert classify(q) == expected
