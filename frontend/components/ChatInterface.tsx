import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2, FileText, ChevronRight, ChevronLeft } from 'lucide-react';
import { Document, ChatMessage } from '../types';
import { askFinSight } from '../services/gemini';
import { c, font } from '../theme';
import { companyLabel } from '../utils/company';
import { useIsTablet } from '../utils/hooks';

interface ChatInterfaceProps {
  documents: Document[];
}

// ── style helpers ────────────────────────────────────────────────────────────

const fs: React.CSSProperties = { fontFamily: font.ui };

const pillBase: React.CSSProperties = {
  fontSize: 11, padding: '3px 10px', borderRadius: 10,
  cursor: 'pointer', border: 'none', fontFamily: font.ui,
  fontWeight: 500, whiteSpace: 'nowrap',
};

const pillActive: React.CSSProperties   = { ...pillBase, background: c.brandTint, color: c.brand };
const pillInactive: React.CSSProperties = { ...pillBase, background: c.surfaceAlt, color: c.textMuted };

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

// ── Ticker → company name map ─────────────────────────────────────────────────
// Covers common S&P 500 names. Falls back to the ticker if not found.


// Returns "Name (TICKER)" when we have a proper name, plain ticker otherwise.
const companyDisplay = (doc: Document): string => {
  const ticker  = doc.ticker?.toUpperCase() || doc.name;
  const name    = companyLabel(doc);
  return name !== ticker ? `${name} (${ticker})` : ticker;
};

// Deduplicates documents by ticker (or name when no ticker).
const uniqueCompanies = (docs: Document[]): Document[] => {
  const seen = new Set<string>();
  return docs.filter(doc => {
    const key = (doc.ticker || doc.name).toUpperCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

// Formats a list of names naturally: "A", "A and B", "A, B, and C", "A, B, C, and 2 more".
const formatList = (names: string[]): string => {
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  if (names.length <= 4)  return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`;
  const shown = names.slice(0, 3).join(', ');
  return `${shown}, and ${names.length - 3} more`;
};

// Builds the context-aware greeting shown as Finch's first message.
const buildGreeting = (docs: Document[]): string => {
  const intro = "Hi, I'm Finch — FinSight's chat assistant.";
  const companies = uniqueCompanies(docs);

  if (companies.length === 0) {
    return `${intro} You don't have any filings loaded yet. Add a company from the Documents page and I'll help you dig into its SEC filings.`;
  }

  if (companies.length === 1) {
    const display = companyDisplay(companies[0]);
    const name    = companyLabel(companies[0]);
    return `${intro} I see you have ${display} loaded. Want to load another company to compare, or shall we start with a question about ${name}?`;
  }

  const list = formatList(companies.map(companyDisplay));
  return `${intro} I've got ${list} loaded. Ask me about any of them, or compare them head to head.`;
};

// ── Markdown renderer for chat bubbles ───────────────────────────────────────
// Inline citation tags [AAPL 10-K #37] are rendered as muted superscripts.

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

const renderChatMarkdown = (text: string): React.ReactNode => {
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

// ── Finch avatar ─────────────────────────────────────────────────────────────
// Single fixed size everywhere — no prop, no percentage sizing — so flex layout
// can never compress the circle regardless of adjacent bubble height.

const FINCH_PX = 36; // single source of truth; change here to resize everywhere

const FinchAvatar: React.FC = () => {
  const [failed, setFailed] = useState(false);
  return (
    <div
      style={{
        // All four of these must agree for the circle to be uncompressible:
        width: FINCH_PX,
        height: FINCH_PX,
        minWidth: FINCH_PX,
        minHeight: FINCH_PX,
        borderRadius: '50%',
        overflow: 'hidden',
        flexShrink: 0,
        // Pins the avatar to the top of the message row regardless of the
        // row's alignItems setting — tall bubbles must not drag the avatar down.
        alignSelf: 'flex-start',
        background: c.surfaceAlt,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {failed ? (
        <Bot size={Math.round(FINCH_PX * 0.44)} color={c.textMuted} />
      ) : (
        <img
          src="/finch-avatar.png"
          alt="Finch"
          style={{
            display: 'block',
            // Absolute px, not 100% — percentage heights can be overridden
            // by an ancestor flex container's cross-axis sizing.
            width: FINCH_PX,
            height: FINCH_PX,
            objectFit: 'contain',
          }}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
};

// ── component ────────────────────────────────────────────────────────────────

const ChatInterface: React.FC<ChatInterfaceProps> = ({ documents }) => {
  const isTablet = useIsTablet();
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  useEffect(() => { setPanelCollapsed(isTablet); }, [isTablet]);

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: buildGreeting(documents),
      timestamp: new Date(),
    },
  ]);
  const [input, setInput]                   = useState('');
  const [isLoading, setIsLoading]           = useState(false);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [inputFocused, setInputFocused]     = useState(false);
  const [hoveredChip, setHoveredChip]       = useState<number | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef    = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Derive single-company context for contextual chips
  const singleCompany = (() => {
    const companies = uniqueCompanies(documents);
    return companies.length === 1 ? companies[0] : null;
  })();

  const primaryName   = singleCompany ? companyLabel(singleCompany) : null;
  const primaryTicker = singleCompany?.ticker?.toUpperCase() ?? null;

  const starterChips = primaryName
    ? [
        `What are ${primaryName}'s key business risks?`,
        `How did ${primaryName}'s revenue change year over year?`,
        `Summarize ${primaryName}'s business and competitive position`,
        `What was ${primaryName}'s free cash flow last year?`,
      ]
    : primaryTicker
    ? [
        `What are ${primaryTicker}'s key business risks?`,
        `How did ${primaryTicker}'s revenue change year over year?`,
        `Summarize ${primaryTicker}'s business and competitive position`,
        `What was ${primaryTicker}'s free cash flow last year?`,
      ]
    : [
        'What are the key business risks?',
        'How did revenue change year over year?',
        'Summarize the business and competitive position',
        'What was free cash flow last year?',
      ];

  const sendMessage = async (text: string) => {
    if (!text.trim() || isLoading) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      text,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const selected = documents.filter(d => selectedDocIds.includes(d.id));
      const tickers  = Array.from(new Set(selected.map(d => d.ticker).filter((t): t is string => Boolean(t))));
      const forms    = Array.from(new Set(selected.map(d => d.form).filter((f): f is '10-K' => Boolean(f))));
      const ticker   = tickers.length === 1 ? tickers[0] : undefined;
      const form     = forms.length   === 1 ? forms[0]   : undefined;

      const { answer, sources, retrievalPath } = await askFinSight(text, { ticker, form, k: 6 });

      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        text: answer,
        sources,
        retrievalPath,
        timestamp: new Date(),
      }]);
    } catch (err) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        text: `Error: ${err instanceof Error ? err.message : 'Failed to get a response.'}`,
        timestamp: new Date(),
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = () => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput('');
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const toggleDoc = (id: string) =>
    setSelectedDocIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  // Left-edge indent for elements that should align under the bubble, not the avatar.
  const AVATAR_GAP    = 8;
  const BUBBLE_INDENT = FINCH_PX + AVATAR_GAP; // 44px

  return (
    <div style={{ display: 'flex', height: '100%', ...fs }}>

      {/* ── Left panel (collapsible) ── */}
      <div
        style={{
          width: panelCollapsed ? 28 : 176, flexShrink: 0,
          background: c.surface,
          borderRight: `0.5px solid ${c.border}`,
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
          transition: 'width 0.18s ease',
        }}
      >
        {/* Toggle button */}
        <button
          onClick={() => setPanelCollapsed(p => !p)}
          title={panelCollapsed ? 'Show companies' : 'Hide companies'}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: '100%', height: 36, flexShrink: 0,
            border: 'none', background: 'transparent', cursor: 'pointer',
            color: c.textFaint, borderBottom: `0.5px solid ${c.border}`,
          }}
        >
          {panelCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>

        {/* Panel content */}
        <div style={{
          padding: '14px 12px', display: 'flex', flexDirection: 'column',
          gap: 16, overflowY: 'auto', flex: 1,
          opacity: panelCollapsed ? 0 : 1,
          transition: 'opacity 0.12s ease',
          pointerEvents: panelCollapsed ? 'none' : 'auto',
        }}>
          {/* Companies */}
          <div>
            <p style={{ fontSize: 11, color: c.textFaint, textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }}>
              Companies
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {documents.length === 0 ? (
                <span style={{ fontSize: 12, color: c.textFaint, fontStyle: 'italic' }}>No filings loaded</span>
              ) : (
                <>
                  <button
                    style={selectedDocIds.length === 0 ? pillActive : pillInactive}
                    onClick={() => setSelectedDocIds([])}
                  >
                    All
                  </button>
                  {documents.map(doc => (
                    <button
                      key={doc.id}
                      style={selectedDocIds.includes(doc.id) ? pillActive : pillInactive}
                      onClick={() => toggleDoc(doc.id)}
                      title={doc.name}
                    >
                      {doc.name.length > 12 ? doc.name.slice(0, 12) + '…' : doc.name}
                    </button>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Loaded filings list */}
          {documents.length > 0 && (
            <div>
              <p style={{ fontSize: 11, color: c.textFaint, textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }}>
                Loaded filings
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {documents.map(doc => (
                  <div
                    key={doc.id}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: c.textMuted }}
                  >
                    <FileText size={12} style={{ flexShrink: 0 }} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {doc.name}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Chat area ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: c.bg }}>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 20px 8px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {messages.map(msg => {
            const isUser = msg.role === 'user';
            const hasMetadata = !isUser && (
              (msg.retrievalPath && msg.retrievalPath !== 'none') ||
              (msg.sources && msg.sources.length > 0)
            );
            return (
              <div key={msg.id} style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
                {/*
                  alignItems: flex-start — avatars and bubble tops align.
                  The FinchAvatar also sets alignSelf: flex-start as defence-in-depth
                  so no ancestor's alignItems can override the fixed circle size.
                */}
                <div style={{ display: 'flex', flexDirection: isUser ? 'row-reverse' : 'row', alignItems: 'flex-start', gap: AVATAR_GAP, maxWidth: '85%' }}>

                  {/* Avatar */}
                  {isUser ? (
                    <div
                      style={{
                        width: 26, height: 26,
                        minWidth: 26, minHeight: 26,
                        borderRadius: '50%',
                        flexShrink: 0,
                        alignSelf: 'flex-start',
                        background: c.brandDeep,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      <User size={13} color={c.onBrand} />
                    </div>
                  ) : (
                    <FinchAvatar />
                  )}

                  {/* Bubble */}
                  <div
                    style={{
                      padding: isUser ? '9px 13px' : '11px 15px',
                      borderRadius: 11,
                      ...(isUser
                        ? {
                            background: c.brandTint,
                            color: c.brandDeep,
                            borderBottomRightRadius: 3,
                          }
                        : {
                            background: c.surface,
                            color: c.text,
                            borderBottomLeftRadius: 3,
                            maxWidth: '68ch',
                            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                          }
                      ),
                      fontSize: 13,
                      lineHeight: 1.6,
                      ...(isUser ? { whiteSpace: 'pre-wrap', fontFamily: font.ui } : {}),
                    }}
                  >
                    {/* Answer body */}
                    {isUser
                      ? msg.text
                      : renderChatMarkdown(msg.text)
                    }

                    {/* Source metadata — visually separated from answer body */}
                    {hasMetadata && (
                      <div
                        style={{
                          marginTop: 10,
                          paddingTop: 8,
                          borderTop: `0.5px solid ${c.border}`,
                        }}
                      >
                        {/* Retrieval path badge */}
                        {msg.retrievalPath && msg.retrievalPath !== 'none' && (
                          <div style={{ marginBottom: msg.sources && msg.sources.length > 0 ? 6 : 0 }}>
                            <span style={pathBadge(msg.retrievalPath)}>
                              {msg.retrievalPath === 'graph'
                                ? '◉ financial data'
                                : msg.retrievalPath === 'both'
                                ? '◉ financial data + filing text'
                                : msg.retrievalPath === 'vector_no_graph'
                                ? '◎ filing text · graph data not loaded'
                                : '◉ filing text'}
                            </span>
                          </div>
                        )}

                        {/* Source citation chips */}
                        {msg.sources && msg.sources.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                            {msg.sources.map((s, i) => (
                              <span key={`${s.source}-${s.chunk_index}-${i}`} style={sourceTag} title={s.source}>
                                {s.ticker} {s.form} · #{s.chunk_index}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Timestamp */}
                    <p style={{ fontSize: 10, color: isUser ? c.textMuted : c.textFaint, margin: '6px 0 0', textAlign: isUser ? 'right' : 'left', fontFamily: font.ui }}>
                      {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}

          {/* ── Empty state: starter chips ── */}
          {messages.length === 1 && !isLoading && (
            <div style={{ paddingLeft: BUBBLE_INDENT, marginTop: 6 }}>

              {/* Suggested question chips */}
              <p style={{ fontSize: 11, color: c.textFaint, margin: '0 0 10px', fontFamily: font.ui, letterSpacing: '0.03em', textTransform: 'uppercase' }}>
                Suggested questions
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7, maxWidth: 460 }}>
                {starterChips.map((chip, i) => (
                  <button
                    key={i}
                    onMouseEnter={() => setHoveredChip(i)}
                    onMouseLeave={() => setHoveredChip(null)}
                    onClick={() => { setHoveredChip(null); sendMessage(chip); }}
                    style={{
                      padding: '8px 14px',
                      borderRadius: 8,
                      border: `1px solid ${hoveredChip === i ? c.brand : c.border}`,
                      background: hoveredChip === i ? c.brandTint : c.bg,
                      color: hoveredChip === i ? c.brand : c.text2,
                      fontSize: 13,
                      fontFamily: font.ui,
                      cursor: 'pointer',
                      textAlign: 'left',
                      lineHeight: 1.4,
                      transition: 'border-color 0.12s, background 0.12s, color 0.12s',
                    }}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Loading indicator */}
          {isLoading && (
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: AVATAR_GAP }}>
              <FinchAvatar />
              <div style={{ padding: '10px 14px', borderRadius: 11, borderBottomLeftRadius: 3, background: c.surface, display: 'flex', alignItems: 'center', gap: 8, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
                <Loader2 size={14} color={c.brand} style={{ animation: 'spin 1s linear infinite' }} />
                <span style={{ fontSize: 13, color: c.textMuted, fontFamily: font.ui }}>Searching filings…</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* ── Input bar ── */}
        <div style={{
          padding: '12px 16px 13px',
          borderTop: `1px solid ${c.border}`,
          background: c.surface,
        }}>
          {/* Combined textarea + send button in one bordered container */}
          <div style={{
            display: 'flex',
            alignItems: 'flex-end',
            background: c.bg,
            border: `1.5px solid ${inputFocused ? c.brand : c.border}`,
            borderRadius: 10,
            transition: 'border-color 0.15s',
            overflow: 'hidden',
          }}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => setInputFocused(true)}
              onBlur={() => setInputFocused(false)}
              placeholder="Ask about revenue, risks, guidance…"
              rows={1}
              style={{
                flex: 1,
                padding: '10px 12px',
                fontSize: 13,
                border: 'none',
                outline: 'none',
                resize: 'none',
                fontFamily: font.ui,
                color: c.text,
                background: 'transparent',
                lineHeight: 1.5,
                height: 40,
                overflowY: 'hidden',
              }}
            />
            <div style={{ padding: '5px 6px 5px 0' }}>
              <button
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                style={{
                  width: 34, height: 34, flexShrink: 0,
                  borderRadius: 7, border: 'none',
                  cursor: input.trim() && !isLoading ? 'pointer' : 'not-allowed',
                  background: input.trim() && !isLoading ? c.brandDeep : c.surfaceAlt,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => { if (input.trim() && !isLoading) e.currentTarget.style.background = c.brandDeepHover; }}
                onMouseLeave={e => { e.currentTarget.style.background = input.trim() && !isLoading ? c.brandDeep : c.surfaceAlt; }}
              >
                <Send size={14} color={input.trim() && !isLoading ? c.onBrand : c.textFaint} />
              </button>
            </div>
          </div>
          <p style={{ fontSize: 11, color: c.textFaint, textAlign: 'center', margin: '7px 0 0', fontFamily: font.ui }}>
            AI responses are grounded in your loaded filings — always verify key figures.
          </p>
        </div>

      </div>
    </div>
  );
};

export default ChatInterface;
