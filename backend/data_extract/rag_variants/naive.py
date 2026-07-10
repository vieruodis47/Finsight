"""
Naive / vector RAG — the production pipeline, wrapped unchanged (baseline).

Retrieve top-k chunks by dense vector search, generate one grounded answer
with the production system prompt (Lewis et al. 2020 retrieve-then-generate).
This variant reuses rag.py's own functions so it IS the production path,
just instrumented.
"""

from __future__ import annotations

from typing import Optional

from . import common
from .common import VariantResult

CONFIG = {
    "variant": "naive",
    "architecture": "vector",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "production-v1",
    "notes": "wraps rag.search + rag.generate_answer (production path)",
}


def _impl(question: str, k: int, ticker: Optional[str], form: Optional[str], trace: list):
    chunks = common.vector_search(question, k=k, ticker=ticker, form=form)
    trace.append({"step": 1, "action": "vector_search",
                  "query": question, "k": k, "hits": len(chunks)})
    if not chunks:
        trace.append({"step": 2, "action": "no_context"})
        return "", []
    answer = common.generate_grounded(question, chunks)
    trace.append({"step": 2, "action": "generate", "chunks_used": len(chunks)})
    return answer, chunks


def answer(question: str, k: int = 5, ticker: Optional[str] = None,
           form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl, CONFIG, question, k, ticker, form)
