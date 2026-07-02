"""
The module for Experimentation of Modular RAG, including the following architectures:
- Self-RAG — the canonical example of a loop/adaptive pattern: reflection tokens decide when to retrieve and critique output.
- CRAG — a conditional/branching pattern: the evaluator routes to correct, ambiguous, or incorrect actions (including falling back to web search).
- FLARE — a loop pattern: confidence-triggered retrieval during generation.
- Adaptive-RAG — a routing/conditional pattern: a classifier assesses query complexity and picks the pipeline.
- RAPTOR — a restructured indexing module: the hierarchical summary tree replaces flat chunking.
"""