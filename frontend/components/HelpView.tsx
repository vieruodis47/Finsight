import React, { useState } from 'react';
import {
  HelpCircle, MessageCircle, FileText, BarChart2,
  CheckCircle, XCircle, ChevronDown, ChevronRight,
  Lightbulb, AlertTriangle,
} from 'lucide-react';
import { c, font } from '../theme';

const FF = font.ui;

const GOOD_QUESTIONS = [
  { q: '"What was Gap Inc.\'s gross margin in FY2024?"',                        why: 'Specific company, specific metric, specific year.' },
  { q: '"What risks did PVH flag related to inventory in their FY2024 10-K?"',  why: 'Names the document type and a concrete topic.' },
  { q: '"How did Gap\'s operating income change from FY2023 to FY2024?"',       why: 'Year-over-year comparison with clear scope.' },
  { q: '"What guidance did AEO\'s management give for FY2025 revenue?"',        why: 'Targets the MD&A section specifically.' },
  { q: '"Compare Gap and PVH\'s debt-to-equity ratio in FY2024."',             why: 'Multi-company but bounded to one metric and one year.' },
];

const BAD_QUESTIONS = [
  { q: '"How is the company doing?"',         fix: 'Which company? Which metric? Which year?' },
  { q: '"Tell me everything about Gap."',     fix: 'Too broad — ask about one section or metric at a time.' },
  { q: '"What will the stock price be?"',     fix: 'FinSight analyzes filings, not future prices.' },
  { q: '"Is this a good investment?"',        fix: "Investment advice isn't in the filings — ask about specific financials instead." },
  { q: '"What happened in the news today?"',  fix: 'FinSight uses uploaded filings, not live news feeds.' },
];

const TIPS = [
  { icon: <FileText size={15} />,     title: 'Name the company and year',        body: 'Always include the ticker or company name and the fiscal year — e.g. "Gap FY2024" not just "the company".' },
  { icon: <BarChart2 size={15} />,    title: 'Name the metric',                  body: 'Ask about one specific number — revenue, gross margin, inventory turnover — rather than a general overview.' },
  { icon: <MessageCircle size={15} />, title: 'Name the document section',       body: 'Saying "in the MD&A" or "in the Risk Factors section" helps the AI find the right chunk faster.' },
  { icon: <Lightbulb size={15} />,    title: 'Ask for comparisons explicitly',   body: 'For peer or YoY comparisons, say so — "compare Gap and PVH" or "FY2023 vs FY2024".' },
];

const FAQS = [
  {
    q: "Why does the AI sometimes say it doesn't know?",
    a: "FinSight only answers from the documents you've uploaded. If a filing isn't loaded, or the answer isn't in the text, it will say so rather than guess.",
  },
  {
    q: 'How many documents should I load at once?',
    a: 'Start with 2–3 filings for the best results. Loading too many at once can dilute the context the AI uses to answer your question.',
  },
  {
    q: 'What document types work best?',
    a: 'Annual 10-K filings give the most complete picture. Earnings transcripts work well for guidance and management commentary.',
  },
  {
    q: 'Can I compare two different companies?',
    a: 'Yes — load both companies\' filings, then ask "Compare [Company A] and [Company B]\'s gross margin in FY2024." The Analysis tab also has a dedicated Compare Documents mode.',
  },
  {
    q: 'Why does the AI get numbers slightly wrong sometimes?',
    a: 'Financial tables in PDFs can be tricky to extract perfectly. Always cross-check key figures against the original filing. Citation chips show you exactly which section the answer came from.',
  },
];

const FaqItem: React.FC<{ q: string; a: string }> = ({ q, a }) => {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: `0.5px solid ${c.border}`, padding: '12px 0' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          width: '100%', background: 'none', border: 'none', cursor: 'pointer',
          padding: 0, textAlign: 'left', gap: 12, fontFamily: FF,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 500, color: c.text }}>{q}</span>
        {open
          ? <ChevronDown  size={15} color={c.textFaint} style={{ flexShrink: 0 }} />
          : <ChevronRight size={15} color={c.textFaint} style={{ flexShrink: 0 }} />
        }
      </button>
      {open && (
        <p style={{ fontSize: 13, color: c.textMuted, lineHeight: 1.7, margin: '10px 0 0', paddingRight: 24 }}>
          {a}
        </p>
      )}
    </div>
  );
};

const HelpView: React.FC = () => {
  const [triedQ, setTriedQ]     = useState('');
  const [feedback, setFeedback] = useState<string | null>(null);

  const checkQuestion = () => {
    const q = triedQ.trim().toLowerCase();
    if (!q) return;
    const issues: string[] = [];
    const hasCompany = /gap|pvh|aeo|american eagle|inditex|h&m|gps/.test(q);
    const hasYear    = /fy20|20\d\d|fiscal/.test(q);
    const hasMetric  = /revenue|margin|income|profit|debt|cash|inventory|turnover|eps|ebitda|guidance|risk|growth/.test(q);
    if (!hasCompany) issues.push('• Mention a specific company (e.g. Gap, PVH, AEO)');
    if (!hasYear)    issues.push('• Include a fiscal year (e.g. FY2024)');
    if (!hasMetric)  issues.push('• Name a specific metric or topic (e.g. gross margin, risk factors)');
    setFeedback(
      issues.length === 0
        ? 'Looks good! This question is specific enough for FinSight to answer well.'
        : 'This question could be more specific:\n' + issues.join('\n')
    );
  };

  const isGood = feedback?.startsWith('Looks good');

  return (
    <div style={{ padding: 22, height: '100%', overflowY: 'auto', fontFamily: FF, background: c.bg }}>

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <div style={{ width: 30, height: 30, borderRadius: 7, background: c.brandTint, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <HelpCircle size={16} color={c.brand} />
          </div>
          <p style={{ fontSize: 15, fontWeight: 500, color: c.text, margin: 0 }}>Help & guidance</p>
        </div>
        <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>
          How to get the best answers from FinSight's AI.
        </p>
      </div>

      {/* Question checker */}
      <div style={{ background: c.surface, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px', marginBottom: 20 }}>
        <p style={{ fontSize: 13, fontWeight: 500, color: c.text, margin: '0 0 4px' }}>
          Test your question
        </p>
        <p style={{ fontSize: 12, color: c.textMuted, margin: '0 0 12px' }}>
          Paste a question below and we'll check if it's specific enough for the AI to answer well.
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            type="text"
            value={triedQ}
            onChange={e => { setTriedQ(e.target.value); setFeedback(null); }}
            onKeyDown={e => e.key === 'Enter' && checkQuestion()}
            onFocus={e => { e.currentTarget.style.borderColor = c.brand; }}
            onBlur={e  => { e.currentTarget.style.borderColor = c.border; }}
            placeholder={`e.g. "What was Gap's gross margin in FY2024?"`}
            style={{
              flex: 1, fontSize: 13, padding: '8px 12px',
              border: `0.5px solid ${c.border}`, borderRadius: 7,
              outline: 'none', fontFamily: FF, color: c.text, background: c.bg,
            }}
          />
          <button
            onClick={checkQuestion}
            disabled={!triedQ.trim()}
            style={{
              padding: '8px 16px', borderRadius: 7, fontSize: 13, fontWeight: 500,
              background: triedQ.trim() ? c.brandDeep : c.border,
              color:      triedQ.trim() ? c.onBrand  : c.textFaint,
              border: 'none', cursor: triedQ.trim() ? 'pointer' : 'not-allowed',
              fontFamily: FF, flexShrink: 0,
            }}
          >
            Check
          </button>
        </div>

        {feedback && (
          <div style={{
            marginTop: 10, padding: '10px 12px', borderRadius: 7,
            background: isGood ? c.posSurface : c.warnSurface,
            border: `0.5px solid ${isGood ? c.posBorder : c.warnBorder}`,
            display: 'flex', gap: 8, alignItems: 'flex-start',
          }}>
            {isGood
              ? <CheckCircle  size={15} color={c.pos} style={{ flexShrink: 0, marginTop: 1 }} />
              : <AlertTriangle size={15} color={c.warnFg} style={{ flexShrink: 0, marginTop: 1 }} />
            }
            <p style={{ fontSize: 12, color: isGood ? c.pos : c.warnFg, margin: 0, lineHeight: 1.65, whiteSpace: 'pre-line' }}>
              {feedback}
            </p>
          </div>
        )}
      </div>

      {/* Good vs bad questions */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 20 }}>

        <div style={{ border: `0.5px solid ${c.border}`, borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ padding: '11px 14px', borderBottom: `0.5px solid ${c.border}`, background: c.posSurface, display: 'flex', alignItems: 'center', gap: 7 }}>
            <CheckCircle size={14} color={c.pos} />
            <p style={{ fontSize: 12, fontWeight: 500, color: c.pos, margin: 0 }}>Questions that work well</p>
          </div>
          <div style={{ padding: '8px 0' }}>
            {GOOD_QUESTIONS.map(({ q, why }, i) => (
              <div key={i} style={{ padding: '8px 14px', borderBottom: i < GOOD_QUESTIONS.length - 1 ? `0.5px solid ${c.borderFaint}` : 'none' }}>
                <p style={{ fontSize: 12, color: c.text, margin: '0 0 2px', fontStyle: 'italic' }}>{q}</p>
                <p style={{ fontSize: 11, color: c.textFaint, margin: 0 }}>{why}</p>
              </div>
            ))}
          </div>
        </div>

        <div style={{ border: `0.5px solid ${c.border}`, borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ padding: '11px 14px', borderBottom: `0.5px solid ${c.border}`, background: c.negSurface, display: 'flex', alignItems: 'center', gap: 7 }}>
            <XCircle size={14} color={c.neg} />
            <p style={{ fontSize: 12, fontWeight: 500, color: c.neg, margin: 0 }}>Questions that are too vague</p>
          </div>
          <div style={{ padding: '8px 0' }}>
            {BAD_QUESTIONS.map(({ q, fix }, i) => (
              <div key={i} style={{ padding: '8px 14px', borderBottom: i < BAD_QUESTIONS.length - 1 ? `0.5px solid ${c.borderFaint}` : 'none' }}>
                <p style={{ fontSize: 12, color: c.text, margin: '0 0 2px', fontStyle: 'italic' }}>{q}</p>
                <p style={{ fontSize: 11, color: c.textFaint, margin: 0 }}>→ {fix}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Tips */}
      <div style={{ border: `0.5px solid ${c.border}`, borderRadius: 10, overflow: 'hidden', marginBottom: 20 }}>
        <div style={{ padding: '11px 14px', borderBottom: `0.5px solid ${c.border}`, background: c.surface }}>
          <p style={{ fontSize: 12, fontWeight: 500, color: c.text2, margin: 0 }}>4 tips for better answers</p>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
          {TIPS.map(({ icon, title, body }, i) => (
            <div
              key={i}
              style={{
                padding: '14px 16px',
                borderRight:  i % 2 === 0 ? `0.5px solid ${c.border}` : 'none',
                borderBottom: i < 2       ? `0.5px solid ${c.border}` : 'none',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
                <span style={{ color: c.accentFg }}>{icon}</span>
                <p style={{ fontSize: 12, fontWeight: 500, color: c.text, margin: 0 }}>{title}</p>
              </div>
              <p style={{ fontSize: 12, color: c.textMuted, margin: 0, lineHeight: 1.6 }}>{body}</p>
            </div>
          ))}
        </div>
      </div>

      {/* FAQ */}
      <div style={{ border: `0.5px solid ${c.border}`, borderRadius: 10, overflow: 'hidden' }}>
        <div style={{ padding: '11px 14px', borderBottom: `0.5px solid ${c.border}`, background: c.surface }}>
          <p style={{ fontSize: 12, fontWeight: 500, color: c.text2, margin: 0 }}>Frequently asked questions</p>
        </div>
        <div style={{ padding: '4px 16px 8px' }}>
          {FAQS.map((faq, i) => <FaqItem key={i} {...faq} />)}
        </div>
      </div>

    </div>
  );
};

export default HelpView;