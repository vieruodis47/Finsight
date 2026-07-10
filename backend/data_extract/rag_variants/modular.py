"""
Modular RAG — a fixed pre-retrieval / retrieval / post-retrieval pipeline
(Gao et al. 2024, "Modular RAG": modules + operators, linear flow pattern).

Operators chosen from the paper's catalogue, one per module:

  Pre-retrieval : query rewrite + sub-query expansion (single LLM call
                  emitting both, to keep the operator cost at 1 call).
  Retrieval     : one vector search per query (original + rewrite + subs).
  Post-retrieval: Reciprocal Rank Fusion across result lists, then LLM
                  listwise rerank of the fused pool down to k.
  Generation    : unchanged production prompt.

Contrast with `agentic`: the flow here is linear and deterministic — no
reflection loop, no conditional routing — isolating the value of classic
pre/post-retrieval operators from the value of agency.
"""

from __future__ import annotations

from typing import Optional

from . import common
from .common import VariantResult

MAX_QUERIES = 4       # original + rewrite + up to 2 sub-queries
FUSED_POOL = 12       # chunks entering the reranker
RRF_K = 60            # standard RRF constant

CONFIG = {
    "variant": "modular",
    "architecture": "rewrite/expand -> multi-search -> RRF -> LLM rerank",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "production-v1 (generation); modular-ops-v1 (rewrite/rerank)",
    "rrf_k": RRF_K,
    "fused_pool": FUSED_POOL,
}

_REWRITE_SYSTEM = (
    "You optimize queries for semantic search over SEC filing text. "
    "Given a question, produce: (1) one clearer rewrite that names the "
    "company, metric, and fiscal period explicitly; (2) up to 2 sub-queries "
    "ONLY if the question genuinely asks for multiple distinct facts "
    "(different metrics, companies, or years) — otherwise an empty list. "
    'Output JSON only: {"rewrite": "...", "subqueries": ["..."]}'
)

_RERANK_SYSTEM = (
    "You rank SEC filing excerpts by how useful they are for answering a "
    "question. Prefer excerpts stating the exact figures/facts asked for, "
    "with the right company and fiscal period. Output JSON only: "
    '{"ranking": [<excerpt numbers, best first>]}'
)


def _rrf_fuse(result_lists) -> list:
    """Reciprocal Rank Fusion; returns chunks sorted by fused score."""
    scores: dict = {}
    first_seen: dict = {}
    for results in result_lists:
        for rank, c in enumerate(results):
            key = (c.ticker, c.form, c.source, c.chunk_index)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
            if key not in first_seen:
                first_seen[key] = c
    ordered = sorted(scores, key=lambda k: scores[k], reverse=True)
    return [first_seen[k] for k in ordered]


def _impl(question: str, k: int, ticker: Optional[str], form: Optional[str], trace: list):
    # Pre-retrieval: rewrite + expansion in one call
    plan = common.llm_json(f"Question: {question}", system=_REWRITE_SYSTEM)
    queries = [question]
    if isinstance(plan, dict):
        rw = (plan.get("rewrite") or "").strip()
        if rw:
            queries.append(rw)
        for sq in (plan.get("subqueries") or [])[:2]:
            if isinstance(sq, str) and sq.strip():
                queries.append(sq.strip())
    queries = queries[:MAX_QUERIES]
    trace.append({"step": 1, "action": "rewrite_expand", "queries": queries})

    # Retrieval: one search per query
    result_lists = []
    for q in queries:
        hits = common.vector_search(q, k=k, ticker=ticker, form=form)
        result_lists.append(hits)
        trace.append({"step": 2, "action": "search", "query": q, "hits": len(hits)})

    fused = _rrf_fuse(result_lists)[:FUSED_POOL]
    trace.append({"step": 3, "action": "rrf_fuse", "pool": len(fused)})
    if not fused:
        return "", []

    # Post-retrieval: LLM listwise rerank down to k
    numbered = "\n\n".join(
        f"({i + 1}) [{c.ticker} {c.form} #{c.chunk_index}] {c.text[:400]}"
        for i, c in enumerate(fused)
    )
    ranking = common.llm_json(
        f"Question: {question}\n\nExcerpts:\n{numbered}",
        system=_RERANK_SYSTEM,
    )
    order = []
    if isinstance(ranking, dict):
        order = [i for i in (ranking.get("ranking") or [])
                 if isinstance(i, int) and 1 <= i <= len(fused)]
    if order:
        seen = set()
        reranked = []
        for i in order:
            if i not in seen:
                seen.add(i)
                reranked.append(fused[i - 1])
        for i, c in enumerate(fused):  # append anything the model dropped
            if (i + 1) not in seen:
                reranked.append(c)
        top = reranked[:k]
    else:
        top = fused[:k]  # rerank failed — keep RRF order
    trace.append({"step": 4, "action": "llm_rerank",
                  "kept": [f"{c.ticker}#{c.chunk_index}" for c in top]})

    answer = common.generate_grounded(question, top)
    trace.append({"step": 5, "action": "generate", "chunks_used": len(top)})
    return answer, top


def answer(question: str, k: int = 5, ticker: Optional[str] = None,
           form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl, CONFIG, question, k, ticker, form)
