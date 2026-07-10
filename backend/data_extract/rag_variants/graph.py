"""
Graph RAG — wraps the existing backend/graph/ layer behind the variant contract.

The repo's graph layer is an XBRL-metric RDF graph + SPARQL with keyword
routing (graph / vector / both), in the spirit of KG-grounded RAG (Xu et al.
2024 customer-service KG-RAG; Edge et al. 2024 GraphRAG motivates the
structured-index idea, though this graph is built from XBRL facts, not
LLM-extracted entities — ingest-time LLM token cost is zero by design).

Notes for scoring: when the router answers purely from the graph, there are
no retrieved text chunks, so chunk-level retrieval metrics (recall@k etc.)
are structurally 0 for that path — the report must attribute this to the
architecture shape, not retrieval failure. The trace records the routing path.
"""

from __future__ import annotations

import threading
from typing import Optional

from . import common
from .common import VariantResult

CONFIG = {
    "variant": "graph",
    "architecture": "xbrl-rdf-graph + vector fallback",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "production-v1 (vector path) / graph-system (graph path)",
    "notes": "wraps backend.graph.router.route_question",
}

_boot_lock = threading.Lock()
_booted = False


def _ensure_graph_loaded() -> None:
    """Rehydrate the in-memory RDF graph from RavenDB once per process."""
    global _booted
    with _boot_lock:
        if _booted:
            return
        from backend.graph.router import rebuild_graph_from_ravendb
        loaded = rebuild_graph_from_ravendb()
        _booted = True
        import logging
        logging.getLogger(__name__).info("graph variant: %d companies loaded", loaded)


def _impl(question: str, k: int, ticker: Optional[str], form: Optional[str], trace: list):
    _ensure_graph_loaded()
    from backend.graph.router import route_question, classify_question

    predicted = classify_question(question)
    trace.append({"step": 1, "action": "classify", "path": predicted})

    answer, chunks, path = route_question(question, k=k, ticker=ticker, form=form)
    trace.append({"step": 2, "action": "route_question", "path_taken": path,
                  "chunks": len(chunks)})
    if path == "none":
        return "", []
    return answer, chunks


def answer(question: str, k: int = 5, ticker: Optional[str] = None,
           form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl, CONFIG, question, k, ticker, form)
