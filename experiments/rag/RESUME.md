# How to finish the RAG experiments (no Claude needed)

_State as of 2026-07-10 ~04:00 CDT._

## What is already DONE (do not redo)

| Piece | Status |
|---|---|
| Corpus (6 filings: AAPL/MSFT/NVDA × 2 years) | ✅ indexed in RavenDB |
| E-1 baseline (naive) — runs + scoring | ✅ complete (`results/E-1/summary.json`) |
| E-3 prompt/context variants — runs + scoring | ✅ complete (`results/E-3/summary.json`) |
| E-2 architectures — naive, hyde, most of graph | ✅ run; valid subset scored |
| **E-2 — agentic, modular, rest of graph (~105 runs)** | ❌ **blocked on daily quota — the one remaining step** |
| Verdict reports (`.claude/evidence/experiments/E-*.md`) | Claude writes these next session from the summaries |

## The one thing left to run

Free-tier Gemini allows ~500 generations/day for the model the variants use;
the daily quota resets at **2:00 AM Central** (midnight Pacific).

**Option A (automatic):** a Windows scheduled task `FinSightE2Completion` fires
**tonight (Sat Jul 11) at 2:10 AM** if the machine is on and you are logged in
(locked screen is fine). Claude Desktop does NOT need to be open.

**Option B (manual):** any day after 2:00 AM Central (before anything else
spends that day's quota), double-click:

```
experiments\rag\complete_E2.cmd
```

It starts the database containers, runs only the missing E-2 runs
(finished work is skipped automatically), and scores everything.
Takes roughly 60–90 minutes. Safe to re-run — if it dies mid-way
(quota, reboot), run it again in the next window and it continues.

**Prerequisites:** Docker Desktop running; machine stays on for the duration.

## How to check whether E-2 is done

`experiments\rag\results\E-2\summary.json` exists and
`experiments\rag\results\e2_completion.log` ends with `finished`.
Each of the five files `results/E-2/{naive,graph,hyde,agentic,modular}.jsonl`
should contain 48 lines (16 questions × 3 repeats).

## Where the results live

- Aggregated metrics (all slices): `experiments/rag/results/E-{1,2,3}/summary.json`
- Per-run scores: `experiments/rag/results/E-*/scores/<variant>.jsonl`
- Raw answers/traces: `experiments/rag/results/E-*/<variant>.jsonl`
- Experiment ledger + predictions: `.claude/EXPERIMENTS.md`
- Final verdict reports: `.claude/evidence/experiments/E-*.md` — written by
  Claude next session (ask for "/rag-verdict" or just "write the RAG verdicts").

## If something looks broken

Ask Claude next session — full context is saved in
`.claude/memory/rag-memory.md` and this file. Nothing here is destructive;
worst case is re-running a step that then skips everything already done.
