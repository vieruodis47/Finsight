# RAG Experiment Metrics — v1 (2026-07-09)

Source of truth for ALL experiment scoring. The rag-experiment agent and any eval runner MUST implement exactly these definitions. Changing a definition = new version of this file + a MANIFEST entry; never silently redefine a metric between experiments.

## Primary metric (the hypothesis lives or dies here)

**Answer correctness on the multi-hop + aggregation slices of the held-out (test) split.**

Every experiment's pre-registration in `.claude/EXPERIMENTS.md` must state, in numbers: the predicted delta on this metric, and the result that counts as refutation (e.g. "graph ≥ +0.15 mean correctness vs naive on multi-hop; refuted if delta ≤ 0"). All other metrics are diagnostic or guardrail.

## Correctness (per question, 0.0–1.0)

Two-tier scoring — deterministic where possible, judged only where necessary:

1. **Numeric facts** (`check: "numeric"` in the eval schema): scored by exact matcher, NO LLM involved.
   - Match = stated value within `tolerance` of gold `value`, unit-aware (handle $391.0B / $391,035 million / 391.0 billion equivalence), AND the fiscal period matches gold. Wrong period = wrong answer, even if the number matches another year.
   - Extract candidate numbers from the answer programmatically; nearest-mention heuristic for association; ambiguous extraction → fall back to judge with the numeric rubric.
2. **Non-numeric facts** (`check: "judged"`): LLM-judge, rubric in `eval/judge_prompts.md`, scored 0 / 1 / 2 → normalized to 0 / 0.5 / 1.

Question score = mean over its `expected_facts`. Slice score = mean over questions, reported with std across the n≥3 repeats. A run that errored/timed out scores 0 for that repeat — never excluded.

**Coverage note (aggregation questions):** correctness on these is inherently coverage — the mean-over-facts scoring already penalizes missing sub-facts. Report the "facts found / facts expected" ratio explicitly for the aggregation slice.

## Retrieval quality (diagnostic — attribute losses to retrieval vs generation)

Against `expected_sources` (gold evidence targets):

- **recall@k** — fraction of gold sources present in the retrieved set (k = the variant's configured k, default 5; for multi-step retrievers, the union of all retrieved chunks, and ALSO report per-step counts).
- **precision@k** — fraction of retrieved chunks that are gold or judged-relevant.
- **MRR** — reciprocal rank of the first gold source.

Matching rule: a retrieved chunk matches a gold source if ticker+form match and the chunk overlaps the gold section/text hint. Record match granularity in the report.

## Faithfulness (guardrail, 0–2 judged)

Every claim in the answer must be supported by the retrieved context shown to the model. Rubric in `eval/judge_prompts.md`. An architecture that raises correctness while faithfulness drops is gaming the eval — flag in the verdict.

## Citation accuracy (guardrail)

Two rates, both required:
- **validity** — fraction of `[TICKER FORM #N]` tags that reference a chunk actually retrieved in that run.
- **support** — fraction of tagged sentences whose cited chunk actually supports the sentence (judged, per-sentence prompt).

## Cost envelope (secondary axis — report ALWAYS, never as an afterthought)

- **Query time:** prompt tokens, completion tokens, total tokens per question; latency p50 and p95 (wall-clock, per question, including retrieval); retrieval/LLM calls per question (agentic variants explode here).
- **Ingest time (per filing, per variant):** wall-clock, LLM tokens spent building the index (GraphRAG entity/relation extraction is the hidden cost — measure it), storage size.

## Contamination control

The eval set flags `post_cutoff: true` questions (answerable only from filings published after the generation model's training cutoff). Report correctness on this subset separately per variant. If a variant scores well overall but collapses on post-cutoff questions, its "knowledge" is parametric, not retrieved — say so in the verdict.

## Slicing & reporting rules (non-negotiable)

1. Every metric reported per slice: single-hop | multi-hop | aggregation | temporal — plus overall. Averages hide exactly what these experiments look for.
2. n ≥ 3 repeats per question per variant; report mean ± std; identical model (`gemini-3.1-lite`), temperature, and system prompt across variants unless that is the registered variable.
3. Dev split for tuning, test split for reported numbers. A variant tuned on test is disqualified — rerun on a new eval version.
4. All metrics, all slices, in every report — no cherry-picking. Negative and inconclusive results get full reports.
5. Close calls (overall correctness delta < 0.05): run the pairwise A/B judge protocol and report win/tie/loss rates alongside rubric scores.
6. ~10% of judged scores per experiment get human spot-check; log disagreements in the report; judge prompt version recorded in every result file.
