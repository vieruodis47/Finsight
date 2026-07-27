import React, { useId, useRef, useState } from 'react';
import { c, font } from '../theme';
import { ChatSource } from '../types';

// Shared chat-answer rendering, used by both the full ChatInterface and the
// compare-view FinChat strip so an answer looks identical in both places:
//   - renderChatMarkdown: markdown (headings, bullets, tables) with inline
//     numbered [n] citation markers.
//   - GroundedAnswer: the answer body + retrieval-path badge + the numbered
//     reference list (each entry inspectable), wired so an inline [n] marker
//     scrolls to and expands its reference.
//
// Citations are DETERMINISTIC and VALIDATED server-side (rag.build_references /
// validate_citations): the reference list is built from the actually-retrieved
// chunks, and only citation numbers in `validCitations` are linkified — any
// other [n] the model emitted is a fabrication and is dropped, never rendered as
// a link.

// ── style atoms ───────────────────────────────────────────────────────────────

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

// Readable company name (resolved server-side); fall back to the bare ticker.
// Never the raw source URL.
const companyName = (s: ChatSource): string => s.company || s.ticker;
// Best-effort section; may be empty (mid-section chunks). Never the source URL.
const sectionLabel = (s: ChatSource): string => s.section || '';
// The SEC href lives here — used only as a link target, never rendered as text.
const edgarUrl = (s: ChatSource): string =>
  (s.url || (s.source?.startsWith('http') ? s.source : '')) || '';

// Palette values from the sources spec that aren't theme tokens (theme tokens are
// used everywhere they exist — see c.brand / c.brandTint / c.text / c.textMuted).
const CITE = {
  label: '#788798',    // small-caps label + section text
  snippet: '#8595A5',  // one-line snippet grey
  cardBorder: '#E4E9EF',
  quoteBg: '#F7F9FB',
} as const;

// ── inline markers ────────────────────────────────────────────────────────────

// Context threaded through the markdown renderer so a [n] marker can become a
// real, focusable button that jumps to reference n. When absent (mid-stream,
// before citations resolve), markers render as inert muted superscripts so the
// footprint doesn't jump when they later become buttons.
export interface CiteContext {
  valid: Set<number>;
  byNumber: Map<number, ChatSource>;
  onCite: (n: number) => void;
}

const markerSuper: React.CSSProperties = {
  fontSize: 9, verticalAlign: 'super', lineHeight: 1, letterSpacing: 0,
  fontFamily: font.ui,
};

const citeAriaLabel = (n: number, s: ChatSource): string => {
  const sec = sectionLabel(s);
  return `Source ${n}: ${companyName(s)} ${s.form}${sec ? `, ${sec}` : ''}`;
};

const CitationMarker: React.FC<{ n: number; source?: ChatSource; onCite: (n: number) => void }> = ({ n, source, onCite }) => {
  const label = source ? citeAriaLabel(n, source) : `Source ${n}`;
  return (
    <button
      type="button"
      onClick={() => onCite(n)}
      aria-label={label}
      style={{
        ...markerSuper,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        minWidth: 13, height: 13, padding: '0 3px', marginLeft: 1,
        border: 'none', borderRadius: 4, cursor: 'pointer',
        background: c.brandTint, color: c.brand, fontWeight: 600,
      }}
    >
      {n}
    </button>
  );
};

const InertMarker: React.FC<{ n: number }> = ({ n }) => (
  <span style={{ ...markerSuper, color: c.textFaint }}>[{n}]</span>
);

// Render a [n] token given the citation context: a clickable marker when n is
// valid + known; nothing when it's a fabricated/out-of-range citation (dropped);
// an inert superscript while streaming (no context yet).
const _renderMarker = (n: number, key: number, cite?: CiteContext): React.ReactNode => {
  if (!cite) return <InertMarker key={key} n={n} />;
  if (cite.valid.has(n) && cite.byNumber.has(n)) {
    return <CitationMarker key={key} n={n} source={cite.byNumber.get(n)} onCite={cite.onCite} />;
  }
  return null; // invalid / unsupported — never render a misleading link
};

const _parseInline = (text: string, cite?: CiteContext): React.ReactNode => {
  const parts = text.split(/(\*\*[^*]+\*\*|\[\d{1,3}\])/g);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) {
          return <strong key={i} style={{ fontWeight: 600 }}>{p.slice(2, -2)}</strong>;
        }
        const cm = /^\[(\d{1,3})\]$/.exec(p);
        if (cm) return _renderMarker(parseInt(cm[1], 10), i, cite);
        return p;
      })}
    </>
  );
};

// ── markdown renderer ─────────────────────────────────────────────────────────

export const renderChatMarkdown = (text: string, cite?: CiteContext): React.ReactNode => {
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
                        {_parseInline(cell.trim(), cite)}
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
      nodes.push(<h2 key={i} style={{ fontSize: 13, fontWeight: 600, color: c.text, margin: '16px 0 4px', fontFamily: font.ui, letterSpacing: '-0.01em' }}>{_parseInline(line.slice(3), cite)}</h2>);
    } else if (line.startsWith('# ')) {
      nodes.push(<h1 key={i} style={{ fontSize: 15, fontWeight: 600, color: c.text, margin: '20px 0 5px', fontFamily: font.ui, letterSpacing: '-0.01em' }}>{_parseInline(line.slice(2), cite)}</h1>);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      nodes.push(
        <li key={i} style={{ marginLeft: 16, marginBottom: 3, fontSize: 13, color: c.text2, lineHeight: 1.6, fontFamily: font.ui }}>
          {_parseInline(line.slice(2), cite)}
        </li>
      );
    } else if (line.trim() === '') {
      nodes.push(<div key={i} style={{ height: 5 }} />);
    } else {
      nodes.push(
        <p key={i} style={{ fontSize: 13, color: c.text2, lineHeight: 1.65, marginBottom: 3, fontFamily: font.ui }}>
          {_parseInline(line, cite)}
        </p>
      );
    }
    i++;
  }

  return nodes;
};

// ── reference list ─────────────────────────────────────────────────────────────

const dot = <span aria-hidden="true" style={{ color: CITE.label, margin: '0 5px' }}>·</span>;

const ReferenceRow: React.FC<{
  source: ChatSource;
  open: boolean;
  onToggle: () => void;
  liRef: (el: HTMLLIElement | null) => void;
}> = ({ source, open, onToggle, liRef }) => {
  const panelId = `cite-panel-${source.number}-${useId()}`;
  const company = companyName(source);
  const section = sectionLabel(source);
  const url = edgarUrl(source);

  return (
    <li
      ref={liRef}
      tabIndex={-1}
      className="cite-row"
      style={{
        listStyle: 'none', background: c.bg,
        border: `1px solid ${CITE.cardBorder}`, borderRadius: 10, overflow: 'hidden',
      }}
    >
      {/* Collapsed row — the whole card header is one accessible button.
          Compact: single line, small chip, ~13px company (semibold, not bold
          black), muted form/section, one-line snippet. */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={citeAriaLabel(source.number!, source)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, width: '100%',
          textAlign: 'left', background: 'transparent', border: 'none',
          padding: '7px 9px', cursor: 'pointer', fontFamily: font.ui,
        }}
      >
        {/* Numbered sapphire chip — inverts to filled when expanded. */}
        <span
          aria-hidden="true"
          style={{
            flexShrink: 0, minWidth: 16, height: 16, borderRadius: 4,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 10, fontWeight: 600, lineHeight: 1,
            background: open ? c.brand : c.brandTint,
            color: open ? c.onBrand : c.brand,
          }}
        >
          {source.number}
        </span>

        <span style={{ flex: 1, minWidth: 0 }}>
          {/* {Company} · {form} · {section} — company semibold ink, form muted,
              section label-grey. */}
          <span style={{ display: 'block', fontSize: 12, lineHeight: 1.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            <span style={{ fontWeight: 600, color: c.text }}>{company}</span>
            {dot}
            <span style={{ color: c.textMuted }}>{source.form}</span>
            {section && <>{dot}<span style={{ color: CITE.label }}>{section}</span></>}
          </span>
          {/* One-line snippet, collapsed only (full text shows when open). */}
          {!open && source.preview && (
            <span style={{ display: 'block', fontSize: 11, color: CITE.snippet, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.35 }}>
              {source.preview}
            </span>
          )}
        </span>

        <span aria-hidden="true" style={{ flexShrink: 0, fontSize: 10, color: CITE.label }}>
          {open ? '▴' : '▾'}
        </span>
      </button>

      {/* Expanded: full chunk in a sapphire-ruled quote block + the EDGAR link
          (the only place the URL appears — as an href, never as text). */}
      {open && (
        <div
          id={panelId}
          role="region"
          aria-live="polite"
          aria-label={`Source ${source.number} passage`}
          className="cite-reveal"
          style={{ padding: '0 10px 10px' }}
        >
          <blockquote
            style={{
              margin: '2px 0 0', padding: '9px 12px', background: CITE.quoteBg,
              borderLeft: `2px solid ${c.brand}`, borderRadius: '0 6px 6px 0',
              fontSize: 12, lineHeight: 1.65, color: c.text2, fontFamily: font.ui,
              whiteSpace: 'pre-wrap', maxHeight: 260, overflowY: 'auto',
            }}
          >
            {source.text || source.preview || '(passage text unavailable)'}
          </blockquote>
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 8,
                fontSize: 11.5, fontWeight: 500, color: c.brand,
                fontFamily: font.ui, textDecoration: 'none',
              }}
            >
              View on SEC EDGAR <span aria-hidden="true">↗</span>
            </a>
          )}
        </div>
      )}
    </li>
  );
};

// ── grounded answer (body + badge + references) ────────────────────────────────

// One stateful unit per assistant answer, so inline [n] markers and the
// reference rows share the same expand/scroll state. Citations render only once
// streaming has finished (they resolve at completion, not per token).
export const GroundedAnswer: React.FC<{
  text: string;
  streaming?: boolean;
  retrievalPath?: string;
  sources?: ChatSource[];
  validCitations?: number[];
  // The inline metric chart, rendered BETWEEN the answer text and the sources so
  // the message reads text → chart → citations. Passed as a node (kept out of
  // this util's imports) and only shown once streaming completes.
  chartSlot?: React.ReactNode;
}> = ({ text, streaming, retrievalPath, sources, validCitations, chartSlot }) => {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const rowRefs = useRef<Map<number, HTMLLIElement>>(new Map());

  const refs = (sources ?? []).filter((s): s is ChatSource & { number: number } => typeof s.number === 'number');
  const validSet = new Set(validCitations ?? []);
  const showCitations = !streaming;

  const cite: CiteContext | undefined = showCitations && refs.length > 0
    ? {
        valid: validSet,
        byNumber: new Map(refs.map(s => [s.number, s])),
        onCite: (n: number) => {
          setExpanded(prev => new Set(prev).add(n));
          const el = rowRefs.current.get(n);
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            el.focus({ preventScroll: true });
          }
        },
      }
    : undefined;

  const toggle = (n: number) =>
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(n) ? next.delete(n) : next.add(n);
      return next;
    });

  const hasPath = !!retrievalPath && retrievalPath !== 'none';
  const showMeta = showCitations && (hasPath || refs.length > 0);

  return (
    <>
      {renderChatMarkdown(text, cite)}
      {streaming && (
        <span className="stream-caret" aria-hidden="true" style={{ background: c.brand }} />
      )}

      {/* Chart sits between the text and the citation cards; it resolves at
          completion (same gate as citations), so both appear together in the new
          order with no intermediate layout jump. */}
      {!streaming && chartSlot}

      {showMeta && (
        <div style={{ marginTop: 10, paddingTop: 8, borderTop: `0.5px solid ${c.border}` }}>
          {hasPath && (
            <div style={{ marginBottom: refs.length > 0 ? 8 : 0 }}>
              <span style={pathBadge(retrievalPath!)}>{pathBadgeLabel(retrievalPath!)}</span>
            </div>
          )}
          {refs.length > 0 && (
            <>
              <p style={{ fontSize: 10, fontWeight: 600, color: CITE.label, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 7px', fontFamily: font.ui }}>
                {(() => {
                  // Graph/XBRL citations are facts, not "passages" — keep the noun
                  // honest per path so both answer types read naturally.
                  const noun = retrievalPath === 'graph' ? 'source' : 'passage';
                  return `Sources · ${refs.length} ${noun}${refs.length > 1 ? 's' : ''}`;
                })()}
              </p>
              <ol aria-label="Source references" style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: 0, padding: 0, listStyle: 'none' }}>
                {refs.map(s => (
                  <ReferenceRow
                    key={s.number}
                    source={s}
                    open={expanded.has(s.number)}
                    onToggle={() => toggle(s.number)}
                    liRef={el => { if (el) rowRefs.current.set(s.number, el); else rowRefs.current.delete(s.number); }}
                  />
                ))}
              </ol>
            </>
          )}
        </div>
      )}
    </>
  );
};
