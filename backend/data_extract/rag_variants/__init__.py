"""
RAG architecture variants for FinSight experiments.

One module per architecture, all implementing the shared contract defined in
.claude/agents/rag-experiment.md:

    def answer(question: str, k: int = 5, ticker: str | None = None,
               form: str | None = None) -> VariantResult

Variants are registered in registry.py. Shared plumbing (instrumentation,
generation, vector search helpers) lives in common.py. The eval runner in
experiments/rag/ is shared by all variants and never forked per variant.
"""
