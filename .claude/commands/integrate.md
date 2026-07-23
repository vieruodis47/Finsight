---
description: Run an integration task across Python/Node/React through the full harness loop
argument-hint: <task description>
---

Delegate to the **gemini-integration** agent with this task: $ARGUMENTS

Require it to follow its contract-first workflow end to end:
read `.claude/memory/integration-memory.md` -> locate both sides of the contract -> state the contract change -> edit all sides -> verify (pytest, node --check, tsc) -> append learnings to memory -> add a `.claude/MANIFEST.md` entry with a falsifiable prediction.
