# RAG Architecture Experiment Ledger

Pre-registration + verdicts for RAG architecture comparisons. Same contract discipline as MANIFEST.md: predictions are written BEFORE running; verdicts are judged against the prediction as written. Negative/inconclusive results stay in the ledger.

## Leaderboard (held-out eval set, updated by /rag-verdict)

| Variant | Eval set | Correctness | Faithfulness | Recall@5 | Multi-hop correctness | Tokens/q | p50 latency | Last exp |
|---|---|---|---|---|---|---|---|---|
| **modular** | v1 | **0.934** | 2.00 | 0.750 | 0.917 | 5,050 | 11.5 s* | E-2 |
| agentic | v1 | 0.927 | 1.79 | 0.813 | 0.917 | 6,827 | 15.4 s* | E-2 |
| naive (baseline) | v1 | 0.917 | 2.00 | 0.813 | 0.917 | 3,791 | 0.9 s | E-2 |
| hyde | v1 | 0.868 | 1.88 | 0.875 | 0.875 | 3,801 | 2.2 s* | E-2 |
| graph | v1 | 0.698 | 2.00 | 0.19 (structural) | 0.292 | **1,620** | **0.8 s** | E-2 |

*Latencies include a 4.5 s/call client-side rate-limit throttle (free tier) multiplied by each variant's LLM-call count — production latencies would be far lower for agentic/modular/hyde. Primary metric (multi-hop+aggregation): modular 0.868 > agentic 0.854 > naive 0.834 > hyde 0.812 > graph 0.396. No variant met its pre-registered gain — see E-2 verdict.*

## Entry format

## E-<n> — <date> — <short title>
- **Hypothesis:** e.g. "GraphRAG beats naive on multi-hop questions"
- **Prediction (falsifiable):** which metrics move, on which slices, by roughly how much; what result counts as refutation
- **Setup:** variants + config hash, eval set version, k, n repeats, gen model, judge model
- **Results:** metric table (all metrics, all slices)
- **Verdict:** pending | supported | refuted | inconclusive — with numbers
- **Report:** .claude/evidence/experiments/E-<n>.md

---

## E-1 — 2026-07-09 — Baseline characterization (naive alone)
- **Hypothesis:** the production naive/vector pipeline handles single-hop lookups well but degrades on the slices that need multiple facts (multi-hop, aggregation, temporal).
- **Prediction (falsifiable):** on `questions.v1.jsonl` (test split), naive scores ≥ 0.70 mean correctness on single-hop; multi-hop and aggregation each land ≥ 0.10 below single-hop; recall@5 ≥ 0.6 overall. Refuted if multi-hop/aggregation are within 0.05 of single-hop (i.e., no headroom for fancier architectures) or single-hop < 0.5 (pipeline broken, comparisons pointless).
- **Setup:** variant `naive` (wraps production rag.py, k=5), eval set v1 test split (16 q), n=3 repeats, gen model `gemini-3.1-flash-lite` temp 0.2, judge `gemma-4-31b-it` temp 0, judge prompts v3 (judge plan revised twice pre-scoring 2026-07-10 — first after a scorer bug sent v2 judge calls to the generation model (scores deleted), then after 2.5-gen models proved closed to new users; final: one gemma judge for all experiments, see eval/judge_prompts.md). Config hash recorded in `results/E-1/run_manifest.json`.
- **Results:** overall correctness 0.917±0.161 | single-hop 1.00 | multi-hop 0.917 | aggregation 0.750 | temporal 1.00 | post-cutoff 0.881 | recall@5 0.813 (aggregation slice: 0.50) | faithfulness 2.0/2 | citation validity 1.00 / support 0.95 | 3,787 tok/q | p50 864 ms | 48/48 runs, 0 errors.
- **Verdict:** **partially supported** — single-hop ≥0.70 ✓ (1.00), recall@5 ≥0.6 ✓ (0.81); aggregation lands 0.25 below single-hop ✓ but multi-hop only 0.083 below (predicted ≥0.10, refutation bound ≤0.05 — between the two). Architecture headroom is concentrated in aggregation, where recall@5=0.50 shows a retrieval-coverage bottleneck.
- **Report:** .claude/evidence/experiments/E-1.md

## E-2 — 2026-07-09 — Architecture comparison: naive vs graph vs hyde vs agentic vs modular
- **Hypothesis:** architectures that decompose or re-structure retrieval (agentic, modular) beat one-shot vector retrieval exactly where retrieval is the bottleneck — multi-hop and aggregation; the XBRL graph path wins temporal/numeric lookups; HyDE moves little on this domain because filing questions are already explicit.
- **Prediction (falsifiable), primary metric = correctness on multi-hop + aggregation slices (test split):**
  - `agentic` ≥ naive + 0.15 on multi-hop; refuted if delta ≤ 0. Cost prediction: ≥ 2× tokens/q and ≥ 2× retrieval calls vs naive.
  - `modular` ≥ naive + 0.10 on multi-hop AND recall@5 ≥ naive + 0.10 overall (multi-query + rerank is a retrieval fix); refuted if both deltas ≤ 0.
  - `graph` ≥ naive + 0.15 on temporal; near-parity (±0.05) on single-hop; recall@5 ≈ 0 on graph-routed questions (structural: no chunks retrieved — documented, not a retrieval failure). Refuted if temporal delta ≤ 0.
  - `hyde` = naive ± 0.05 on all correctness slices (may nudge MRR up); refuted (in the interesting direction) if hyde beats naive by > 0.10 anywhere.
  - Guardrail: any variant whose correctness gain comes with faithfulness drop > 0.3 (0–2 scale) vs naive is gaming the eval — flag in verdict.
- **Setup:** variants `naive,graph,hyde,agentic,modular` — identical gen model (`gemini-3.1-flash-lite`), temp 0.2, production system prompt for final generation; retrieval architecture is the only variable. Eval v1 test split, k=5, n=3 repeats, judge `gemma-4-31b-it` temp 0, judge prompts v3 (see E-1 note), blinded. Agentic bounded ≤5 retrievals/≤4 LLM calls. Ingest cost measured per variant (`results/ingest.json`) — graph's XBRL path costs 0 LLM tokens by design.
- **Results:** overall corr — modular 0.934 | agentic 0.927 | naive 0.917 | hyde 0.868 | graph 0.698. Primary (mh+agg): modular 0.868 | agentic 0.854 | naive 0.834 | hyde 0.812 | graph 0.396. Graph multi-hop collapse 0.292 (router misroute); agentic 1.8x tokens, 3.6 LLM calls, faith 1.79; modular best aggregation 0.819 but recall@5 -0.062. Pairwise: ties dominate (10-13/16). All 48/48 runs, 0 errors.
- **Verdict:** **refuted (as registered)** — agentic multi-hop delta +0.000 (needed +0.15); modular multi-hop +0.000 and recall -0.062 (needed +0.10 both); graph temporal delta 0.000 at ceiling; hyde outside +/-0.05 (worse). Naive baseline held; modular's +0.034 primary-metric gain is the only positive signal, below prediction and within noise. Follow-up candidate (E-4): metrics-scoped graph router to keep graph's 2.3x cost win without the multi-hop collapse.
- **Report:** .claude/evidence/experiments/E-2.md

## E-3 — 2026-07-09 — Prompt/context engineering on fixed naive retrieval
- **Hypothesis:** on this pipeline the generation prompt is a second-order effect for correctness but first-order for citation discipline; a quote-first evidence scaffold (our suggested technique) is the exception and lifts correctness on the fact-dense slices.
- **Prediction (falsifiable), registered variable = system prompt / context serialization (retrieval byte-identical to naive):**
  - `prompt_minimal` (control): correctness within 0.05 of production prompt, but citation validity drops ≥ 0.2 absolute — i.e., the big production prompt earns its tokens on citations, not correctness. Refuted if correctness drops > 0.10 (prompt matters more than predicted) or citations hold (prompt is dead weight).
  - `prompt_fewshot`: citation validity ≥ production + 0.05; correctness ± 0.05 (exemplar helps format, not facts).
  - `ctx_metadata` (context engineering: relevance-order + metadata manifest instead of the production bookend trick): temporal-slice correctness ≥ production + 0.05 (explicit filing dates disambiguate periods); refuted if ≤ 0.
  - `prompt_quote_first` (suggested): multi-hop + temporal correctness ≥ production + 0.10, faithfulness ≥ production, at ≥ 1.3× completion tokens; refuted if correctness delta ≤ 0 or faithfulness drops.
- **Setup:** variants `naive,prompt_minimal,prompt_fewshot,ctx_metadata,prompt_quote_first`; everything except the prompt/context format held fixed (same retrieval call, same k=5, same gen model/temp). Eval v1 test split, n=3, judge `gemma-4-31b-it` temp 0, judge prompts v3 (see E-1 note). Dev split reserved for any prompt tuning — none performed before this registration.
- **Results:** overall corr — fewshot 0.913 | ctx_metadata 0.910 | naive(prod) 0.906 | minimal 0.882 | quote_first 0.865. quote_first multi-hop 0.764 (-0.111 vs prod) at 1.65x completion tokens; citation validity 1.00 in EVERY arm incl. minimal; faithfulness 2.0 everywhere. Pairwise: ties 10-15/16 per pair; quote_first 2W/4L.
- **Verdict:** core hypothesis **supported** (prompts are second-order for correctness: 3 of 4 arms within 0.03 of production), suggested technique **refuted** (quote_first hurt: (mh+temp)/2 delta -0.056, refutation bound was <=0). minimal-prompt prediction refuted in the informative direction: citations held at 1.00 without the big prompt (caveat: tag instruction retained). ctx_metadata/fewshot inconclusive at ceiling. Binding constraint is retrieval coverage, not prompting.
- **Report:** .claude/evidence/experiments/E-3.md
