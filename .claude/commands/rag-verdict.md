---
description: Attribute pending RAG experiments - score results, set verdicts, update leaderboard
---

Delegate to the **rag-experiment** agent, attribution mode:

1. Find every EXPERIMENTS.md entry with verdict `pending`. For each, check `experiments/rag/results/<exp-id>/` for complete raw results (all variants x questions x repeats; missing runs = incomplete, say so).
2. Score per the metrics section of the agent (all metrics, sliced by type). Compare against the pre-registered prediction — the prediction as written, not a post-hoc reinterpretation.
3. Set verdict: supported / refuted / inconclusive, with numbers and confidence (n, variance). Update the leaderboard table.
4. Write/refresh the evidence report in `.claude/evidence/experiments/`, and add durable learnings to `.claude/memory/rag-memory.md`.
