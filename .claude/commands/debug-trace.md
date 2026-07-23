---
description: Distill an integration failure into a layered evidence report (AHE Agent Debugger)
argument-hint: <what failed, or path to logs>
---

Act as the Agent Debugger for this failure: $ARGUMENTS

1. Gather raw signal: relevant server logs, `.claude/evidence/traces/tool-log.jsonl` (recent entries), failing request/response bodies, stack traces. Reproduce with `curl` if possible.
2. Localize the seam: which boundary failed — React->Node, React->Python, Node->Gemini, Python->Gemini, Python<->RavenDB, or env/ports?
3. Identify root cause, distinguishing contract drift, env misconfig, SDK behavior, and logic bugs.
4. Write a report to `.claude/evidence/reports/YYYY-MM-DD-<slug>.md` following `.claude/evidence/reports/TEMPLATE.md`. Link raw evidence rather than pasting it (progressive disclosure).
5. Update the one-line index in `.claude/evidence/overview.md`.
6. If the root cause reveals a harness deficiency (agent lacked a fact, rule, or check), say so explicitly — that feeds `/harness-evolve`.
