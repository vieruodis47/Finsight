---
description: Pre-register and run a RAG architecture experiment (delegates to rag-experiment agent)
argument-hint: <hypothesis, e.g. "GraphRAG beats naive on multi-hop questions">
---

Delegate to the **rag-experiment** agent: $ARGUMENTS

Enforce its protocol strictly, in order:
1. Pre-register the hypothesis + falsifiable prediction in `.claude/EXPERIMENTS.md` (new E-<n> entry) BEFORE any implementation or run.
2. Implement/verify the variant(s) in `backend/data_extract/rag_variants/` against the shared contract.
3. Run all variants on the versioned eval set (`experiments/rag/eval/`), n>=3 repeats, raw results to `experiments/rag/results/<exp-id>/`.
4. Score all metrics, sliced by question type. Report to `.claude/evidence/experiments/<exp-id>.md`.
5. Set the verdict in EXPERIMENTS.md and update the leaderboard; record learnings in `.claude/memory/rag-memory.md`.
