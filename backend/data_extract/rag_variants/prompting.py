"""
Prompt- and context-engineering variants over FIXED naive retrieval.

These isolate the prompt/context as the experimental variable (allowed by
METRICS.md rule 2 when registered as such): retrieval is byte-identical to
the `naive` variant — same search call, same k — only the system prompt
and/or the context serialization differ.

Variants:
  prompt_minimal    - bare-bones instruction. Control arm: does the large
                      production prompt actually earn its tokens?
  prompt_fewshot    - production prompt + one worked exemplar demonstrating
                      citation + fiscal-period discipline (classic few-shot
                      prompt engineering).
  ctx_metadata      - context engineering: straight relevance ordering
                      (no bookend reordering) with explicit metadata headers
                      (fiscal period from filing_date, source) and a context
                      manifest listing what was retrieved. Tests the
                      production "_format_context" bookend heuristic against
                      transparent structure.
  prompt_quote_first- suggested technique (ours): two-stage scaffold in one
                      call — extract verbatim evidence quotes per sub-fact
                      first, then compose the answer only from the quotes,
                      stating the fiscal period next to every figure.
                      Prediction: helps temporal/multi-hop correctness and
                      the deterministic numeric matcher (period adjacency).
"""

from __future__ import annotations

from typing import Optional

from . import common
from .common import VariantResult


# --- shared retrieval (identical to naive) -----------------------------------

def _retrieve(question, k, ticker, form, trace):
    chunks = common.vector_search(question, k=k, ticker=ticker, form=form)
    trace.append({"step": 1, "action": "vector_search", "query": question,
                  "k": k, "hits": len(chunks)})
    return chunks


# --- prompt_minimal ------------------------------------------------------------

_MINIMAL_PROMPT = (
    "Answer the question using only the provided SEC filing context. "
    "Cite sources inline with their block tags, e.g. [AAPL 10-K #4]. "
    "If the context is insufficient, say so."
)

CONFIG_MINIMAL = {
    "variant": "prompt_minimal",
    "architecture": "vector (naive retrieval)",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "minimal-v1",
    "registered_variable": "system prompt",
}


def _impl_minimal(question, k, ticker, form, trace):
    chunks = _retrieve(question, k, ticker, form, trace)
    if not chunks:
        return "", []
    ans = common.generate_grounded(question, chunks, system_prompt=_MINIMAL_PROMPT)
    trace.append({"step": 2, "action": "generate", "prompt": "minimal-v1"})
    return ans, chunks


# --- prompt_fewshot -------------------------------------------------------------

_FEWSHOT_SUFFIX = (
    "\n\nWorked example of the expected style:\n"
    "Question: What was Contoso's total revenue in fiscal 2023?\n"
    "Context block: [CTSO 10-K #7 | edgar.example] Total revenue for the "
    "fiscal year ended June 30, 2023 was $52,110 million, an increase of 7% "
    "year-over-year.\n"
    "Answer: Contoso's total revenue was $52.1 billion in fiscal 2023 "
    "[CTSO 10-K #7]. This was a 7% increase over fiscal 2022 [CTSO 10-K #7].\n"
    "Note how every sentence states the fiscal period and carries its "
    "citation tag."
)

CONFIG_FEWSHOT = {
    "variant": "prompt_fewshot",
    "architecture": "vector (naive retrieval)",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "production-v1 + fewshot-v1",
    "registered_variable": "system prompt",
}


def _impl_fewshot(question, k, ticker, form, trace):
    chunks = _retrieve(question, k, ticker, form, trace)
    if not chunks:
        return "", []
    ans = common.generate_grounded(
        question, chunks, system_prompt=common.SYSTEM_PROMPT + _FEWSHOT_SUFFIX
    )
    trace.append({"step": 2, "action": "generate", "prompt": "fewshot-v1"})
    return ans, chunks


# --- ctx_metadata ---------------------------------------------------------------

CONFIG_CTX = {
    "variant": "ctx_metadata",
    "architecture": "vector (naive retrieval)",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "production-v1",
    "registered_variable": "context serialization (ordering + metadata)",
}


def _format_context_metadata(chunks) -> str:
    """Relevance order, explicit metadata headers, and a retrieval manifest."""
    manifest = "\n".join(
        f"- [{c.ticker} {c.form} #{c.chunk_index}] filed {getattr(c, 'filing_date', '') or 'n/a'}"
        for c in chunks
    )
    blocks = []
    for rank, c in enumerate(chunks, start=1):
        header = (
            f"[{c.ticker} {c.form} #{c.chunk_index} | relevance rank {rank} | "
            f"filed {getattr(c, 'filing_date', '') or 'n/a'} | {c.source}]"
        )
        blocks.append(f"{header}\n{c.text}")
    return (
        "Retrieved context manifest (check the filing date against the fiscal "
        "period the question asks about):\n" + manifest + "\n\n---\n\n"
        + "\n\n---\n\n".join(blocks)
    )


def _impl_ctx(question, k, ticker, form, trace):
    chunks = _retrieve(question, k, ticker, form, trace)
    if not chunks:
        return "", []
    ans = common.generate_grounded(
        question, chunks, context_formatter=_format_context_metadata
    )
    trace.append({"step": 2, "action": "generate", "context": "metadata-manifest-v1"})
    return ans, chunks


# --- prompt_quote_first (suggested) ----------------------------------------------

_QUOTE_FIRST_PROMPT = (
    "You are FinSight, an expert financial research assistant.\n"
    "Answer ONLY using the provided context from SEC filings.\n"
    "Work in two stages inside a single response:\n"
    "\n"
    "Stage 1 — EVIDENCE (a section headed 'Evidence:'):\n"
    "List each fact needed to answer the question as a bullet with a verbatim "
    "quote (<=30 words) from the context and its block tag, e.g.:\n"
    '- "Total net sales increased 2% to $391,035 million in 2024" [AAPL 10-K #4]\n'
    "Only quote text that actually appears in the context. If a needed fact "
    "is absent, write '- MISSING: <what is missing>'.\n"
    "\n"
    "Stage 2 — ANSWER (a section headed 'Answer:'):\n"
    "Compose the answer strictly from the Stage 1 quotes. Every sentence "
    "stating a fact or number MUST name the fiscal period it belongs to AND "
    "carry the citation tag of the quote it came from, in the format "
    "[TICKER FORM #N]. Never state a figure whose period you cannot name. "
    "If Stage 1 recorded MISSING facts, state explicitly what could not be "
    "determined from the provided documents.\n"
    "\n"
    "If the context contains conflicting values, present both and say the "
    "context is conflicting; do not pick one."
)

CONFIG_QUOTE = {
    "variant": "prompt_quote_first",
    "architecture": "vector (naive retrieval)",
    "gen_model": common.GEN_MODEL,
    "temperature": common.GEN_TEMPERATURE,
    "prompt": "quote-first-v1 (suggested)",
    "registered_variable": "system prompt",
}


def _impl_quote(question, k, ticker, form, trace):
    chunks = _retrieve(question, k, ticker, form, trace)
    if not chunks:
        return "", []
    ans = common.generate_grounded(question, chunks, system_prompt=_QUOTE_FIRST_PROMPT)
    trace.append({"step": 2, "action": "generate", "prompt": "quote-first-v1"})
    return ans, chunks


# --- contract entry points --------------------------------------------------------

def answer_minimal(question: str, k: int = 5, ticker: Optional[str] = None,
                   form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl_minimal, CONFIG_MINIMAL, question, k, ticker, form)


def answer_fewshot(question: str, k: int = 5, ticker: Optional[str] = None,
                   form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl_fewshot, CONFIG_FEWSHOT, question, k, ticker, form)


def answer_ctx_metadata(question: str, k: int = 5, ticker: Optional[str] = None,
                        form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl_ctx, CONFIG_CTX, question, k, ticker, form)


def answer_quote_first(question: str, k: int = 5, ticker: Optional[str] = None,
                       form: Optional[str] = None) -> VariantResult:
    return common.run_variant(_impl_quote, CONFIG_QUOTE, question, k, ticker, form)
