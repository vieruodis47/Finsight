# RAG experiment runbook — E-1 / E-2 / E-3

Everything below is staged and smoke-tested; the only missing ingredient is a
working Gemini credential. Pre-registrations live in `.claude/EXPERIMENTS.md`.

## 0. Prerequisites

1. **Gemini credential** — replace `GEMINI_API_KEY` in `backend/.env.python`
   (current value is an invalid `AQ.…` token; a real key starts with `AIza`).
   Get one at https://aistudio.google.com/apikey.
   *Alternative:* `gcloud auth login` + `gcloud auth application-default login`
   and unset `GEMINI_API_KEY` (Vertex mode via `GOOGLE_CLOUD_PROJECT`).
2. **RavenDB** — Docker Desktop running, containers `finsight-ravendb-1` and
   `raven-proxy` up (`docker start finsight-ravendb-1 raven-proxy`).
   RavenDB is reachable at `http://127.0.0.1:8081` (host 8080 is taken by
   AirPlay; the proxy bridges into the compose network). All commands below
   assume `RAVENDB_URLS=http://127.0.0.1:8081` in the environment.
3. Python venv: `.venv` (repo requirements installed).

## 1. Ingest the eval corpus (once)

6 filings — AAPL 10-K FY2024+FY2025, MSFT FY2024+FY2025, NVDA FY2025+FY2026 —
matching every `expected_sources` entry in eval v1:

```
RAVENDB_URLS=http://127.0.0.1:8081 python experiments/rag/ingest_eval_corpus.py \
    --tickers AAPL,MSFT,NVDA --years 2
```

Writes chunk embeddings + IngestManifests + FilingMetrics (graph substrate) and
an ingest-cost report to `experiments/rag/results/ingest.json`. Quota-aware:
stops cleanly on daily embedding quota; re-run to resume (already-indexed
filings are skipped by manifest).

Sanity check afterwards: every ticker/form/period in the eval set must be
indexed (SCHEMA.md rule) — `IngestManifests` should show 6 entries.

## 2. Run the experiments (pre-registered order)

```
# E-1 baseline
RAVENDB_URLS=http://127.0.0.1:8081 python experiments/rag/runner.py --exp E-1 \
    --variants naive --eval experiments/rag/eval/questions.v1.jsonl --repeats 3

# E-2 architectures
RAVENDB_URLS=http://127.0.0.1:8081 python experiments/rag/runner.py --exp E-2 \
    --variants naive,graph,hyde,agentic,modular \
    --eval experiments/rag/eval/questions.v1.jsonl --repeats 3

# E-3 prompt/context axis
RAVENDB_URLS=http://127.0.0.1:8081 python experiments/rag/runner.py --exp E-3 \
    --variants naive,prompt_minimal,prompt_fewshot,ctx_metadata,prompt_quote_first \
    --eval experiments/rag/eval/questions.v1.jsonl --repeats 3
```

Resume-safe: rerunning skips completed (qid, repeat) pairs. Errors/timeouts are
recorded as failed runs (score 0), never excluded. E-2/E-3 can reuse E-1's
naive results only if the config hash matches — otherwise let them re-run.

Budget estimate: 16 questions × 3 repeats × (1 + 5 + 5) variant-runs ≈ 528
generation calls plus ~2× that in judge calls; with `gemini-3.1-lite` this fits
comfortably in a paid tier, but free-tier daily caps will need the runner's
resume support across days.

## 3. Score + aggregate

```
python experiments/rag/scorer.py --exp E-1 --eval experiments/rag/eval/questions.v1.jsonl
python experiments/rag/scorer.py --exp E-2 --eval experiments/rag/eval/questions.v1.jsonl
python experiments/rag/scorer.py --exp E-3 --eval experiments/rag/eval/questions.v1.jsonl
```

Produces `results/<exp>/scores/<variant>.jsonl` + `results/<exp>/summary.json`
(all metrics, all slices, post-cutoff subset). Judge calls are blinded, temp 0,
disk-cached (`judge_cache.jsonl`).

## 4. Verdict + report

Run `/rag-verdict` (or hand the summaries to the rag-experiment agent):
compare against the pre-registered predictions **as written**, close calls
(overall correctness delta < 0.05) get the R4 pairwise protocol
(`Judge.pairwise`, both orders), ~10% of judged scores get a human spot-check,
then write `.claude/evidence/experiments/E-<n>.md`, update the leaderboard and
verdicts in `.claude/EXPERIMENTS.md`, and add learnings to
`.claude/memory/rag-memory.md`.
