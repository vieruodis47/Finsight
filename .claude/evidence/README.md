# Evidence corpus (AHE experience observability)

Layered, drill-down evidence. Read `overview.md` first; open individual reports only as needed; raw traces are the last resort.

- `overview.md` — one-line index of all reports; entry point every round.
- `reports/` — one file per analyzed failure/success, from TEMPLATE.md. Named `YYYY-MM-DD-<slug>.md`.
- `traces/tool-log.jsonl` — raw tool-use trace appended by the PostToolUse hook (`hooks/trace.js`). Verify report claims against it.
