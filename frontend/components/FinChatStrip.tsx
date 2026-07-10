import React, { useEffect, useState } from 'react';
import { MessageSquare, Send, Loader2, Info } from 'lucide-react';
import { c, font } from '../theme';
import { askFinSight, fetchIndexedStatus, ChatResult } from '../services/gemini';
import { renderChatMarkdown, AnswerMeta } from '../utils/chatRender';

interface FinChatStripProps {
  anchor: string;
  peer: string;
}

const FF = font.ui;
const cardStyle: React.CSSProperties = {
  background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px', marginTop: 18,
};

// Single-shot FinChat scoped to the two companies on screen. GATED ON /indexed
// ONLY: chat answers come from the vector path over FilingChunks, so a company
// with metrics/price but no completed IngestManifest can't be answered about.
// When both are indexed the input is live; otherwise it's replaced by a passive
// note naming the specific missing ticker(s) and pointing at the Documents page.
// We deliberately do NOT offer a one-click ingest here: /compare/:a/:p is a
// shareable URL, and an ingest button on it would let a shared link burn the
// daily embedding budget. Ingest stays on Documents, where a company was chosen.
const FinChatStrip: React.FC<FinChatStripProps> = ({ anchor, peer }) => {
  const [indexed, setIndexed]   = useState<Record<string, boolean> | null>(null);
  const [input, setInput]       = useState('');
  const [asking, setAsking]     = useState(false);
  const [answer, setAnswer]     = useState<ChatResult | null>(null);
  const [askError, setAskError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIndexed(null);
    setAnswer(null);
    setAskError(null);
    setInput('');
    fetchIndexedStatus([anchor, peer]).then(res => { if (!cancelled) setIndexed(res); });
    return () => { cancelled = true; };
  }, [anchor, peer]);

  const bothIndexed = !!indexed && !!indexed[anchor] && !!indexed[peer];
  const missing = indexed ? [anchor, peer].filter(t => !indexed[t]) : [];

  const send = async () => {
    const q = input.trim();
    if (!q || asking || !bothIndexed) return;
    setAsking(true);
    setAskError(null);
    setAnswer(null);
    try {
      // ALWAYS send [anchor, peer]: a pair question that names neither company
      // ("which has better margins?") must still be confined to these two, not
      // fall to a global search over the whole corpus.
      const res = await askFinSight(q, { tickers: [anchor, peer], k: 6 });
      setAnswer(res);
    } catch (e) {
      setAskError(e instanceof Error ? e.message : 'Failed to get an answer.');
    } finally {
      setAsking(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <div style={cardStyle}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <MessageSquare size={15} color={c.brand} />
        <span style={{ fontSize: 13, fontWeight: 600, color: c.text }}>Ask FinChat</span>
        <span style={{ fontSize: 12, color: c.textMuted }}>
          about <span style={{ color: c.brandDeep, fontWeight: 600 }}>{anchor}</span>
          {' '}vs <span style={{ color: c.accentFg, fontWeight: 600 }}>{peer}</span>
        </span>
      </div>

      {indexed === null ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: c.textMuted, fontSize: 13 }}>
          <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Checking index status…
        </div>
      ) : !bothIndexed ? (
        // Passive gate — names the specific missing ticker(s), points at Documents.
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 12px', background: c.surfaceAlt, borderRadius: 8, color: c.textMuted, fontSize: 13, lineHeight: 1.55 }}>
          <Info size={15} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            FinChat needs{' '}
            {missing.length === 2 ? (
              <>
                <strong style={{ color: c.text }}>{missing[0]}</strong> and{' '}
                <strong style={{ color: c.text }}>{missing[1]}</strong>
              </>
            ) : (
              <strong style={{ color: c.text }}>{missing[0]}</strong>
            )}{' '}
            indexed to answer about {missing.length === 2 ? 'them' : 'it'}. Add{' '}
            {missing.length === 2 ? 'them' : 'it'} from the <strong style={{ color: c.text }}>Documents</strong> page
            to enable chat here — the metrics and price comparison above don’t require indexing.
          </span>
        </div>
      ) : (
        <>
          {/* Input row */}
          <div style={{ display: 'flex', alignItems: 'flex-end', background: c.bg, border: `1.5px solid ${c.border}`, borderRadius: 10, overflow: 'hidden' }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={`Ask about ${anchor} vs ${peer} — margins, risks, strategy…`}
              rows={1}
              aria-label={`Ask FinChat about ${anchor} versus ${peer}`}
              style={{ flex: 1, padding: '10px 12px', fontSize: 13, border: 'none', outline: 'none', resize: 'none', fontFamily: FF, color: c.text, background: 'transparent', lineHeight: 1.5, height: 40 }}
            />
            <div style={{ padding: '5px 6px 5px 0' }}>
              <button
                onClick={send}
                disabled={!input.trim() || asking}
                aria-label="Send"
                style={{
                  width: 34, height: 34, borderRadius: 7, border: 'none',
                  cursor: input.trim() && !asking ? 'pointer' : 'not-allowed',
                  background: input.trim() && !asking ? c.brandDeep : c.surfaceAlt,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                {asking
                  ? <Loader2 size={14} color={c.onBrand} style={{ animation: 'spin 1s linear infinite' }} />
                  : <Send size={14} color={input.trim() && !asking ? c.onBrand : c.textFaint} />}
              </button>
            </div>
          </div>

          {/* Answer / loading / error (single-shot) */}
          {asking && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, color: c.textMuted, fontSize: 13 }}>
              <Loader2 size={14} color={c.brand} style={{ animation: 'spin 1s linear infinite' }} /> Searching filings…
            </div>
          )}
          {askError && !asking && (
            <p style={{ marginTop: 12, fontSize: 13, color: c.neg }}>Error: {askError}</p>
          )}
          {answer && !asking && (
            <div style={{ marginTop: 12, padding: '12px 14px', background: c.surface, borderRadius: 10, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
              {answer.answer
                ? renderChatMarkdown(answer.answer)
                : <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>No answer was returned.</p>}
              <AnswerMeta retrievalPath={answer.retrievalPath} sources={answer.sources} />
            </div>
          )}

          <p style={{ fontSize: 11, color: c.textFaint, margin: '8px 0 0' }}>
            Grounded in indexed filings for {anchor} and {peer} — always verify key figures.
          </p>
        </>
      )}
    </div>
  );
};

export default FinChatStrip;
