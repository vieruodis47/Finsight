import React from 'react';
import {
  ComposedChart, Line, Area, Scatter, XAxis, YAxis, Tooltip,
  CartesianGrid,
} from 'recharts';
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from 'lucide-react';
import { c, font } from '../theme';
import { fmtUSD } from '../utils/format';
import { gridCols, abbrevYear } from '../utils/chart';
import { useIsMobile } from '../utils/hooks';
import { ForecastResult, ForecastMetric } from '../services/gemini';
import { ChartFigure } from './ChartDescription';
import { ResponsiveChart } from './ResponsiveChart';
import { ChartCarousel, CarouselSlide } from './ChartCarousel';

const FF = font.ui;

const METRIC_LABELS: Record<string, string> = {
  revenue: 'Revenue',
  gross_margin_pct: 'Gross margin',
  operating_margin_pct: 'Operating margin',
  net_margin_pct: 'Net margin',
};

// A finite-number type guard. Every numeric field from the forecast API is run
// through this before it's formatted or fed to Recharts, so a null / undefined /
// NaN / Infinity value (a partial or malformed metric) renders as "—" instead of
// throwing a TypeError mid-render and white-screening the whole page.
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

// Revenue arrives as raw USD (not millions); fmtUSD (shared) scales it to $T/B/M.
const fmtVal = (v: unknown, unit: 'usd' | 'pct'): string =>
  !isNum(v) ? '—' : unit === 'usd' ? fmtUSD(v) : `${v.toFixed(1)}%`;

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

const cardStyle: React.CSSProperties = {
  background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '14px 16px',
};

const MetricForecast: React.FC<{ m: ForecastMetric }> = ({ m }) => {
  // ── Defensive normalization ──────────────────────────────────────────────
  // The forecast API is trusted to send well-formed metrics, but a partial or
  // version-skewed response can omit fields. Coerce everything to a safe shape
  // up front so no downstream access (.toFixed / .map / .length / .slice /
  // .replace) can throw. A missing field degrades gracefully, it never blanks.
  const unit: 'usd' | 'pct' = m.unit === 'pct' ? 'pct' : 'usd';
  const metricKey = typeof m.metric === 'string' ? m.metric : '';
  const label = METRIC_LABELS[metricKey] ?? (metricKey ? metricKey.replace(/_/g, ' ') : 'Metric');

  const anomalyYears: string[] = Array.isArray(m.anomaly_years)
    ? m.anomaly_years.filter((y): y is string => typeof y === 'string')
    : [];
  const history = Array.isArray(m.history) ? m.history : [];

  const predicted = isNum(m.predicted_value) ? m.predicted_value : null;
  const ciLow = isNum(m.confidence_low) ? m.confidence_low : null;
  const ciHigh = isNum(m.confidence_high) ? m.confidence_high : null;
  const nextLabel = typeof m.next_label === 'string' && m.next_label ? m.next_label : 'Next period (projected)';

  const { color: tColor, Icon: TIcon, label: tLabel } = trendStyle(m.trend);

  // Years the forecaster denoised as off-trend outliers, keyed by FY label so we
  // can dot them on the actuals line (amber = caution, NOT a directional signal).
  const anomalySet = new Set(anomalyYears.map(y => y.slice(0, 4)));

  // History as solid actuals; a dashed segment bridges the last actual to the
  // projected point, which carries a 95% CI band (ciLow..ciHigh).
  const data: Record<string, number | string | null>[] = history.map(h => {
    const yrRaw = String(h?.year ?? '');
    const yr = yrRaw.length > 4 ? yrRaw.slice(0, 4) : yrRaw;
    const val = isNum(h?.value) ? h.value : null;
    return {
      year: yr,
      actual: val,
      anomaly: anomalySet.has(yr) ? val : null,
      projected: null,
      ciLow: null,
      ciHigh: null,
    };
  });
  if (data.length > 0) {
    const last = data[data.length - 1];
    last.projected = last.actual; // bridge the dashed line from the last actual
  }
  // Only add the projected point when there's a real number to plot.
  if (predicted !== null) {
    data.push({
      year: nextLabel.replace(/\s*\(projected\)/i, ''),
      actual: null,
      projected: predicted,
      ciLow,
      ciHigh,
    });
  }

  // Nothing plottable at all — show a contained note rather than an empty chart.
  if (data.length === 0) {
    return (
      <div style={cardStyle}>
        <span style={{ fontSize: 13, fontWeight: 500, color: c.text }}>{label}</span>
        <p style={{ fontSize: 12, color: c.textMuted, margin: '8px 0 0' }}>
          No forecastable history for this metric.
        </p>
      </div>
    );
  }

  const tickFmt = (v: number) => (unit === 'usd' ? fmtUSD(v) : `${Math.round(v)}%`);

  return (
    <div style={cardStyle}>
      {/* Header: metric + directional trend + reliability */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: c.text }}>{label}</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 500, color: tColor }}>
          <TIcon size={14} /> {tLabel}
        </span>
        <span style={reliabilityStyle(m.reliability)}>
          {m.reliability ?? 'unknown'} confidence · R² {isNum(m.r_squared) ? m.r_squared.toFixed(2) : '—'}
        </span>
      </div>

      <ChartFigure description={m.description}>
      <ResponsiveChart height={200}>
        {(w) => (
        <ComposedChart data={data} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={c.borderFaint} vertical={false} />
          <XAxis dataKey="year" tickFormatter={abbrevYear(w)} interval="preserveStartEnd" tick={{ fontSize: 11, fill: c.textFaint }} tickLine={false} axisLine={{ stroke: c.border }} />
          <YAxis tick={{ fontSize: 11, fill: c.textFaint }} tickLine={false} axisLine={false} width={54} tickFormatter={tickFmt} />
          <Tooltip
            formatter={((v: number | null, name: string) => {
              if (v == null) return ['—', name];
              const label = name === 'actual' ? 'Actual'
                : name === 'projected' ? 'Projected'
                : name === 'ciHigh' ? 'CI high' : name === 'ciLow' ? 'CI low' : name;
              return [fmtVal(v, unit), label];
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
          {/* Denoised anomalies — amber dots on the actuals (caution, not directional) */}
          <Scatter dataKey="anomaly" fill={c.warnFg} isAnimationActive={false} />
        </ComposedChart>
        )}
      </ResponsiveChart>
      </ChartFigure>

      {/* Numeric summary */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: c.textMuted }}>{nextLabel}:</span>
        <span style={{ fontSize: 15, fontWeight: 600, color: c.text }}>{fmtVal(predicted, unit)}</span>
        {(ciLow !== null || ciHigh !== null) && (
          <span style={{ fontSize: 12, color: c.textFaint }}>
            95% CI {fmtVal(ciLow, unit)} – {fmtVal(ciHigh, unit)}
          </span>
        )}
      </div>
      {anomalyYears.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 11, color: c.textMuted }}>
          <AlertTriangle size={12} color={c.textFaint} />
          Denoised {anomalyYears.length} anomalous year{anomalyYears.length > 1 ? 's' : ''} ({anomalyYears.join(', ')}) before fitting the trend.
        </div>
      )}
    </div>
  );
};

const ForecastPanel: React.FC<{ data: ForecastResult }> = ({ data }) => {
  const isMobile = useIsMobile();
  // Guard the top-level shape too: a malformed response (metrics missing/not an
  // array) shows an empty state instead of throwing on `.map`.
  const metrics = Array.isArray(data?.metrics) ? data.metrics : [];
  const ticker = data?.ticker ?? '';

  // One forecast card per metric. On mobile they become a swipeable carousel
  // (one per view); desktop keeps the responsive grid.
  const slides: CarouselSlide[] = metrics.map((m, i) => {
    const key = (m && typeof m.metric === 'string' && m.metric) || String(i);
    const label = METRIC_LABELS[key] ?? (typeof m?.metric === 'string' && m.metric ? m.metric.replace(/_/g, ' ') : 'Metric');
    return { key, label, node: <MetricForecast m={m} /> };
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <p style={{ fontSize: 12, color: c.textMuted, margin: 0, lineHeight: 1.6 }}>
        Denoised weighted-linear-trend projection for <strong style={{ color: c.text }}>{ticker}</strong>,
        with 95% confidence intervals. Statistical estimate from historical filings — not investment advice.
      </p>
      {metrics.length === 0 ? (
        <div style={cardStyle}>
          <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>
            No forecastable metrics were returned for {ticker || 'this company'}.
          </p>
        </div>
      ) : isMobile ? (
        <ChartCarousel slides={slides} label={`${ticker} forecast charts`} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: gridCols(isMobile, 320), gap: 12 }}>
          {slides.map(s => <React.Fragment key={s.key}>{s.node}</React.Fragment>)}
        </div>
      )}
    </div>
  );
};

export default ForecastPanel;
