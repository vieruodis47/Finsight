# RAG experiments substrate

Run by the `rag-experiment` agent (see `.claude/agents/rag-experiment.md`).
Ledger + leaderboard: `.claude/EXPERIMENTS.md`. Reports: `.claude/evidence/experiments/`.

**Binding documents (the harness enforces these — read before building anything):**

- `METRICS.md` — every metric's definition, the primary metric, slicing & reporting rules. Runners implement these exactly; no improvised metrics.
- `eval/SCHEMA.md` — eval question format, gold-fact verification rules, composition rules.
- `eval/judge_prompts.md` — versioned judge rubrics + blinding protocol + deterministic numeric-matcher spec.

Layout:

- `eval/` — versioned golden question sets (`questions.v1.jsonl` test split, `questions.v1.dev.jsonl` tuning split; see SCHEMA.md; `questions.example.jsonl` shows the format). Never mutate a version after an experiment used it.
- `results/<exp-id>/<variant>.jsonl` — raw per-question-per-repeat run records (append-only).
- `results/<exp-id>/scores/<variant>.jsonl` — scored records (one line per question x repeat, all metrics), produced by the scorer per METRICS.md.
- Variant implementations live in `backend/data_extract/rag_variants/` (one module per architecture, shared interface, `registry.py`). The GraphRAG layer in `backend/graph/` gets wrapped as the `graph` variant behind the same interface.

Raw run record (one JSON line per question x repeat):
{"exp":"E-2","variant":"graph","qid":"q001","repeat":1,"answer":"...","sources":[...],
 "trace":[...],"prompt_tokens":0,"completion_tokens":0,"latency_ms":0,"retrieval_calls":1,
 "config_hash":"...","judge_prompt_version":1,"ts":"ISO8601","error":null}

Scored record adds:
{"correctness":0.83,"per_fact":[...],"recall_at_k":1.0,"precision_at_k":0.6,"mrr":1.0,
 "faithfulness":2,"citation_validity":1.0,"citation_support":0.9,"slice":"multi-hop"}

Ingest cost (per variant, per filing set) goes in `results/<exp-id>/ingest.json`:
{"variant":"graph","filings":12,"wall_clock_s":0,"llm_tokens":0,"storage_mb":0}
