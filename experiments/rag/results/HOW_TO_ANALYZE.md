# How to read and plot the RAG experiment results

Audience: an analysis session (human or LLM) producing matplotlib charts from
this directory. Everything needed is on disk here; no database or API access
required. Definitions of every metric: `../METRICS.md` (binding). Experiment
predictions and verdict rules: `../../../.claude/EXPERIMENTS.md`.

## 1. What is in this directory

```
results/
  ingest.json              # corpus ingest cost report (wall-clock, chunks)
  embed_cache.jsonl        # infra cache — ignore for analysis
  E-1/                     # baseline characterization (naive only)
  E-2/                     # architecture comparison (naive/graph/hyde/agentic/modular)
  E-3/                     # prompt & context engineering (5 prompt variants, fixed retrieval)
```

Per experiment directory:

```
E-*/
  run_manifest.json        # config: eval set digest, k, repeats, variant configs, config_hash
  <variant>.jsonl          # RAW runs: one line per question x repeat (answer, sources, trace, cost)
  scores/<variant>.jsonl   # SCORED runs: one line per question x repeat (all metrics)
  summary.json             # aggregated metrics per variant per slice  <-- START HERE
  judge_cache.jsonl        # infra cache — ignore for analysis
```

**Completeness status (check before plotting):**
- E-1: complete (48 runs, 0 errors).
- E-3: complete (240 runs, 0 errors).
- E-2: complete ONLY if `summary.json` exists here AND each of the five
  `E-2/*.jsonl` raw files has 48 lines with (near-)zero non-null `error`
  fields. Until then agentic/modular/graph contain quota-artifact error
  records that are re-run by `../complete_E2.cmd` — **do not draw
  architecture conclusions from a partial E-2**; either skip it or plot only
  `naive`/`hyde` with an explicit caveat.

## 2. summary.json schema (the aggregation you should plot from)

```json
{
  "exp": "E-1",
  "judge_model": "gemma-4-31b-it",
  "judge_prompt_version": 3,
  "match_granularity": "<how retrieved chunks were matched to gold sources>",
  "variants": {
    "<variant>": {
      "overall":            { <block> },
      "single-hop":         { <block> },
      "multi-hop":          { <block> },
      "aggregation":        { <block> },
      "temporal":           { <block> },
      "post_cutoff_subset": { <block> }   // contamination control (see §4)
    }
  }
}
```

Each `<block>`:

| Field | Meaning | Notes for plotting |
|---|---|---|
| `n_questions`, `n_runs`, `n_errors` | population sizes | annotate n; errored runs score 0 and are INCLUDED |
| `correctness_mean` | mean of per-question means (repeats collapsed first), 0–1 | **primary metric**; the registered comparisons live on the multi-hop and aggregation slices |
| `correctness_std_across_questions` | std across question means | use as error bars |
| `recall_at_k`, `precision_at_k`, `mrr` | retrieval diagnostics vs gold sources | see graph-variant caveat §4 |
| `faithfulness_mean_0to2` | groundedness guardrail, 0–2 scale | nulls (errored runs) excluded from the mean |
| `citation_validity` | fraction of [TICKER FORM #N] tags pointing at actually-retrieved chunks | null-safe mean; answers with no tags excluded |
| `citation_support` | fraction of sampled cited sentences the cited chunk actually supports | sampled ≤2 sentences/answer |
| `answers_with_citations` | fraction of runs with ≥1 citation tag | plot alongside validity — validity alone is misleading if few answers cite |
| `facts_found_ratio` | facts found / facts expected | the coverage number for the aggregation slice |
| `tokens_per_q_mean`, `prompt_tokens_mean`, `completion_tokens_mean` | cost axis | |
| `latency_p50_ms`, `latency_p95_ms` | wall-clock per question | caveat: repeated identical queries skip the embed API hop (cache), so absolute latencies are optimistic; cross-variant comparison is still fair |
| `retrieval_calls_mean`, `llm_calls_mean` | calls per question | agentic/modular are the expensive ones by design |

## 3. scores/<variant>.jsonl schema (per-run drill-down)

One JSON object per line, keys:
`exp, variant, qid, repeat, slice, post_cutoff, correctness, per_fact,
facts_found, facts_expected, recall_at_k, precision_at_k, mrr, retrieved,
faithfulness, citation_tag_count, citation_validity, citation_support,
prompt_tokens, completion_tokens, total_tokens, latency_ms, retrieval_calls,
llm_calls, error, judge_model, judge_prompt_version, match_granularity`

- `slice` ∈ {single-hop, multi-hop, aggregation, temporal}; `qid` ∈ q001…q016.
- `per_fact` is a list with per-gold-fact `{claim, check, score, method, ...}`
  — `method` tells you whether the deterministic numeric matcher
  (`numeric_matcher`) or the LLM judge (`judge_r1`, `numeric_fallback_judge`)
  produced the score. Useful for a "how much is judge-dependent" plot.
- `faithfulness`/`citation_*` may be null (errored runs, no-tag answers):
  filter nulls, never fillna(0).
- Raw `<variant>.jsonl` files additionally contain `answer`, `sources`,
  `trace`, `llm_call_inputs` — useful for qualitative tables, too big to plot.

## 4. Semantics you must respect (or the charts will lie)

1. **Slices are the story.** The pre-registered hypotheses are per-slice
   (e.g. "agentic ≥ naive + 0.15 on multi-hop"). A single overall bar per
   variant hides exactly what the experiment was built to show. Default to
   grouped bars: x = slice, group = variant.
2. **E-3 compares prompts, not retrieval** — every E-3 variant retrieves
   identically; plot E-3 as deltas vs the `naive` (production prompt) row,
   and include citation_validity/support and completion_tokens: the
   registered predictions are about citations and token cost as much as
   correctness.
3. **Graph variant recall@k ≈ 0 is structural, not failure**: when the graph
   router answers from SPARQL it retrieves no text chunks, so chunk-level
   recall/precision/MRR are 0 by construction while correctness can be high.
   Annotate this on any E-2 retrieval chart (or exclude graph from retrieval
   panels with a note).
4. **post_cutoff_subset** = questions answerable only from filings newer than
   the generator's training data. If a variant's correctness collapses there
   relative to its overall number, its knowledge is parametric, not
   retrieved. Plot overall vs post-cutoff correctness side by side per
   variant — this is the contamination-control chart.
5. **Repeats**: 3 per question. Collapse to per-question means before
   aggregating (summary.json already does this). For per-run scatter, jitter
   rather than average silently.
6. **Errors**: runs with non-null `error` score correctness 0 and are
   included (METRICS.md rule) — but in a partial E-2 those errors are quota
   artifacts scheduled for re-run, not variant failures. Check `n_errors`
   before trusting any E-2 block.
7. n is small (16 test questions, 3–4 per slice). Show the per-question dots
   (strip plot) on top of bars where possible; don't over-read deltas
   < ~0.1 on a 4-question slice.

## 5. Suggested figures

1. **E-2 primary**: correctness by slice × variant (grouped bars +
   `correctness_std_across_questions` whiskers + per-question dots from
   scores/). One panel per slice group, `naive` always first as baseline.
2. **Cost-quality frontier (E-2)**: x = `tokens_per_q_mean` (log), y = mean
   correctness on multi-hop+aggregation, marker size = `latency_p50_ms`,
   one point per variant. This is the "is agentic worth 4x tokens" chart.
3. **Retrieval diagnostics (E-2, minus graph)**: recall@5 / precision@5 / MRR
   grouped bars.
4. **E-3 prompt deltas**: horizontal bar chart of (variant − naive) for
   correctness_mean (overall + temporal + multi-hop), citation_validity,
   citation_support, faithfulness; second axis/panel for
   completion_tokens_mean ratio. Highlights whether `prompt_quote_first`
   earned its extra tokens (registered prediction: +0.10 multi-hop/temporal).
5. **Contamination control (all exps)**: overall vs post_cutoff correctness
   per variant.
6. **Per-question heatmap (E-2 or E-3)**: rows = variants, cols = q001…q016
   (grouped by slice), cell = mean correctness. Failures cluster visibly.

## 6. Starter code

```python
import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt   # pip install matplotlib pandas

ROOT = Path(__file__).parent if "__file__" in dir() else Path(".")

def load_summary(exp):
    with open(ROOT / exp / "summary.json", encoding="utf-8") as f:
        s = json.load(f)
    rows = []
    for variant, blocks in s["variants"].items():
        for slice_name, block in blocks.items():
            rows.append({"exp": exp, "variant": variant,
                         "slice": slice_name, **block})
    return pd.DataFrame(rows)

def load_scores(exp):
    frames = []
    for p in (ROOT / exp / "scores").glob("*.jsonl"):
        frames.append(pd.read_json(p, lines=True))
    return pd.concat(frames, ignore_index=True)

# Example: E-2 correctness by slice x variant, error bars + question dots
summ = load_summary("E-2")
runs = load_scores("E-2")
slices = ["single-hop", "multi-hop", "aggregation", "temporal"]
variants = ["naive", "graph", "hyde", "agentic", "modular"]  # naive first

fig, ax = plt.subplots(figsize=(10, 5))
width = 0.8 / len(variants)
for i, v in enumerate(variants):
    sub = summ[(summ.variant == v) & (summ.slice.isin(slices))].set_index("slice").reindex(slices)
    x = [slices.index(s) + i * width for s in slices]
    ax.bar(x, sub.correctness_mean, width=width, label=v,
           yerr=sub.correctness_std_across_questions, capsize=3)
    # per-question dots
    q = (runs[runs.variant == v].groupby(["slice", "qid"]).correctness.mean()
         .reset_index())
    ax.scatter([slices.index(s) + i * width for s in q.slice],
               q.correctness, s=10, color="black", zorder=3, alpha=0.6)
ax.set_xticks([i + 0.4 - width / 2 for i in range(len(slices))])
ax.set_xticklabels(slices); ax.set_ylabel("correctness (0-1)"); ax.set_ylim(0, 1.05)
ax.legend(title="variant"); ax.set_title("E-2: answer correctness by question type")
plt.tight_layout(); plt.show()
```

## 7. Known headline numbers (verify against summary.json, don't trust prose)

- E-1 naive overall: correctness 0.917 ± 0.161, recall@5 0.813,
  faithfulness 2.0/2, citation validity 1.00, ~3.8k tokens/q, p50 864 ms.
  Per-slice numbers and the E-1 verdict against its pre-registered prediction
  live in `E-1/summary.json` and `.claude/EXPERIMENTS.md`.
- Judge: `gemma-4-31b-it`, judge prompts v3, temp 0 (recorded per file).
- Generation: `gemini-3.1-flash-lite`, temp 0.2, k=5, n=3 repeats, eval set
  v1 test split (16 questions; composition in `../eval/SCHEMA.md`).
