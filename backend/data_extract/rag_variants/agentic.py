"""
Agentic RAG — a bounded single-agent retrieval loop.

Design synthesized from the Agentic RAG survey (planning + reflection
patterns), FLARE (retrieve when the model knows it lacks evidence,
Jiang et al. 2023) and Adaptive-RAG (spend retrieval effort proportional
to question complexity, Jeong et al. 2024):

  1. PLAN    - decompose the question into 1-3 targeted search queries.
  2. RETRIEVE- run each query against the vector store.
  3. REFLECT - the agent inspects gathered evidence and either stops or
               issues one refined follow-up query (max 2 reflection rounds).
  4. ANSWER  - grounded generation over the deduplicated evidence set with
               the production system prompt.

Hard bounds: <= 5 retrieval calls, <= 4 LLM calls per question, evidence
capped at 2k tokens' worth of chunks (top 10) — the survey's noted failure
mode is unbounded cost, so the loop is budgeted by construction.
"""

from __future__ import annotations

from typing import Optional

from . import common
from .common import VariantResult

MAX_SUBQUERIES = 3
MAX_REFLECT_ROUNDS = 2
MAX_EVIDENCE_CHUNKS = 10

CONFIG = {
    "variant": "agentic",
    "architecture": "plan -> retrieve -> reflect loop (bounded)",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "production-v1 (final answer); agentic-planner-v1 (loop)",
    "max_subqueries": MAX_SUBQUERIES,
    "max_reflect_rounds": MAX_REFLECT_ROUNDS,
}

_PLANNER_SYSTEM = (
    "You are the retrieval planner for a financial research assistant that "
    "searches SEC filing text (10-K/10-Q chunks) with semantic search. "
    "Decompose the user's question into the minimal set of search queries "
    "(1-3) that together cover every fact needed. Multi-part or multi-year "
    "questions need one query per distinct fact/period. Each query should "
    "name the company and fiscal year when known. Output JSON only: "
    '{"queries": ["...", "..."]}'
)

_REFLECT_SYSTEM = (
    "You are auditing evidence gathered for a financial question. Decide "
    "whether the evidence contains every fact needed for a complete, "
    "precise answer (right companies, right fiscal periods, right metrics). "
    "If something is missing, produce ONE refined search query targeting "
    "the gap. Output JSON only: "
    '{"sufficient": true|false, "missing": "<what is missing or empty>", '
    '"next_query": "<query or empty>"}'
)


def _evidence_digest(chunks) -> str:
    lines = []
    for c in chunks[:MAX_EVIDENCE_CHUNKS]:
        lines.append(f"[{c.ticker} {c.form} #{c.chunk_index}] {c.text[:300]}")
    return "\n".join(lines)


def _impl(question: str, k: int, ticker: Optional[str], form: Optional[str], trace: list):
    # 1. PLAN
    plan = common.llm_json(f"Question: {question}", system=_PLANNER_SYSTEM)
    queries = []
    if isinstance(plan, dict):
        queries = [q for q in (plan.get("queries") or []) if isinstance(q, str) and q.strip()]
    if not queries:
        queries = [question]
    queries = queries[:MAX_SUBQUERIES]
    trace.append({"step": 1, "action": "plan", "queries": queries})

    # 2. RETRIEVE
    evidence = []
    for q in queries:
        hits = common.vector_search(q, k=k, ticker=ticker, form=form)
        evidence.extend(hits)
        trace.append({"step": 2, "action": "search", "query": q, "hits": len(hits)})
    evidence = common.dedupe_chunks(evidence)

    # 3. REFLECT (bounded)
    for round_i in range(MAX_REFLECT_ROUNDS):
        if not evidence:
            break
        verdict = common.llm_json(
            f"Question: {question}\n\nEvidence gathered:\n{_evidence_digest(evidence)}",
            system=_REFLECT_SYSTEM,
        )
        if not isinstance(verdict, dict):
            break
        trace.append({"step": 3, "action": "reflect", "round": round_i + 1,
                      "sufficient": verdict.get("sufficient"),
                      "missing": (verdict.get("missing") or "")[:160]})
        if verdict.get("sufficient") or not verdict.get("next_query"):
            break
        nq = str(verdict["next_query"]).strip()
        hits = common.vector_search(nq, k=k, ticker=ticker, form=form)
        trace.append({"step": 3, "action": "search_refined", "query": nq,
                      "hits": len(hits)})
        before = len(evidence)
        evidence = common.dedupe_chunks(evidence + hits)
        if len(evidence) == before:
            break  # refinement found nothing new — stop, don't burn budget

    if not evidence:
        return "", []

    evidence = evidence[:MAX_EVIDENCE_CHUNKS]

    # 4. ANSWER
    answer = common.generate_grounded(question, evidence)
    trace.append({"step": 4, "action": "generate", "chunks_used": len(evidence)})
    return answer, evidence


def answer(question: str, k: int = 5, ticker: Optional[str] = None,
           form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl, CONFIG, question, k, ticker, form)
