"""
The module for Experimentation of Advanced RAG paradigm, including the following architectures:
- HyDE — a pre-retrieval technique: it transforms the query by generating a hypothetical answer before searching.
- REPLUG — retriever-side optimization around a frozen LLM; usually grouped here since it refines retrieval quality without restructuring the pipeline.
- Reranking and compression methods in general (cross-encoder rerankers, context refiners) live here as post-retrieval steps.
"""