import React from 'react';
import {
  ComposedChart, Line, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from 'lucide-react';
import { c, font } from '../theme';
import { ForecastResult, ForecastMetric } from '../services/gemini';

const FF = font.ui;

const METRIC_LABELS: Record<string, string> = {
  revenue: 'Revenue',
  gross_margin_pct: 'Gross margin',
  operating_margin_pct: 'Operating margin',
  net_margin_pct: 'Net margin',
};

// Revenue arrives as raw USD (not millions), so scale generically.
const fmtUSD = (v: number): string => {
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${Math.round(v).toLocaleString()}`;
};
const fmtVal = (v: number, unit: 'usd' | 'pct'): string =>
  unit === 'usd' ? fmtUSD(v) : `${v.toFixed(1)}%`;

// Trend is a DIRECTIONAL FINANCIAL SIGNAL — the one place green/red is allowed.
const trendStyle = (trend: ForecastMetric['trend']) => {
  if (trend === 'improving') return { color: c.pos, Icon: TrendingUp, label: 'Improving' };
  if (trend === 'declining') return { color: c.neg, Icon: TrendingDown, label: 'Declining' };
  return { color: c.textMuted, Icon: Minus, label: 'Stable' };
};

const reliabilityStyle = (r: ForecastMetric['reliability']): React.CSSProperties => ({
  fontSize: 11, fontWeight: 500, padding: '2px 8px', borderRadius: 10,
  // Neutral/brand chips only — reliability is model confidence, NOT a directional
  // signal, so it must not borrow green/red.
  background: r === 'high' ? c.brandTint : c.surfaceAlt,
  color: r === 'high' ? c.brand : c.textMuted,
});

const MetricForecast: React.FC<{ m: ForecastMetric }> = ({ m }) => {
  const label = METRIC_LABELS[m.metric] ?? m.metric.replace(/_/g, ' ');
  const { color: tColor, Icon: TIcon, label: tLabel } = trendStyle(m.trend);

  // History as solid actuals; a dashed segment bridges the last actual to the
  // projected point, which carries a 95% CI band (ciLow..ciHigh).
  const data: Record<string, number | string | null>[] = m.history.map(h => ({
    year: h.year.length > 4 ? h.year.slice(0, 4) : h.year,
    actual: h.value,
    projected: null,
    ciLow: null,
    ciHigh: null,
  }));
  if (data.length > 0) {
    const last = data[data.length - 1];
    last.projected = last.actual; // bridge the dashed line from the last actual
  }
  data.push({
    year: m.next_label.replace(/\s*\(projected\)/i, ''),
    actual: null,
    projected: m.predicted_value,
    ciLow: m.confidence_low,
    ciHigh: m.confidence_high,
  });

  const tickFmt = (v: number) => (m.unit === 'usd' ? fmtUSD(v) : `${Math.round(v)}%`);

  return (
    <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '14px 16px' }}>
      {/* Header: metric + directional trend + reliability */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: c.text }}>{label}</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 500, color: tColor }}>
          <TIcon size={14} /> {tLabel}
        </span>
        <span style={reliabilityStyle(m.reliability)}>
          {m.reliability} confidence · R² {m.r_squared.toFixed(2)}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={data} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={c.borderFaint} vertical={false} />
          <XAxis dataKey="year" tick={{ fontSize: 11, fill: c.textFaint }} tickLine={false} axisLine={{ stroke: c.border }} />
          <YAxis tick={{ fontSize: 11, fill: c.textFaint }} tickLine={false} axisLine={false} width={54} tickFormatter={tickFmt} />
          <Tooltip
            formatter={((v: number | null, name: string) => {
              if (v == null) return ['—', name];
              const label = name === 'actual' ? 'Actual'
                : name === 'projected' ? 'Projected'
                : name === 'ciHigh' ? 'CI high' : name === 'ciLow' ? 'CI low' : name;
              return [fmtVal(v, m.unit), label];
            }) as never}
            contentStyle={{ fontSize: 12, fontFamily: FF, border: `0.5px solid ${c.border}`, borderRadius: 8 }}
          />
          {/* 95% CI band around the projection (neutral brand-light fill) */}
          <Area dataKey="ciHigh" stroke="none" fill={c.brandLight} fillOpacity={0.12} connectNulls isAnimationActive={false} />
          <Area dataKey="ciLow" stroke="none" fill={c.bg} fillOpacity={1} connectNulls isAnimationActive={false} />
          {/* Actual history — solid brand line */}
          <Line dataKey="actual" stroke={c.brand} strokeWidth={2} dot={{ r: 3, fill: c.brand }} connectNulls={false} isAnimationActive={false} />
          {/* Projection — dashed brand-light line to the projected point */}
          <Line dataKey="projected" stroke={c.brandLight} strokeWidth={2} strokeDasharray="5 4" dot={{ r: 4, fill: c.brandLight }} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Numeric summary */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: c.textMuted }}>{m.next_label}:</span>
        <span style={{ fontSize: 15, fontWeight: 600, color: c.text }}>{fmtVal(m.predicted_value, m.unit)}</span>
        <span style={{ fontSize: 12, color: c.textFaint }}>
          95% CI {fmtVal(m.confidence_low, m.unit)} – {fmtVal(m.confidence_high, m.unit)}
        </span>
      </div>
      {m.anomaly_years.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 11, color: c.textMuted }}>
          <AlertTriangle size={12} color={c.textFaint} />
          Denoised {m.anomaly_years.length} anomalous year{m.anomaly_years.length > 1 ? 's' : ''} ({m.anomaly_years.join(', ')}) before fitting the trend.
        </div>
      )}
    </div>
  );
};

const ForecastPanel: React.FC<{ data: ForecastResult }> = ({ data }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
    <p style={{ fontSize: 12, color: c.textMuted, margin: 0, lineHeight: 1.6 }}>
      Denoised weighted-linear-trend projection for <strong style={{ color: c.text }}>{data.ticker}</strong>,
      with 95% confidence intervals. Statistical estimate from historical filings — not investment advice.
    </p>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12 }}>
      {data.metrics.map(m => <MetricForecast key={m.metric} m={m} />)}
    </div>
  </div>
);

export default ForecastPanel;
