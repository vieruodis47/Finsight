import React, { useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, BarChart, Bar, ComposedChart, Area, Scatter,
  XAxis, YAxis, Tooltip, Legend, CartesianGrid, ReferenceLine, Cell,
} from 'recharts';
import { Loader2, AlertCircle, TrendingUp, TrendingDown } from 'lucide-react';
import { c, font, seriesB } from '../theme';
import { fmtUSD, fmtPct } from '../utils/format';
import { gridFaint, gridCols, abbrevYear, xAxisBase, yAxisBase, tooltipStyle, legendProps } from '../utils/chart';
import { useIsMobile } from '../utils/hooks';
import {
  fetchTrends, fetchQuarterly, fetchDistribution, fetchReturns,
  TrendsResult, QuarterlyResult, DistributionResult, PeriodReturns,
} from '../services/gemini';
import { ChartFigure } from './ChartDescription';
import { ResponsiveChart } from './ResponsiveChart';
import { ChartCarousel, CarouselSlide } from './ChartCarousel';

// Ported from Michelle's offline Plotly charts.py to Recharts. Six single-company
// views. Green/red is used ONLY on the returns bars (a directional market signal,
// with ▲/▼); every other series uses neutral/brand categorical tokens, and
// distribution anomalies use the amber caution token (an anomaly is not
// directional). Dollar values arrive as raw USD from the tag-merged metrics layer.

const FF = font.ui;

// Formatting (fmtUSD raw-dollars, fmtPct) and the tooltip / legend / axis look
// all come from the shared modules. Trends uses the faint gridline; alias the
// shared primitives to the local names the charts below already reference.
const gridProps = gridFaint;
const xAxisProps = xAxisBase;

const Panel: React.FC<{ title: string; subtitle?: string; children: React.ReactNode }> = ({ title, subtitle, children }) => (
  <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '14px 16px' }}>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
      <p style={{ fontSize: 11, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0, fontFamily: FF }}>{title}</p>
      {subtitle && <span style={{ fontSize: 11, color: c.textFaint }}>{subtitle}</span>}
    </div>
    {children}
  </div>
);

const selectMini: React.CSSProperties = {
  fontSize: 12, padding: '4px 8px', border: `0.5px solid ${c.border}`,
  borderRadius: 6, outline: 'none', fontFamily: FF, color: c.text, background: c.bg, cursor: 'pointer',
};

// ── #1 Single-metric trend over time ────────────────────────────────────────
const TREND_METRICS = [
  { key: 'revenue', label: 'Revenue', unit: 'usd' },
  { key: 'net_income', label: 'Net Income', unit: 'usd' },
  { key: 'gross_margin_pct', label: 'Gross Margin %', unit: 'pct' },
  { key: 'operating_margin_pct', label: 'Operating Margin %', unit: 'pct' },
  { key: 'net_margin_pct', label: 'Net Margin %', unit: 'pct' },
] as const;

const TrendChart: React.FC<{ data: TrendsResult }> = ({ data }) => {
  const [metric, setMetric] = useState<typeof TREND_METRICS[number]['key']>('revenue');
  const def = TREND_METRICS.find(m => m.key === metric)!;
  const fmt = def.unit === 'usd' ? fmtUSD : fmtPct;
  const desc = data.descriptions?.[metric];
  return (
    <Panel title="Metric over time">
      <div style={{ marginBottom: 8 }}>
        <select style={selectMini} value={metric} onChange={e => setMetric(e.target.value as typeof metric)}>
          {TREND_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      </div>
      <ChartFigure description={desc}>
        <ResponsiveChart height={220}>
          {(w) => (
          <LineChart data={data.points} margin={{ top: 6, right: 12, left: 4, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis {...xAxisProps} dataKey="year" tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
            <YAxis {...yAxisBase} width={58} tickFormatter={(v: number) => (def.unit === 'usd' ? fmtUSD(v) : `${Math.round(v)}%`)} />
            <Tooltip {...tooltipStyle} formatter={((v: number) => [fmt(v), def.label]) as never} labelFormatter={(l) => `FY ${l}`} />
            <Line type="monotone" dataKey={metric} stroke={c.brand} strokeWidth={2} dot={{ r: 3, fill: c.brand }} connectNulls name={def.label} isAnimationActive={false} />
          </LineChart>
          )}
        </ResponsiveChart>
      </ChartFigure>
    </Panel>
  );
};

// ── #5 Margin breakdown: COGS vs Gross Profit (stacked) ─────────────────────
const MarginStackChart: React.FC<{ data: TrendsResult }> = ({ data }) => {
  return (
  <Panel title="Cost structure" subtitle="COGS + Gross profit = Revenue">
    <ChartFigure description={data.descriptions?.cost_structure}>
      <ResponsiveChart height={220}>
        {(w) => (
        <BarChart data={data.points} margin={{ top: 6, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis {...xAxisProps} dataKey="year" tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
          <YAxis {...yAxisBase} width={58} tickFormatter={(v: number) => fmtUSD(v)} />
          <Tooltip {...tooltipStyle} formatter={((v: number, n: string) => [fmtUSD(v), n === 'cogs' ? 'COGS' : 'Gross profit']) as never} labelFormatter={(l) => `FY ${l}`} />
          <Legend {...legendProps} formatter={(v: string) => (v === 'cogs' ? 'COGS' : 'Gross profit')} />
          {/* Neutral categorical fills — cost vs profit is not a directional signal */}
          <Bar dataKey="cogs" stackId="s" fill={c.peer} maxBarSize={26} name="cogs" />
          <Bar dataKey="gross_profit" stackId="s" fill={c.brand} maxBarSize={26} name="gross_profit" radius={[3, 3, 0, 0]} />
        </BarChart>
        )}
      </ResponsiveChart>
    </ChartFigure>
  </Panel>
  );
};

// ── #6 Revenue vs Net Income (dual axis) ────────────────────────────────────
const RevenueProfitChart: React.FC<{ data: TrendsResult }> = ({ data }) => {
  return (
  <Panel title="Revenue vs Net income" subtitle="dual axis">
    <ChartFigure description={data.descriptions?.revenue_vs_income}>
      <ResponsiveChart height={220}>
        {(w) => (
        <ComposedChart data={data.points} margin={{ top: 6, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis {...xAxisProps} dataKey="year" tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
          <YAxis {...yAxisBase} yAxisId="rev" width={54} tickFormatter={(v: number) => fmtUSD(v)} />
          <YAxis {...yAxisBase} yAxisId="ni" orientation="right" width={54} tickFormatter={(v: number) => fmtUSD(v)} />
          <Tooltip {...tooltipStyle} formatter={((v: number, n: string) => [fmtUSD(v), n === 'revenue' ? 'Revenue' : 'Net income']) as never} labelFormatter={(l) => `FY ${l}`} />
          <Legend {...legendProps} formatter={(v: string) => (v === 'revenue' ? 'Revenue' : 'Net income')} />
          <ReferenceLine yAxisId="ni" y={0} stroke={c.border} />
          {/* Two hue-differentiated series (sapphire revenue / amber net income) —
              the old pair was two sapphires, indistinguishable in greyscale. Net
              income is also dashed so colour is never the only cue (WCAG 1.4.1). */}
          <Line yAxisId="rev" type="monotone" dataKey="revenue" stroke={c.brand} strokeWidth={2} dot={false} connectNulls name="revenue" isAnimationActive={false} />
          <Line yAxisId="ni" type="monotone" dataKey="net_income" stroke={seriesB.fill} strokeWidth={2} strokeDasharray={seriesB.dash} dot={false} connectNulls name="net_income" isAnimationActive={false} />
        </ComposedChart>
        )}
      </ResponsiveChart>
    </ChartFigure>
  </Panel>
  );
};

// ── #2 Quarterly breakdown (latest FY) ──────────────────────────────────────
const QUARTER_METRICS = [
  { key: 'revenue', label: 'Revenue' },
  { key: 'gross_profit', label: 'Gross profit' },
  { key: 'operating_income', label: 'Operating income' },
  { key: 'net_income', label: 'Net income' },
] as const;

const QuarterlyChart: React.FC<{ data: QuarterlyResult }> = ({ data }) => {
  const [metric, setMetric] = useState<typeof QUARTER_METRICS[number]['key']>('revenue');
  const def = QUARTER_METRICS.find(m => m.key === metric)!;
  const desc = data.descriptions?.[metric];
  return (
    <Panel title="Quarterly breakdown" subtitle={`FY${data.fy}`}>
      <div style={{ marginBottom: 8 }}>
        <select style={selectMini} value={metric} onChange={e => setMetric(e.target.value as typeof metric)}>
          {QUARTER_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      </div>
      <ChartFigure description={desc}>
        <ResponsiveChart height={200}>
          {() => (
          <BarChart data={data.points} margin={{ top: 6, right: 12, left: 4, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis {...xAxisProps} dataKey="quarter" />
            <YAxis {...yAxisBase} width={58} tickFormatter={(v: number) => fmtUSD(v)} />
            <Tooltip {...tooltipStyle} formatter={((v: number) => [fmtUSD(v), def.label]) as never} />
            <ReferenceLine y={0} stroke={c.border} />
            <Bar dataKey={metric} fill={c.brand} maxBarSize={40} radius={[3, 3, 0, 0]} name={def.label} />
          </BarChart>
          )}
        </ResponsiveChart>
      </ChartFigure>
    </Panel>
  );
};

// ── #9 Distribution (bell curve + per-year dots) ────────────────────────────
const DIST_METRICS = [
  { key: 'net_margin_pct', label: 'Net Margin %' },
  { key: 'operating_margin_pct', label: 'Operating Margin %' },
  { key: 'gross_margin_pct', label: 'Gross Margin %' },
  { key: 'revenue', label: 'Revenue' },
] as const;

const normalPdf = (x: number, mean: number, std: number): number =>
  (1 / (std * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mean) / std) ** 2);

const DistributionChart: React.FC<{ ticker: string }> = ({ ticker }) => {
  const [metric, setMetric] = useState<typeof DIST_METRICS[number]['key']>('net_margin_pct');
  const [data, setData] = useState<DistributionResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr(null); setData(null);
    fetchDistribution(ticker, metric)
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setErr(e instanceof Error ? e.message : 'Failed'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ticker, metric]);

  const def = DIST_METRICS.find(m => m.key === metric)!;
  const fmt = data?.unit === 'usd' ? fmtUSD : fmtPct;

  const { curve, normalPts, anomalyPts, domain } = useMemo(() => {
    if (!data || data.std <= 0) return { curve: [], normalPts: [], anomalyPts: [], domain: [0, 1] as [number, number] };
    const { mean, std } = data;
    const lo = mean - 4 * std, hi = mean + 4 * std;
    const curve = Array.from({ length: 61 }, (_, i) => {
      const x = lo + ((hi - lo) * i) / 60;
      return { x, pdf: normalPdf(x, mean, std) };
    });
    const pt = (p: { year: string; value: number }) => ({ x: p.value, pdf: normalPdf(p.value, mean, std), year: p.year });
    return {
      curve,
      normalPts: data.points.filter(p => !p.is_anomaly).map(pt),
      anomalyPts: data.points.filter(p => p.is_anomaly).map(pt),
      domain: [lo, hi] as [number, number],
    };
  }, [data]);

  return (
    <Panel title="Distribution" subtitle="historical spread; ⚠ = trend anomaly">
      <div style={{ marginBottom: 8 }}>
        <select style={selectMini} value={metric} onChange={e => setMetric(e.target.value as typeof metric)}>
          {DIST_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      </div>
      {loading && <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: c.textMuted, fontSize: 13 }}><Loader2 size={15} style={{ animation: 'spin 1s linear infinite', marginRight: 6 }} /> Loading…</div>}
      {!loading && err && <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: c.textMuted, fontSize: 12, textAlign: 'center' }}>No {def.label.toLowerCase()} distribution for {ticker}.</div>}
      {!loading && !err && data && (
        <ChartFigure description={data.description}>
          <ResponsiveChart height={220}>
            {() => (
            <ComposedChart data={curve} margin={{ top: 6, right: 12, left: 4, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} type="number" dataKey="x" domain={domain} tickFormatter={(v: number) => (data.unit === 'usd' ? fmtUSD(v) : `${Math.round(v)}%`)} />
              <YAxis {...yAxisBase} width={30} tick={false} label={{ value: 'density', angle: -90, position: 'insideLeft', fontSize: 10, fill: c.textFaint }} />
              <Tooltip {...tooltipStyle}
                formatter={((v: number, _n: string, p: { payload?: { year?: string; x?: number } }) => (p?.payload?.year ? [fmt(p.payload.x ?? v), `FY${p.payload.year}`] : null)) as never}
              />
              <Area dataKey="pdf" stroke={c.brandLight} fill={c.brandTint} fillOpacity={0.6} isAnimationActive={false} />
              <Scatter data={normalPts} dataKey="pdf" fill={c.brand} isAnimationActive={false} />
              <Scatter data={anomalyPts} dataKey="pdf" isAnimationActive={false}>
                {anomalyPts.map((_, i) => <Cell key={i} fill={c.warnFg} />)}
              </Scatter>
            </ComposedChart>
            )}
          </ResponsiveChart>
        </ChartFigure>
      )}
    </Panel>
  );
};

// ── #8 Trailing returns (directional → green/red allowed) ───────────────────
const ReturnsChart: React.FC<{ returns: PeriodReturns }> = ({ returns }) => {
  const rows = [
    { label: '1M', value: returns.m1 },
    { label: '3M', value: returns.m3 },
    { label: '6M', value: returns.m6 },
    { label: '1Y', value: returns.y1 },
  ];
  // Accessible summary restating the plotted returns (market-price data, not
  // filings). The values are also shown in the legend row below, so this lives
  // only in an aria-label to avoid a visible duplicate.
  const fmtRet = (v: number | null) => (v == null ? 'not available' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`);
  const ariaLabel =
    `Trailing price return versus the close 1, 3, 6 and 12 months ago: ` +
    `${fmtRet(returns.m1)} over 1 month, ${fmtRet(returns.m3)} over 3 months, ` +
    `${fmtRet(returns.m6)} over 6 months, ${fmtRet(returns.y1)} over 1 year. ` +
    `Market-price movement, not from filings; not investment advice.`;
  return (
    <Panel title="Trailing price return" subtitle="vs close 1M / 3M / 6M / 1Y ago">
      <div role="img" aria-label={ariaLabel}>
      <ResponsiveChart height={200}>
        {() => (
        <BarChart data={rows} margin={{ top: 14, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis {...xAxisProps} dataKey="label" />
          <YAxis {...yAxisBase} width={44} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip {...tooltipStyle} formatter={((v: number) => [`${v >= 0 ? '▲' : '▼'} ${v.toFixed(1)}%`, 'Return']) as never} />
          <ReferenceLine y={0} stroke={c.border} />
          {/* Returns ARE a directional financial signal — the one place green/red belongs */}
          <Bar dataKey="value" maxBarSize={44} radius={[3, 3, 0, 0]} name="Return">
            {rows.map((r, i) => <Cell key={i} fill={r.value == null ? c.peer : r.value >= 0 ? c.pos : c.neg} />)}
          </Bar>
        </BarChart>
        )}
      </ResponsiveChart>
      </div>
      <div style={{ display: 'flex', gap: 14, marginTop: 8, flexWrap: 'wrap' }}>
        {rows.map(r => (
          <span key={r.label} style={{ fontSize: 12, color: c.textMuted, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            {r.label}:{' '}
            {r.value == null ? <span style={{ color: c.textFaint }}>—</span> : (
              <span style={{ color: r.value >= 0 ? c.pos : c.neg, fontWeight: 500, display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                {r.value >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                {r.value.toFixed(1)}%
              </span>
            )}
          </span>
        ))}
      </div>
    </Panel>
  );
};

// ── Container: fetch once, lay the six charts out in a responsive grid ───────
const TrendsPanel: React.FC<{ ticker: string }> = ({ ticker }) => {
  const isMobile = useIsMobile();
  const [trends, setTrends] = useState<TrendsResult | null>(null);
  const [quarterly, setQuarterly] = useState<QuarterlyResult | null>(null);
  const [returns, setReturns] = useState<PeriodReturns | null>(null);
  const [quarterlyErr, setQuarterlyErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    setTrends(null); setQuarterly(null); setReturns(null); setQuarterlyErr(null);

    // Trends is the required backbone; quarterly + returns are best-effort so a
    // missing quarterly filer or market blip doesn't blank the whole panel.
    fetchTrends(ticker)
      .then(t => { if (!cancelled) setTrends(t); })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load trends.'); })
      .finally(() => { if (!cancelled) setLoading(false); });

    fetchQuarterly(ticker)
      .then(q => { if (!cancelled) setQuarterly(q); })
      .catch(e => { if (!cancelled) setQuarterlyErr(e instanceof Error ? e.message : 'no quarterly data'); });

    fetchReturns(ticker)
      .then(r => { if (!cancelled) setReturns(r); })
      .catch(() => { /* returns are optional */ });

    return () => { cancelled = true; };
  }, [ticker]);

  if (loading) {
    return (
      <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: 20, display: 'flex', alignItems: 'center', gap: 8, color: c.textMuted, fontSize: 13, fontFamily: FF }}>
        <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> Loading trends for {ticker}…
      </div>
    );
  }
  if (error || !trends) {
    return (
      <div style={{ background: c.negSurface, border: `0.5px solid ${c.negBorder}`, borderRadius: 10, padding: '14px 16px', display: 'flex', alignItems: 'flex-start', gap: 10, color: c.neg, fontSize: 13, fontFamily: FF }}>
        <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> {error ?? 'No trend data.'}
      </div>
    );
  }

  // The six single-company views. On mobile these become a swipeable carousel
  // (one chart per view) instead of a tall vertical stack; desktop keeps the
  // responsive grid. Each entry carries a label used by the carousel's live
  // region + position readout.
  const slides: CarouselSlide[] = [
    { key: 'metric', label: 'Metric over time', node: <TrendChart data={trends} /> },
    { key: 'revprofit', label: 'Revenue vs Net income', node: <RevenueProfitChart data={trends} /> },
    { key: 'cost', label: 'Cost structure', node: <MarginStackChart data={trends} /> },
    {
      key: 'quarterly', label: 'Quarterly breakdown',
      node: quarterly
        ? <QuarterlyChart data={quarterly} />
        : <Panel title="Quarterly breakdown"><div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: c.textMuted, fontSize: 12, textAlign: 'center' }}>No quarterly data available for {ticker}.{quarterlyErr ? '' : ''}</div></Panel>,
    },
    { key: 'distribution', label: 'Distribution', node: <DistributionChart ticker={ticker} /> },
    {
      key: 'returns', label: 'Trailing price return',
      node: returns
        ? <ReturnsChart returns={returns} />
        : <Panel title="Trailing price return"><div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: c.textMuted, fontSize: 12 }}>No market data for {ticker}.</div></Panel>,
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontFamily: FF }}>
      <p style={{ fontSize: 12, color: c.textMuted, margin: 0, lineHeight: 1.6 }}>
        Multi-year charts for <strong style={{ color: c.text }}>{trends.ticker}</strong>, from the full tag-merged
        filing history. Fiscal-year labels use each filing's period-end date.
      </p>
      {isMobile ? (
        <ChartCarousel slides={slides} label={`${trends.ticker} trend charts`} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: gridCols(isMobile, 360), gap: 12 }}>
          {slides.map(s => <React.Fragment key={s.key}>{s.node}</React.Fragment>)}
        </div>
      )}
    </div>
  );
};

export default TrendsPanel;
