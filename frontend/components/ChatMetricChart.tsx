import React from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, Legend,
  CartesianGrid, LabelList,
} from 'recharts';
import { c, font, series } from '../theme';
import { fmtM } from '../utils/format';
import {
  gridSolid, xAxisBase, yAxisBase, tooltipStyle, legendProps, abbrevYear,
} from '../utils/chart';
import { ResponsiveChart } from './ResponsiveChart';
import type { ChatChart } from '../services/gemini';

// Inline comparison / over-time chart rendered inside an assistant bubble. It is
// driven ENTIRELY by the `chart` payload the backend built from the same XBRL
// rows that grounded the answer text — this component never computes a number, so
// the chart and the prose can't disagree. Reuses the Analysis view's Recharts
// primitives + theme (sapphire series palette; hue + dash so lines separate in
// greyscale). Green/red are reserved for directional signals and are not used.

// prefers-reduced-motion → turn off Recharts' enter animations.
const usePrefersReducedMotion = (): boolean => {
  const [reduced, setReduced] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setReduced(mq.matches);
    sync();
    mq.addEventListener?.('change', sync);
    return () => mq.removeEventListener?.('change', sync);
  }, []);
  return reduced;
};

// Per-unit value formatting (matches the backend caption formatting).
const fmtValue = (unit: ChatChart['unit'], v: number | null | undefined): string => {
  if (v == null) return 'no data';
  switch (unit) {
    case 'pct':       return `${v.toFixed(1)}%`;
    case 'ratio':     return v.toFixed(2);
    case 'per_share': return `$${v.toFixed(2)}`;
    case 'usd_m':     return fmtM(v);           // input already in $millions
    default:          return `${v}`;
  }
};
const axisTick = (unit: ChatChart['unit']) => (v: number): string => {
  switch (unit) {
    case 'pct':   return `${v}%`;
    case 'usd_m': return fmtM(v).replace('$', '');
    default:      return `${v}`;
  }
};

const ChatMetricChart: React.FC<{ chart: ChatChart }> = ({ chart }) => {
  const reduced = usePrefersReducedMotion();
  const unit = chart.unit;
  const animate = !reduced;

  // Companies that are a genuine data gap — named explicitly so the gap is
  // labeled (never silently zero/omitted).
  const barGaps = chart.kind === 'bar'
    ? (chart.bars ?? []).filter(b => b.value == null).map(b => b.label)
    : [];
  const lineGaps = chart.kind === 'line'
    ? (chart.series ?? []).filter(s => s.points.every(p => p.value == null)).map(s => s.ticker)
    : [];
  const gaps = [...barGaps, ...lineGaps];

  return (
    <figure
      role="group"
      aria-label={chart.caption}
      style={{ margin: '12px 0 2px', border: `0.5px solid ${c.border}`, borderRadius: 8, padding: '10px 12px 8px', background: c.bg }}
    >
      <figcaption style={{ fontSize: 11, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.04em', margin: '0 0 8px', fontFamily: font.ui }}>
        {chart.label}{chart.kind === 'bar' && chart.year ? ` · FY${chart.year}` : ''}
      </figcaption>

      {/* Bounded height so Recharts never renders at 0-height inside the bubble. */}
      <ResponsiveChart height={chart.kind === 'bar' ? 190 : 200}>
        {(w) => chart.kind === 'bar' ? (
          <BarChart data={(chart.bars ?? []).map(b => ({ name: b.label, value: b.value }))}
                    margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid {...gridSolid} />
            <XAxis {...xAxisBase} dataKey="name" />
            <YAxis {...yAxisBase} width={48} tickFormatter={axisTick(unit)} />
            <Tooltip
              {...tooltipStyle}
              formatter={((v: number) => [fmtValue(unit, v), chart.label]) as never}
            />
            {/* Single categorical series (companies on the x-axis) → sapphire.
                A null value renders as a gap (no bar); labels sit above bars. */}
            <Bar dataKey="value" fill={series.fill[0]} radius={[3, 3, 0, 0]} maxBarSize={54} isAnimationActive={animate}>
              <LabelList dataKey="value" position="top"
                         formatter={((v: number) => fmtValue(unit, v)) as never}
                         style={{ fontSize: 11, fill: c.textMuted, fontFamily: font.ui }} />
            </Bar>
          </BarChart>
        ) : (
          <LineChart
            data={(chart.years ?? []).map(y => {
              const row: Record<string, number | string | null> = { year: y };
              for (const s of chart.series ?? []) {
                row[s.ticker] = s.points.find(p => p.year === y)?.value ?? null;
              }
              return row;
            })}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid {...gridSolid} />
            <XAxis {...xAxisBase} dataKey="year" tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
            <YAxis {...yAxisBase} width={48} tickFormatter={axisTick(unit)} />
            <Tooltip
              {...tooltipStyle}
              formatter={((v: number, n: string) => [fmtValue(unit, v), n]) as never}
              labelFormatter={((y: string) => `FY ${y}`) as never}
            />
            {(chart.series ?? []).length > 1 && <Legend {...legendProps} />}
            {(chart.series ?? []).map((s, i) => (
              <Line
                key={s.ticker}
                type="monotone"
                dataKey={s.ticker}
                name={s.ticker}
                stroke={series.fill[i % series.fill.length]}
                strokeWidth={2}
                strokeDasharray={series.dash[i % series.dash.length] || undefined}
                dot={{ r: 2 }}
                isAnimationActive={animate}
                // Gaps must READ as gaps, not be bridged with an interpolated line.
                connectNulls={false}
              />
            ))}
          </LineChart>
        )}
      </ResponsiveChart>

      {/* Explicit labeled-gap annotation: a genuine data gap keeps its x-axis
          slot (not omitted) and draws no bar (not a zero) — this line names it as
          "no data", consistent with how the answer text discloses the gap. */}
      {gaps.length > 0 && (
        <p style={{ fontSize: 11, color: c.textFaint, margin: '6px 0 0', lineHeight: 1.5, fontFamily: font.ui }}>
          <span aria-hidden="true" style={{ marginRight: 5 }}>▫</span>
          No data for {gaps.join(', ')} — not disclosed in the filings.
        </p>
      )}

      {/* Numeric summary — keeps the figures present as text (not chart-only). */}
      <p style={{ fontSize: 11, color: c.textFaint, margin: '6px 0 0', lineHeight: 1.5, fontFamily: font.ui }}>
        {chart.caption}
      </p>
    </figure>
  );
};

export default ChatMetricChart;
