---
description: Build or extend the golden eval set for RAG experiments
argument-hint: [tickers/topics to cover, or "review" to audit the current set]
---

Delegate to the **rag-experiment** agent: build/extend the eval set. Focus: $ARGUMENTS

Rules:
- Schema per `experiments/rag/eval/questions.example.jsonl`: id, question, ticker, form, type (single-hop | multi-hop | aggregation | temporal), expected_facts, expected_sources.
- Ground every expected_fact in an actually-ingested filing (check `/ingest-status`); no invented numbers — verify against the source document.
- Balance question types; multi-hop and aggregation questions are what differentiate architectures, so they must be >= 40% of the set.
- Extending the set = new version file (questions.v<N>.jsonl); never mutate a version an experiment already ran on. Keep a dev split for tuning separate from the held-out report split.
