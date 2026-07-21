import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, AlertTriangle } from 'lucide-react';
import { Document, ChatMessage } from '../types';
import { askFinSightStream } from '../services/gemini';
import { c, font } from '../theme';
import { companyLabel } from '../utils/company';
import { useIsMobile } from '../utils/hooks';
import { GroundedAnswer } from '../utils/chatRender';
import BirdLoader from './BirdLoader';

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

// The "fetching an answer" indicator is the shared <BirdLoader variant="full">
// (see components/BirdLoader.tsx) — one source of truth for the flying gull,
// reused per-widget on the Dashboard.

// ── component ────────────────────────────────────────────────────────────────

const ChatInterface: React.FC<ChatInterfaceProps> = ({ documents }) => {
  const isMobile = useIsMobile();
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
  // A11y: the streaming bubble is NOT a live region (that would announce every
  // token). Instead we push the COMPLETED answer here once, so a screen reader
  // announces the finished reply a single time.
  const [announcement, setAnnouncement]     = useState('');

  const scrollRef   = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Whether the thread is pinned to the bottom. Starts true; scrolling away from
  // the bottom disables auto-stick (so the user can read history while a reply
  // arrives), and scrolling back to the bottom re-enables it.
  const stickToBottomRef = useRef(true);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  // Auto-scroll to the newest message/loader — but only when pinned to bottom.
  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [messages, isLoading]);

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
    // Bird = pre-generation phase (keyword routing + graph/vector retrieval).
    // It stays up until the FIRST token arrives, then we swap to streaming text.
    setIsLoading(true);

    const assistantId = `a-${Date.now()}`;
    let started = false;   // has the assistant bubble been inserted yet?
    let acc = '';          // accumulated streamed text

    // Insert the (empty) streaming assistant bubble on the first token, hiding
    // the bird. Guarded so it runs exactly once.
    const ensureStarted = () => {
      if (started) return;
      started = true;
      setIsLoading(false);
      setMessages(prev => [...prev, {
        id: assistantId,
        role: 'assistant',
        text: '',
        streaming: true,
        timestamp: new Date(),
      }]);
    };

    const patch = (updates: Partial<ChatMessage>) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? { ...m, ...updates } : m)));

    // Scope retrieval to the user's LOADED companies so vector search can't
    // surface arbitrary corpus companies (the "Charter/Verizon for a NVDA/AAPL
    // question" bug). An explicit doc selection narrows further; empty selection
    // ("All") scopes to every loaded doc. The backend treats this ticker list as
    // an authoritative `ticker IN (...)` filter, and the graph→vector fallback
    // inherits the same scope, so a graph miss can no longer widen to the corpus.
    const selected  = documents.filter(d => selectedDocIds.includes(d.id));
    const scopeDocs = selected.length > 0 ? selected : documents;
    const tickers   = Array.from(new Set(scopeDocs.map(d => d.ticker).filter((t): t is string => Boolean(t))));
    const forms     = Array.from(new Set(scopeDocs.map(d => d.form).filter((f): f is '10-K' => Boolean(f))));
    const form      = forms.length === 1 ? forms[0] : undefined;

    await askFinSightStream(text, { tickers: tickers.length ? tickers : undefined, form, k: 6 }, {
      onToken: (delta) => {
        ensureStarted();
        acc += delta;
        patch({ text: acc });
      },
      onDone: ({ sources, validCitations, retrievalPath }) => {
        ensureStarted();
        patch({ text: acc, sources, validCitations, retrievalPath, streaming: false });
        // Announce the finished answer once (see `announcement` a11y note).
        setAnnouncement(acc);
      },
      onError: (message) => {
        if (!started) {
          // Failed before any token — show a standalone error bubble.
          started = true;
          setIsLoading(false);
          setMessages(prev => [...prev, {
            id: assistantId,
            role: 'assistant',
            text: acc || `Error: ${message}`,
            streaming: false,
            error: true,
            timestamp: new Date(),
          }]);
        } else {
          // Mid-stream failure: keep the partial text, flag the error.
          patch({ text: acc, streaming: false, error: true });
        }
      },
    });

    // Safety net: if the stream returned without ever starting (shouldn't
    // happen — the backend always emits at least one text token), clear the bird.
    if (!started) setIsLoading(false);
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

  const AVATAR_GAP = 8;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: c.bg, ...fs }}>

      {/* Visually-hidden polite live region: announces each COMPLETED answer
          once (not per token — that would spam assistive tech during streaming). */}
      <div
        aria-live="polite"
        aria-atomic="true"
        style={{ position: 'absolute', width: 1, height: 1, margin: -1, padding: 0, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0 }}
      >
        {announcement}
      </div>

      {/* ── Filter chips — relocated from the old inner Companies panel. Same
          selectedDocIds state/logic (empty selection = "All"); the duplicate
          "Loaded filings" list is dropped since the main sidebar already lists them. */}
      {documents.length > 0 && (
        <div style={{ borderBottom: `0.5px solid ${c.border}`, padding: '10px 20px', flexShrink: 0 }}>
          <div style={{ maxWidth: 700, margin: '0 auto', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
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
          </div>
        </div>
      )}

      {/* ── Chat area ──
          minHeight: 0 is the actual scroll fix: without it this flex child's
          min-height resolves to its content size, so it never shrinks and the
          inner overflow-y:auto can't engage. */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>

        {/* Messages — the only scroll container; centered ~700px reading column */}
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '20px 20px 8px' }}
        >
          <div style={{ maxWidth: 700, margin: '0 auto', width: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {messages.map(msg => {
            const isUser = msg.role === 'user';
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
                    {/* Answer body + (at completion) retrieval badge and the
                        numbered, inspectable reference list. During streaming a
                        blinking caret trails the text; citations resolve once the
                        stream finishes, so the reference list appends below with
                        no reflow of the text above. */}
                    {isUser
                      ? msg.text
                      : (
                          <GroundedAnswer
                            text={msg.text}
                            streaming={msg.streaming}
                            retrievalPath={msg.retrievalPath}
                            sources={msg.sources}
                            validCitations={msg.validCitations}
                          />
                        )
                    }

                    {/* Mid-stream failure — keep the partial text above, flag it. */}
                    {!isUser && msg.error && (
                      <p role="alert" style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '8px 0 0', fontSize: 12, color: c.neg }}>
                        <AlertTriangle size={13} style={{ flexShrink: 0 }} />
                        The response was interrupted. Please try asking again.
                      </p>
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

          {/* ── Empty state: starter chips — 2×2 grid of equal-width cards
              (single column below 640px, see .chat-suggest-grid in index.html) ── */}
          {messages.length === 1 && !isLoading && (
            <div style={{ marginTop: 6 }}>

              {/* Suggested question chips */}
              <p style={{ fontSize: 11, color: c.textFaint, margin: '0 0 10px', fontFamily: font.ui, letterSpacing: '0.03em', textTransform: 'uppercase' }}>
                Suggested questions
              </p>
              <div className="chat-suggest-grid">
                {starterChips.map((chip, i) => (
                  <button
                    key={i}
                    onMouseEnter={() => setHoveredChip(i)}
                    onMouseLeave={() => setHoveredChip(null)}
                    onClick={() => { setHoveredChip(null); sendMessage(chip); }}
                    style={{
                      padding: isMobile ? '11px 14px' : '8px 14px',
                      minHeight: isMobile ? 44 : undefined,
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

          {/* Loading indicator — flying-bird "fetching an answer", styled as a
              normal assistant reply bubble. Shown only while awaiting the
              response; replaced by the answer message on completion. */}
          {isLoading && (
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: AVATAR_GAP }}>
              <FinchAvatar />
              <div style={{ padding: '10px 14px', borderRadius: 11, borderBottomLeftRadius: 3, background: c.surface, display: 'flex', alignItems: 'center', boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
                <BirdLoader variant="full" label="Fetching an answer…" ariaLabel="FinChat is fetching an answer" />
              </div>
            </div>
          )}

          </div>
        </div>

        {/* ── Input bar — inner content constrained to the same ~700px column.
            The bottom padding adds env(safe-area-inset-bottom) so on iOS the
            composer clears the home-indicator bar (0 on non-notched devices). ── */}
        <div style={{
          padding: '12px 16px calc(13px + env(safe-area-inset-bottom))',
          borderTop: `1px solid ${c.border}`,
          background: c.surface,
          flexShrink: 0,
        }}>
          <div style={{ maxWidth: 700, margin: '0 auto' }}>
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
                height: isMobile ? 44 : 40,
                overflowY: 'hidden',
              }}
            />
            <div style={{ padding: '5px 6px 5px 0' }}>
              <button
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                aria-label="Send message"
                style={{
                  width: isMobile ? 44 : 34, height: isMobile ? 44 : 34, flexShrink: 0,
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
    </div>
  );
};

export default ChatInterface;
