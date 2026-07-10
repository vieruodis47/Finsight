import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, Search, Loader2, AlertCircle } from 'lucide-react';
import { c, font } from '../theme';
import { useOnClickOutside } from '../utils/hooks';
import { fmtM, fmtPct, fmtRatio } from '../utils/format';
import { fetchCompareMetrics, CompareMetricsResult, ComparePoint } from '../services/gemini';
import PeerPicker from './PeerPicker';
import PriceCompareChart from './PriceCompareChart';

interface CompareViewProps {
  anchor: string;
  peer: string;
  // Stable cycle array (sidebar order, anchor removed, deep-linked peer at the
  // tail) — always contains `peer`. Built in App so ordering is deterministic.
  peers: string[];
  onBack: () => void;
  onSelectPeer: (peer: string) => void;
}

// ── Metric config ───────────────────────────────────────────────────────────

type MetricKey =
  | 'revenue' | 'net_income' | 'free_cash_flow'
  | 'gross_margin_pct' | 'operating_margin_pct' | 'net_margin_pct'
  | 'revenue_growth_pct' | 'debt_to_equity' | 'current_ratio';

// dir: how a two-company comparison is scored.
//   scale  — an absolute-size figure; bigger ≠ better, so no relative winner.
//   higher — higher value wins.  lower — lower value wins (inverted).
// allowNegativeSignal: whether a NEGATIVE value is unfavorable on its own terms
// (a net loss, negative free cash flow), flagged c.neg/▼ before any head-to-head.
// Required (not optional) and orthogonal to `dir` — FCF is `higher` AND signed —
// so every row must state it explicitly. This is what keeps the two 'scale'
// behaviours honest (revenue can't go negative → false; net_income can → true)
// and forces a new row to decide rather than silently inherit or miss the check.
// Margins/growth CAN go negative but are left relative-only by product choice —
// now visible here as `false`, not buried in a comment.
type Dir = 'scale' | 'higher' | 'lower';
interface MetricDef {
  key: MetricKey;
  label: string;
  fmt: (v: number | null | undefined) => string;
  dir: Dir;
  allowNegativeSignal: boolean;
}

const METRIC_ROWS: MetricDef[] = [
  { key: 'revenue',              label: 'Revenue',          fmt: fmtM,     dir: 'scale',  allowNegativeSignal: false },
  { key: 'net_income',           label: 'Net Income',       fmt: fmtM,     dir: 'scale',  allowNegativeSignal: true  },
  { key: 'free_cash_flow',       label: 'Free Cash Flow',   fmt: fmtM,     dir: 'higher', allowNegativeSignal: true  },
  { key: 'gross_margin_pct',     label: 'Gross Margin',     fmt: fmtPct,   dir: 'higher', allowNegativeSignal: false },
  { key: 'operating_margin_pct', label: 'Operating Margin', fmt: fmtPct,   dir: 'higher', allowNegativeSignal: false },
  { key: 'net_margin_pct',       label: 'Net Margin',       fmt: fmtPct,   dir: 'higher', allowNegativeSignal: false },
  { key: 'revenue_growth_pct',   label: 'Revenue Growth',   fmt: fmtPct,   dir: 'higher', allowNegativeSignal: false },
  { key: 'debt_to_equity',       label: 'Debt-to-Equity',   fmt: fmtRatio, dir: 'lower',  allowNegativeSignal: false },
  { key: 'current_ratio',        label: 'Current Ratio',    fmt: fmtRatio, dir: 'higher', allowNegativeSignal: false },
];

interface CellStyle { text: string; color: string; weight: number; arrow: '' | '▲' | '▼'; }

// Tone for one company's value in a metric row. Branch order IS the contract:
//   1. null                       → neutral, no arrow; never enters a comparison
//                                    (a missing value is never coerced to 0)
//   2. negative + allowNegative   → c.neg / ▼ on its own terms; checked BEFORE
//                                    any head-to-head, so it fires even when the
//                                    peer value is null
//   3. scale                      → bold neutral (bigger ≠ better; no winner)
//   4. directional, peer missing  → neutral; a present value is NOT favorable
//                                    just because the other side is absent
//   5. directional, both present  → c.pos / ▲ only when STRICTLY better
function toneFor(value: number | null, other: number | null, def: MetricDef): CellStyle {
  const text = def.fmt(value);
  if (value == null) return { text, color: c.textFaint, weight: 400, arrow: '' };
  if (def.allowNegativeSignal && value < 0) return { text, color: c.neg, weight: 600, arrow: '▼' };
  if (def.dir === 'scale') return { text, color: c.text, weight: 600, arrow: '' };
  if (other == null) return { text, color: c.text, weight: 500, arrow: '' };
  // The one and only inverted comparison: dir 'lower' (debt_to_equity) flips the
  // test so the smaller value wins; every other directional row is 'higher'.
  const better = def.dir === 'higher' ? value > other : value < other;
  return better
    ? { text, color: c.pos, weight: 600, arrow: '▲' }
    : { text, color: c.text, weight: 500, arrow: '' };
}

// ── Cards ────────────────────────────────────────────────────────────────────

const Card: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px', marginTop: 18 }}>
    {children}
  </div>
);

const ValueCell: React.FC<{ cell: CellStyle }> = ({ cell }) => (
  <span style={{ padding: '9px 0', borderTop: `0.5px solid ${c.borderFaint}`, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
    <span style={{ color: cell.color, fontWeight: cell.weight, fontSize: 13 }}>
      {cell.text}
      {cell.arrow && <span style={{ marginLeft: 4, fontSize: 11 }}>{cell.arrow}</span>}
    </span>
  </span>
);

const KeyMetricsPanel: React.FC<{ data: CompareMetricsResult }> = ({ data }) => {
  const { a: ta, b: tb } = data.tickers;

  // Latest common fiscal year: the most recent revenue row with BOTH companies
  // reporting. Revenue is the base series every metric year derives from, so it
  // defines "this company has fiscal year Y".
  const commonYear = useMemo(() => {
    const rev = data.revenue;
    for (let i = rev.length - 1; i >= 0; i--) {
      if (rev[i].a != null && rev[i].b != null) return rev[i].year;
    }
    return null;
  }, [data]);

  if (!commonYear) {
    return (
      <Card>
        <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>
          No overlapping fiscal year with reported revenue for {ta} and {tb}.
        </p>
      </Card>
    );
  }

  const rowAt = (key: MetricKey): ComparePoint | undefined =>
    data[key].find(p => p.year === commonYear);

  const colHead: React.CSSProperties = { textAlign: 'right', fontSize: 13, fontWeight: 600, padding: '0 0 10px' };

  return (
    <Card>
      <p style={{ fontSize: 11, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 12px' }}>
        Key metrics · FY{commonYear}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(130px, 1fr) 1fr 1fr', alignItems: 'baseline' }}>
        <span />
        <span style={{ ...colHead, color: c.brandDeep }}>{ta}</span>
        <span style={{ ...colHead, color: c.accentFg }}>{tb}</span>

        {METRIC_ROWS.map(def => {
          const row = rowAt(def.key);
          const av = row?.a ?? null;
          const bv = row?.b ?? null;
          return (
            <React.Fragment key={def.key}>
              <span style={{ padding: '9px 0', borderTop: `0.5px solid ${c.borderFaint}`, color: c.textMuted, fontSize: 13 }}>
                {def.label}
              </span>
              <ValueCell cell={toneFor(av, bv, def)} />
              <ValueCell cell={toneFor(bv, av, def)} />
            </React.Fragment>
          );
        })}
      </div>
    </Card>
  );
};

// ── View ──────────────────────────────────────────────────────────────────────

// Nav controls for the comparison view. Three distinct controls, never merged:
//   1. "← {anchor}"     — back to the anchor's company view
//   2. "‹ {peer} ›"     — cycle the peer (only rendered at 3+ peers; below that
//                          chevrons would be dead/toggle, so we show just the
//                          name and rely on the picker)
//   3. peer picker      — search any SEC company; available at every peer count
// Below the nav: the key-metrics panel at the latest common fiscal year. The
// comparison is a pure XBRL read (fetchCompareMetrics) — works for any SEC pair,
// spends zero embedding quota. The normalized price chart lands in the next diff.
const CompareView: React.FC<CompareViewProps> = ({ anchor, peer, peers, onBack, onSelectPeer }) => {
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerWrapRef = useRef<HTMLDivElement>(null);
  useOnClickOutside(pickerWrapRef, () => setPickerOpen(false), pickerOpen);

  const [data, setData]       = useState<CompareMetricsResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    fetchCompareMetrics(anchor, peer)
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load comparison.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [anchor, peer]);

  const n = peers.length;
  const idx = Math.max(0, peers.indexOf(peer)); // peer is always in `peers`
  const showCycler = n >= 3;
  const prevPeer = n > 0 ? peers[(idx - 1 + n) % n] : peer;
  const nextPeer = n > 0 ? peers[(idx + 1) % n] : peer;

  const chevronBtn: React.CSSProperties = {
    width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
    borderRadius: 6, border: `0.5px solid ${c.border}`, background: c.bg,
    cursor: 'pointer', color: c.textMuted, padding: 0,
  };

  return (
    <div style={{ padding: 22, height: '100%', overflowY: 'auto', fontFamily: font.ui, boxSizing: 'border-box' }}>

      {/* ── Nav controls ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>

        {/* 1. Back to anchor */}
        <button
          onClick={onBack}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px 0 9px',
            borderRadius: 7, border: `0.5px solid ${c.border}`, background: c.bg,
            fontSize: 13, fontWeight: 500, color: c.text, cursor: 'pointer', fontFamily: font.ui,
          }}
          onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
          onMouseLeave={e => (e.currentTarget.style.background = c.bg)}
        >
          <ArrowLeft size={15} />
          {anchor}
        </button>

        <span style={{ fontSize: 13, color: c.textFaint }}>vs</span>

        {/* 2. Peer — cycler at 3+, otherwise a static name (peer = honey accent) */}
        {showCycler ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              aria-label="Previous peer"
              onClick={() => onSelectPeer(prevPeer)}
              style={chevronBtn}
              onMouseEnter={e => { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; }}
              onMouseLeave={e => { e.currentTarget.style.background = c.bg; e.currentTarget.style.color = c.textMuted; }}
            >
              <ChevronLeft size={16} />
            </button>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.accentFg, minWidth: 44, textAlign: 'center' }}>
              {peer}
            </span>
            <button
              aria-label="Next peer"
              onClick={() => onSelectPeer(nextPeer)}
              style={chevronBtn}
              onMouseEnter={e => { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; }}
              onMouseLeave={e => { e.currentTarget.style.background = c.bg; e.currentTarget.style.color = c.textMuted; }}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        ) : (
          <span style={{ fontSize: 14, fontWeight: 600, color: c.accentFg }}>{peer}</span>
        )}

        {/* 3. Peer picker — always available */}
        <div ref={pickerWrapRef} style={{ position: 'relative' }}>
          <button
            onClick={() => setPickerOpen(o => !o)}
            aria-haspopup="listbox"
            aria-expanded={pickerOpen}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px',
              borderRadius: 7, border: `0.5px solid ${c.border}`, background: pickerOpen ? c.hover : c.bg,
              fontSize: 13, color: c.textMuted, cursor: 'pointer', fontFamily: font.ui,
            }}
            onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
            onMouseLeave={e => { if (!pickerOpen) e.currentTarget.style.background = c.bg; }}
          >
            <Search size={14} />
            Change peer
          </button>
          <PeerPicker
            open={pickerOpen}
            onClose={() => setPickerOpen(false)}
            onSelect={onSelectPeer}
            exclude={[anchor, peer]}
            align="left"
          />
        </div>
      </div>

      {/* ── Key metrics ── */}
      {loading && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: c.textMuted, fontSize: 13 }}>
            <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />
            Loading comparison…
          </div>
        </Card>
      )}

      {!loading && error && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, color: c.neg, fontSize: 13 }}>
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>Couldn’t load {anchor} vs {peer}: {error}</span>
          </div>
        </Card>
      )}

      {!loading && !error && data && <KeyMetricsPanel data={data} />}

      {/* ── Price — normalized % change (independent of the metrics fetch) ── */}
      <PriceCompareChart anchor={anchor} peer={peer} />
    </div>
  );
};

export default CompareView;
