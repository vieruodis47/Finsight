# RAG experiments substrate

Run by the `rag-experiment` agent (see `.claude/agents/rag-experiment.md`).
Ledger + leaderboard: `.claude/EXPERIMENTS.md`. Reports: `.claude/evidence/experiments/`.

- `eval/` — versioned golden question sets (`questions.v1.jsonl`, dev split separate) + `judge_prompts.md`. Never mutate a version after an experiment used it.
- `results/<exp-id>/<variant>.jsonl` — raw per-question-per-repeat records (append-only).
- Variant implementations live in `backend/data_extract/rag_variants/` (one module per architecture, shared interface, `registry.py`).

Result record schema (one JSON line per question x repeat):
{"exp":"E-1","variant":"naive","qid":"q001","repeat":1,"answer":"...","sources":[...],
 "trace":[...],"prompt_tokens":0,"completion_tokens":0,"latency_ms":0,
 "config_hash":"...","ts":"ISO8601","error":null}
