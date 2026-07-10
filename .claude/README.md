# FinSight .claude/ harness

An agent harness for this repo, structured after **Agentic Harness Engineering** (arXiv:2604.25850): every harness component is a file, every failure becomes distilled evidence, every edit/experiment carries a falsifiable prediction.

Two domains: **integration** (Python <-> Node <-> React seams) and **RAG experiments** (proving which retrieval architecture is best).

## AHE component map

| AHE component (paper §3.1) | Here |
|---|---|
| System prompt | `agents/*.md` bodies |
| Sub-agent configuration | `agents/gemini-integration.md`, `agents/rag-experiment.md` frontmatter |
| Tool description/implementation | agent `tools:` allowlists + `commands/*.md` |
| Skills | `commands/` (see Daily use) |
| Middleware | `hooks/trace.js` via `settings.json` (PostToolUse trace logger) |
| Long-term memory | `memory/integration-memory.md`, `memory/rag-memory.md` |

## Observability pillars

1. **Component** (§3.1): one file per component; edits are git-diffable and revertible at file granularity. RAG variants follow the same rule: one module per architecture in `backend/data_extract/rag_variants/`.
2. **Experience** (§3.2): `evidence/` — `overview.md` -> `reports/` (integration failures) and `evidence/experiments/` (experiment reports) -> `traces/tool-log.jsonl` (raw). Progressive disclosure: read shallow first. Raw experiment data: `experiments/rag/results/`.
3. **Decision** (§3.3): `MANIFEST.md` (harness/seam edits) and `EXPERIMENTS.md` (architecture hypotheses + leaderboard) — every entry pre-registers a prediction; the next round confirms, refutes, or reverts.

## Daily use

Integration:
- `/integrate <task>` — run an integration change through the contract-first loop.
- `/contract-check` — audit React<->Node<->Python contracts for drift.
- `/debug-trace <failure>` — distill a failure into an evidence report.

RAG experiments:
- `/rag-eval [scope]` — build/extend the versioned golden question set.
- `/rag-experiment <hypothesis>` — pre-register in EXPERIMENTS.md, implement variant, run, report.
- `/rag-verdict` — score pending experiments, set verdicts, update the leaderboard.

Harness itself:
- `/harness-evolve` — one AHE round: attribute pending manifest predictions, read evidence, improve the harness, commit.

Tip: add `@.claude/memory/integration-memory.md` to a root `CLAUDE.md` if you want the seam map loaded in every session, not only inside the agents.
