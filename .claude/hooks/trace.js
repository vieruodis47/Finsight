#!/usr/bin/env node
// AHE experience observability: append one JSONL line per tool use.
// Registered as a PostToolUse hook in .claude/settings.json. Must never fail the session.
try {
  let raw = '';
  process.stdin.on('data', (d) => (raw += d));
  process.stdin.on('end', () => {
    try {
      const e = JSON.parse(raw || '{}');
      const line = JSON.stringify({
        ts: new Date().toISOString(),
        tool: e.tool_name || 'unknown',
        input: summarize(e.tool_input),
        ok: !(e.tool_response && e.tool_response.is_error),
      });
      require('fs').appendFileSync(
        require('path').join(__dirname, '..', 'evidence', 'traces', 'tool-log.jsonl'),
        line + '\n'
      );
    } catch (_) {}
    process.exit(0);
  });
  setTimeout(() => process.exit(0), 3000);
} catch (_) {
  process.exit(0);
}

function summarize(input) {
  if (!input) return '';
  const s = input.command || input.file_path || input.pattern || JSON.stringify(input);
  return String(s).slice(0, 200);
}
