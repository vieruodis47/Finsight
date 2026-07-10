"""
Variant registry: name -> answer callable (shared contract, see __init__.py).

Architecture axis (retrieval architecture is the variable, prompt fixed):
  naive, graph, hyde, agentic, modular

Prompt/context axis (naive retrieval fixed, prompt/context is the variable):
  prompt_minimal, prompt_fewshot, ctx_metadata, prompt_quote_first
"""

from __future__ import annotations

from . import naive, graph, hyde, agentic, modular, prompting

REGISTRY = {
    # architecture axis
    "naive": naive.answer,
    "graph": graph.answer,
    "hyde": hyde.answer,
    "agentic": agentic.answer,
    "modular": modular.answer,
    # prompt/context axis (fixed naive retrieval)
    "prompt_minimal": prompting.answer_minimal,
    "prompt_fewshot": prompting.answer_fewshot,
    "ctx_metadata": prompting.answer_ctx_metadata,
    "prompt_quote_first": prompting.answer_quote_first,
}

ARCHITECTURE_VARIANTS = ["naive", "graph", "hyde", "agentic", "modular"]
PROMPT_VARIANTS = ["naive", "prompt_minimal", "prompt_fewshot",
                   "ctx_metadata", "prompt_quote_first"]


def get(name: str):
    if name not in REGISTRY:
        raise KeyError(f"Unknown variant '{name}'. Known: {sorted(REGISTRY)}")
    return REGISTRY[name]
