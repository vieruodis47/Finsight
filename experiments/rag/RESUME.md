# RAG experiments — COMPLETE (2026-07-11)

All three experiments are run, scored, judged (including the pairwise
close-call protocol), and reported. Nothing is left to execute.

| Artifact | Where |
|---|---|
| Analysis notebook (tables + charts + computed verdicts) | `results/evaluation.ipynb` (Run All with the `.venv` kernel to recompute) |
| Aggregates | `results/E-{1,2,3}/summary.json` + `pairwise.json` |
| Evidence reports | `../../.claude/evidence/experiments/E-{1,2,3}.md` |
| Ledger, verdicts, leaderboard | `../../.claude/EXPERIMENTS.md` |
| Metric definitions / schemas | `../METRICS.md`, `eval/SCHEMA.md`, `eval/judge_prompts.md` (v3) |
| How to plot / extend analysis | `results/HOW_TO_ANALYZE.md` |

Headline: the naive baseline held (0.917); modular best overall (0.934,
+0.034 primary metric, below its registered +0.10); graph cheapest (2.3x)
but collapses on multi-hop via router misroutes; all E-2 predictions refuted
as written. E-3: prompts second-order; quote-first scaffold self-refuted.

Re-running anything is safe (resume + caches). Free-tier quota facts and the
follow-up idea (E-4: metrics-scoped graph router) are recorded in
`../../.claude/memory/rag-memory.md`.
