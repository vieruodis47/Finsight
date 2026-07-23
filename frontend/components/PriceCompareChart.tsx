import React, { useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import { Loader2, AlertCircle } from 'lucide-react';
import { c, font } from '../theme';
import { useIsMobile } from '../utils/hooks';
import { fetchMarketData, MarketHistoryPoint } from '../services/gemini';

interface PriceCompareChartProps {
  anchor: string;
  peer: string;
}

const FF = font.ui;

// Range buttons → yfinance period strings the /market route accepts.
const RANGES: { label: string; period: string }[] = [
  { label: '1M', period: '1mo' },
  { label: '3M', period: '3mo' },
  { label: '6M', period: '6mo' },
  { label: '1Y', period: '1y'  },
  { label: '5Y', period: '5y'  },
];

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmtDateTick = (d: string): string => {
  const [y, m] = d.split('-');
  return `${MONTHS[+m - 1]} '${y.slice(2)}`;
};
const fmtPctSigned = (v: number): string => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;

interface Row { date: string; a: number | null; b: number | null }
interface ChartModel {
  rows: Row[];
  finalA: number | null;   // last plotted % for the anchor (null if not drawn)
  finalB: number | null;
  missing: string[];       // tickers with no history in this range
  noOverlap: boolean;      // both present but zero shared trading dates
}

const pct = (v: number, base: number): number => (v / base - 1) * 100;
const toMap = (hist: MarketHistoryPoint[]): Map<string, number> => {
  const m = new Map<string, number>();
  for (const p of hist) m.set(p.date, p.close);
  return m;
};

// Build the normalized model. The two series are INNER-JOINED on date (not
// zipped by index) before any percent-change math: a positional zip silently
// desyncs the moment one ticker has a trading halt or a listing gap the other
// doesn't — the arrays stay the same length but index i stops meaning the same
// day. That corruption is invisible at 1M and glaring at 5Y. Keying by date and
// keeping only shared dates guarantees every x-position holds both companies'
// close for the SAME day. Each series is then rebased to its own close on the
// first shared date, so both lines start at 0% at the window's left edge — and
// because the window's first joined date changes with the range, changing range
// rebases from the new window, never the old baseline.
function buildModel(a: string, b: string, aHist: MarketHistoryPoint[], bHist: MarketHistoryPoint[]): ChartModel {
  const aOk = aHist.length > 0;
  const bOk = bHist.length > 0;
  const missing: string[] = [];
  if (!aOk) missing.push(a);
  if (!bOk) missing.push(b);

  if (!aOk && !bOk) {
    return { rows: [], finalA: null, finalB: null, missing, noOverlap: false };
  }

  // Both present → inner-join on date, rebase to the first shared close.
  if (aOk && bOk) {
    const am = toMap(aHist);
    const bm = toMap(bHist);
    const dates = [...am.keys()].filter(d => bm.has(d)).sort();
    if (dates.length === 0) {
      return { rows: [], finalA: null, finalB: null, missing, noOverlap: true };
    }
    const a0 = am.get(dates[0])!;
    const b0 = bm.get(dates[0])!;
    const rows: Row[] = dates.map(d => ({ date: d, a: pct(am.get(d)!, a0), b: pct(bm.get(d)!, b0) }));
    const last = rows[rows.length - 1];
    return { rows, finalA: last.a, finalB: last.b, missing, noOverlap: false };
  }

  // Exactly one present → draw it alone, rebased to its own first close.
  const solo = aOk ? aHist : bHist;
  const v0 = solo[0].close;
  const rows: Row[] = solo.map(p => ({
    date: p.date,
    a: aOk ? pct(p.close, v0) : null,
    b: bOk ? pct(p.close, v0) : null,
  }));
  const last = rows[rows.length - 1];
  return { rows, finalA: aOk ? last.a : null, finalB: bOk ? last.b : null, missing, noOverlap: false };
}

const cardStyle: React.CSSProperties = {
  background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px', marginTop: 18,
};

// Normalized price-change comparison. Lines are CATEGORICAL — anchor c.brandDeep,
// peer c.accent (the fill variant, matching CompareCharts) — carrying no
// good/bad meaning. The only green/red on the panel is the final % figure per
// ticker in the legend, where up/down IS the signal.
const PriceCompareChart: React.FC<PriceCompareChartProps> = ({ anchor, peer }) => {
  const isMobile = useIsMobile();
  const [period, setPeriod] = useState('1y');
  const [model, setModel]   = useState<ChartModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setModel(null);
    // allSettled: a dead ticker 404s (fetchMarketData throws) but must not take
    // the other line down with it.
    Promise.allSettled([fetchMarketData(anchor, period), fetchMarketData(peer, period)])
      .then(([ra, rb]) => {
        if (cancelled) return;
        const aHist = ra.status === 'fulfilled' ? ra.value.history : [];
        const bHist = rb.status === 'fulfilled' ? rb.value.history : [];
        setModel(buildModel(anchor, peer, aHist, bHist));
        setLoading(false);
      })
      .catch(e => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Failed to load price history.');
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [anchor, peer, period]);

  const tooltip = useMemo(() => ({
    contentStyle: { fontSize: 12, borderRadius: 8, border: `0.5px solid ${c.border}`, fontFamily: FF, background: c.bg },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    formatter: (v: any, name: any) => [v == null ? '—' : fmtPctSigned(v as number), (name as string) === 'a' ? anchor : peer],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    labelFormatter: (d: any) => d as string,
  }), [anchor, peer]);

  const legendEntry = (label: string, color: string, final: number | null) => (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 9, height: 9, borderRadius: '50%', background: color, display: 'inline-block' }} />
      <span style={{ fontSize: 13, fontWeight: 600, color }}>{label}</span>
      {final != null && (
        <span style={{ fontSize: 13, fontWeight: 600, color: final >= 0 ? c.pos : c.neg }}>
          {fmtPctSigned(final)}
        </span>
      )}
    </span>
  );

  return (
    <div style={cardStyle}>
      {/* Header: title + range selector */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <p style={{ fontSize: 11, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
          Price · % change
        </p>
        <div style={{ display: 'inline-flex', background: c.surfaceAlt, borderRadius: 8, padding: 3, gap: 2 }}>
          {RANGES.map(r => {
            const active = r.period === period;
            return (
              <button
                key={r.period}
                onClick={() => setPeriod(r.period)}
                style={{
                  padding: '4px 12px', borderRadius: 6, fontSize: 12,
                  fontWeight: active ? 500 : 400,
                  background: active ? c.bg : 'transparent',
                  color: active ? c.brand : c.textMuted,
                  border: active ? `0.5px solid ${c.border}` : '0.5px solid transparent',
                  cursor: 'pointer', fontFamily: FF,
                }}
              >
                {r.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Legend with final % (the only green/red on the chart) */}
      {model && (model.finalA != null || model.finalB != null) && (
        <div style={{ display: 'flex', gap: 18, marginBottom: 8, flexWrap: 'wrap' }}>
          {model.finalA != null && legendEntry(anchor, c.brandDeep, model.finalA)}
          {model.finalB != null && legendEntry(peer, c.accent, model.finalB)}
        </div>
      )}

      {/* Missing / no-overlap notes */}
      {model && model.missing.length === 1 && (
        <p style={{ fontSize: 12, color: c.textMuted, margin: '0 0 8px' }}>
          No price history for {model.missing[0]} in this range — showing {model.missing[0] === anchor ? peer : anchor} only.
        </p>
      )}
      {model && model.noOverlap && (
        <p style={{ fontSize: 12, color: c.textMuted, margin: '0 0 8px' }}>
          No overlapping trading dates for {anchor} and {peer} in this range.
        </p>
      )}

      {/* Body */}
      {loading ? (
        <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: c.textMuted, fontSize: 13 }}>
          <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />
          Loading price history…
        </div>
      ) : error ? (
        <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, color: c.neg, fontSize: 13 }}>
          <AlertCircle size={16} /> {error}
        </div>
      ) : model && model.rows.length > 0 ? (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={model.rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={c.border} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: c.textFaint }}
              tickLine={false}
              axisLine={{ stroke: c.border }}
              minTickGap={isMobile ? 72 : 48}
              tickFormatter={fmtDateTick}
            />
            <YAxis
              tick={{ fontSize: 11, fill: c.textFaint }}
              tickLine={false}
              axisLine={false}
              width={48}
              tickFormatter={(v: number) => `${v > 0 ? '+' : ''}${Math.round(v)}%`}
            />
            <Tooltip {...tooltip} />
            <ReferenceLine y={0} stroke={c.border} />
            <Line type="monotone" dataKey="a" stroke={c.brandDeep} strokeWidth={2} dot={false} connectNulls name="a" />
            <Line type="monotone" dataKey="b" stroke={c.accent}    strokeWidth={2} dot={false} connectNulls name="b" />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: c.textMuted, fontSize: 13 }}>
          No price history available for {anchor} or {peer} in this range.
        </div>
      )}
    </div>
  );
};

export default PriceCompareChart;
