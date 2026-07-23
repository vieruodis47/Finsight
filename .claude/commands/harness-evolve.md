---
description: Run one AHE evolution round on this .claude/ harness itself
---

Run one evolution round on the harness (the files under `.claude/`), following Agentic Harness Engineering:

1. **Attribute first**: read `.claude/MANIFEST.md`. For every entry with verdict `pending`, check its prediction against what actually happened since (evidence reports, test results, memory). Set verdict to `confirmed` or `reverted`; if `reverted`, undo that edit (git history gives file-level rollback).
2. **Read the evidence corpus**: `.claude/evidence/overview.md`, then drill into individual reports only as needed.
3. **Propose edits** to harness components only — `agents/*.md`, `commands/*.md`, `memory/*.md`, `hooks/*`, `settings.json`. Each edit must map to ONE component and cite specific evidence. Do not edit application code in this round.
4. **Record**: for each edit, append a MANIFEST entry: evidence, root cause, edit, predicted fixes, at-risk regressions, verdict `pending`.
5. **Commit**: `git add .claude && git commit -m "harness: evolution round <n>"` so every round is a revertible tag.

Constraints (controllability): never weaken verification steps to make tasks "pass"; never delete the seed workflow in `agents/gemini-integration.md`; memory edits must merge, not wipe.
