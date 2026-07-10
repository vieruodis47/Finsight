# RAG Experiments Memory (long-term)

Maintained by the rag-experiment agent. Facts about architectures, eval infrastructure, and durable experiment learnings.

## Verified facts (2026-07-02)

- **The production pipeline is Naive/vector RAG, not GraphRAG.** `embeddings.py`: paragraph-aware chunking (max ~1800 chars, 1-para overlap) -> Gemini embeddings (normalized) -> RavenDB vector search. `rag.py`: `search()` top-k -> single `generate_content` call, `GEMINI_GEN_MODEL ?? gemini-1.5-flash`, temp 0.2, citation-tag system prompt. Team believed this was GraphRAG — corrected 2026-07-02 during harness setup.
- Programmatic entry: `rag.answer_question(question, k=5, ticker=None, form=None) -> (answer, list[FilingChunk])`. FilingChunk carries ticker/form/chunk_index/source/text.
- No `rag_variants/` package exists yet; first experiment must scaffold it (registry + `naive` wrapper around the existing pipeline as baseline).
- Eval substrate lives in `experiments/rag/` (eval sets, judge prompts, raw results). Ledger + leaderboard: `.claude/EXPERIMENTS.md`. Reports: `.claude/evidence/experiments/`.
- Requires live `GEMINI_API_KEY` + RavenDB (`RAVENDB_URLS`/`RAVENDB_DATABASE`) and ingested filings — check `/ingest-status/{ticker}` before running.

## Architecture notes

- naive (baseline): current pipeline, wrapped unchanged.
- graph: to implement — entity/relation extraction at ingest, graph store + community summaries, graph-guided retrieval. Biggest expected edge: multi-hop & aggregation questions. Biggest cost: ingest-time token spend.
- agentic: to implement — LLM loop that decomposes the question, issues multiple searches, decides when to stop. Expected edge: multi-hop; risk: latency/cost blowup.
- modular: to implement — pluggable stages (query rewrite, hybrid retrieval, rerank, compression) over the vector store.

## Learnings

- (add dated entries after each experiment verdict)

## Infra + substrate state (2026-07-09)

- **RavenDB data was lost**: the `finsight_ravendb-data` Docker volume contained only a fresh `System` folder — no FilingChunks/manifests survived. Whatever was ingested before lived elsewhere. Full re-ingest required before any experiment.
- **Port topology on this machine**: host 8080 is held by an AirPlay service. RavenDB (`finsight-ravendb-1`) has no host port binding; a `raven-proxy` socat container now publishes it at `http://127.0.0.1:8081`. Run experiments with `RAVENDB_URLS=http://127.0.0.1:8081` (env files still say 8080 — deliberately untouched).
- **RavenDB node needed one-time `POST /admin/cluster/bootstrap`** (was passive) and `PUT /admin/databases` to create `finsight`.
- **RESOLVED 2026-07-09:** user supplied a working key (new-format `AQ.`-prefixed keys ARE valid — the old one was expired, not malformed). Key lives in both env files now.
- **Variant substrate is live**: `backend/data_extract/rag_variants/` (naive, graph, hyde, agentic, modular + prompt_minimal, prompt_fewshot, ctx_metadata, prompt_quote_first). Shared instrumentation wraps the genai client singleton — token/call/latency metering is identical across variants, including calls inside backend/graph/router.py.
- **Eval v1 shipped**: 16 test + 8 dev questions (AAPL FY23–25, MSFT FY24–25, NVDA FY25–26), every numeric verified via XBRL pipeline AND literal presence in the indexed sections; composition rules pass. Corpus = 6 filings (2 most recent 10-Ks per ticker), ingest via `experiments/rag/ingest_eval_corpus.py`.
- **NVDA quirk**: `RevenueFromContractWithCustomerExcludingAssessedTax` doesn't extract for NVDA (uses a different revenue tag) — NVDA gold facts use net income / R&D / OCF / cost of revenue instead. If someone adds NVDA revenue questions, verify the tag first.
- E-1 (baseline), E-2 (architectures), E-3 (prompt/context axis) pre-registered 2026-07-09 in EXPERIMENTS.md; execution instructions in experiments/rag/RUNBOOK.md.
- **Quota economics (free tier, measured 2026-07-09):** embeddings = 1000 requests/day/model, counted PER TEXT not per batch call. **Daily reset is midnight US-Pacific (07:00 UTC / 02:00 America/Chicago), NOT midnight UTC** — confirmed empirically 2026-07-10T00:53Z when the quota was still exhausted 53 min after UTC midnight — one 10-K ingest burns ~250; retried batches re-burn. Query embeds share the pool. Mitigations that keep the full matrix feasible: query-embedding cache (EMBED_CACHE_PATH), judge on a different model family (`GEMINI_JUDGE_MODEL=gemini-2.5-flash-lite` = separate daily pool), runner purges quota-artifact error records on resume so infra failures never score as variant failures.

## Correction (2026-07-07)

- Generation model is now `gemini-3.1-lite` (team decision; supersedes gemini-1.5-flash above). All experiment variants must use it unless the model itself is the experimental variable.

## Correction (2026-07-09)

- **The real model id is `gemini-3.1-flash-lite`** — `gemini-3.1-lite` does not exist in the Gemini API catalogue (404). Env files fixed 2026-07-09; production /api/chat would have 404'd with the old id once the env override was read.
