import React from 'react';
import { c, font } from '../theme';
import { ChatSource } from '../types';

// Shared chat-answer rendering, used by both the full ChatInterface and the
// compare-view FinChat strip so an answer looks identical in both places:
//   - renderChatMarkdown: markdown (headings, bullets, tables) with inline
//     [TICKER 10-K #N] citation tags rendered as muted superscripts.
//   - AnswerMeta: the retrieval-path badge + source-citation chips block.

// ── style atoms ───────────────────────────────────────────────────────────────

const sourceTag: React.CSSProperties = {
  fontSize: 10, padding: '2px 7px', borderRadius: 6,
  background: c.surfaceAlt, color: c.textMuted, fontFamily: font.ui,
  whiteSpace: 'nowrap',
};

const pathBadge = (path: string): React.CSSProperties => ({
  fontSize: 10, padding: '2px 8px', borderRadius: 6, fontFamily: font.ui,
  whiteSpace: 'nowrap', fontWeight: 500,
  ...(path === 'graph'
    ? { background: c.brandTint, color: c.brand }
    : path === 'both'
    ? { background: c.accentSoft, color: c.accentFg }
    : path === 'vector_no_graph'
    ? { background: c.warnSurface, color: c.warnFg }
    : { background: c.surfaceAlt, color: c.textMuted }),
});

const pathBadgeLabel = (path: string): string =>
  path === 'graph'
    ? '◉ financial data'
    : path === 'both'
    ? '◉ financial data + filing text'
    : path === 'vector_no_graph'
    ? '◎ filing text · graph data not loaded'
    : '◉ filing text';

// ── markdown renderer ─────────────────────────────────────────────────────────

const _parseInline = (text: string): React.ReactNode => {
  const parts = text.split(/(\*\*[^*]+\*\*|\[[A-Z0-9]+\s+10-K\s+#\d+\])/g);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) {
          return <strong key={i} style={{ fontWeight: 600 }}>{p.slice(2, -2)}</strong>;
        }
        if (/^\[[A-Z0-9]+\s+10-K\s+#\d+\]$/.test(p)) {
          return (
            <span
              key={i}
              style={{
                fontSize: 9, color: c.textFaint, fontFamily: font.ui,
                verticalAlign: 'super', lineHeight: 1, letterSpacing: 0,
              }}
            >
              {p}
            </span>
          );
        }
        return p;
      })}
    </>
  );
};

export const renderChatMarkdown = (text: string): React.ReactNode => {
  if (!text) return null;
  const lines = text.split('\n');
  const nodes: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Table: consume consecutive | lines
    if (line.trim().startsWith('|')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      const rows = tableLines.filter(l => !/^\|[\s|:-]+\|$/.test(l.trim()));
      nodes.push(
        <table key={`tbl-${i}`} style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 12 }}>
          <tbody>
            {rows.map((row, ri) => {
              const cells = row.split('|').slice(1, -1);
              const isHeader = ri === 0;
              return (
                <tr key={ri}>
                  {cells.map((cell, ci) =>
                    isHeader ? (
                      <th key={ci} style={{ padding: '4px 10px', textAlign: 'left', fontWeight: 600, borderBottom: `1px solid ${c.border}`, color: c.text, fontFamily: font.ui, fontSize: 12 }}>
                        {cell.trim()}
                      </th>
                    ) : (
                      <td key={ci} style={{ padding: '4px 10px', borderBottom: `0.5px solid ${c.borderFaint}`, color: c.text2, fontFamily: font.ui }}>
                        {_parseInline(cell.trim())}
                      </td>
                    )
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      );
      continue;
    }

    if (line.startsWith('## ')) {
      nodes.push(<h2 key={i} style={{ fontSize: 13, fontWeight: 600, color: c.text, margin: '16px 0 4px', fontFamily: font.ui, letterSpacing: '-0.01em' }}>{_parseInline(line.slice(3))}</h2>);
    } else if (line.startsWith('# ')) {
      nodes.push(<h1 key={i} style={{ fontSize: 15, fontWeight: 600, color: c.text, margin: '20px 0 5px', fontFamily: font.ui, letterSpacing: '-0.01em' }}>{_parseInline(line.slice(2))}</h1>);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      nodes.push(
        <li key={i} style={{ marginLeft: 16, marginBottom: 3, fontSize: 13, color: c.text2, lineHeight: 1.6, fontFamily: font.ui }}>
          {_parseInline(line.slice(2))}
        </li>
      );
    } else if (line.trim() === '') {
      nodes.push(<div key={i} style={{ height: 5 }} />);
    } else {
      nodes.push(
        <p key={i} style={{ fontSize: 13, color: c.text2, lineHeight: 1.65, marginBottom: 3, fontFamily: font.ui }}>
          {_parseInline(line)}
        </p>
      );
    }
    i++;
  }

  return nodes;
};

// ── retrieval-path badge + source chips ───────────────────────────────────────

// Renders the metadata block below an assistant answer: the retrieval-path badge
// and the source-citation chips, separated from the answer body by a hairline.
// Returns null when there's nothing to show (no path, or path 'none', and no
// sources) — the same gate ChatInterface used inline.
export const AnswerMeta: React.FC<{ retrievalPath?: string; sources?: ChatSource[] }> = ({ retrievalPath, sources }) => {
  const hasPath = !!retrievalPath && retrievalPath !== 'none';
  const hasSources = !!sources && sources.length > 0;
  if (!hasPath && !hasSources) return null;

  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: `0.5px solid ${c.border}` }}>
      {hasPath && (
        <div style={{ marginBottom: hasSources ? 6 : 0 }}>
          <span style={pathBadge(retrievalPath!)}>{pathBadgeLabel(retrievalPath!)}</span>
        </div>
      )}
      {hasSources && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {sources!.map((s, i) => (
            <span key={`${s.source}-${s.chunk_index}-${i}`} style={sourceTag} title={s.source}>
              {s.ticker} {s.form} · #{s.chunk_index}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
