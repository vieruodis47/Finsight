"""
HyDE — Hypothetical Document Embeddings (Gao et al. 2022, "Precise Zero-Shot
Dense Retrieval without Relevance Labels").

Instead of embedding the question, an LLM writes a hypothetical filing
passage that would answer it; that passage is embedded and used for
retrieval (answer-to-answer similarity). Following the paper, the query
vector is averaged with the hypothetical-document vector to anchor the
search near the original intent. Generation is unchanged production.
"""

from __future__ import annotations

import numpy as np
from typing import Optional

from . import common
from .common import VariantResult

CONFIG = {
    "variant": "hyde",
    "architecture": "hypothetical-document retrieval + vector",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "production-v1 (generation); hyde-v1 (hypothesis)",
    "notes": "1 extra LLM call to draft the hypothetical passage",
}

_HYDE_SYSTEM = (
    "You draft hypothetical SEC filing passages. Given a financial research "
    "question, write a short passage (80-150 words) in the style of a 10-K "
    "filing (MD&A or financial statement notes) that would directly answer "
    "the question. Invent plausible specifics — the text is used only as a "
    "search probe, never shown to users. No preamble, passage text only."
)


def _impl(question: str, k: int, ticker: Optional[str], form: Optional[str], trace: list):
    hypo = common.llm(f"Question: {question}", system=_HYDE_SYSTEM, temperature=0.4)
    trace.append({"step": 1, "action": "hypothetical_document",
                  "chars": len(hypo), "preview": hypo[:160]})
    if not hypo:
        hypo = question  # degenerate fallback: behave like naive

    # Embed the hypothetical passage as a document, the question as a query,
    # then average (the paper's multi-vector trick, adapted to the asymmetric
    # task-type embedding space) and renormalize.
    vecs = common.embed([hypo], task_type="RETRIEVAL_DOCUMENT")
    qvec = common.embed([question], task_type="RETRIEVAL_QUERY")
    avg = np.mean([np.asarray(vecs[0]), np.asarray(qvec[0])], axis=0)
    norm = float(np.linalg.norm(avg))
    fused = (avg / norm).tolist() if norm > 0 else avg.tolist()

    chunks = common.search_by_vector(fused, k=k, ticker=ticker, form=form)
    trace.append({"step": 2, "action": "vector_search_hyde", "k": k,
                  "hits": len(chunks)})
    if not chunks:
        # Fall back to plain query search rather than returning nothing.
        chunks = common.vector_search(question, k=k, ticker=ticker, form=form)
        trace.append({"step": 3, "action": "fallback_plain_search",
                      "hits": len(chunks)})
    if not chunks:
        return "", []
    answer = common.generate_grounded(question, chunks)
    trace.append({"step": 4, "action": "generate", "chunks_used": len(chunks)})
    return answer, chunks


def answer(question: str, k: int = 5, ticker: Optional[str] = None,
           form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl, CONFIG, question, k, ticker, form)
