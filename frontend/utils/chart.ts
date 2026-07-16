// Shared Recharts styling primitives — single source of truth for the axis /
// grid / tooltip / legend look used across the Analysis charts (AnalysisView
// comparison charts, TrendsPanel, CompareView). Previously each component
// redeclared these locally, which drifted over time.
//
// Two grid variants are exported explicitly rather than merged, because the
// views intentionally differ: the comparison charts use the stronger `c.border`
// gridline, the single-company Trends charts use the fainter `c.borderFaint`.
// Naming them keeps that intent visible instead of hiding it behind one shared
// constant that would silently change one view's appearance.

import { c, font } from '../theme';

// Responsive grid columns for the card/chart grids. Below the mobile breakpoint
// everything stacks to a single column (auto-fit's minmax(NNNpx) would otherwise
// force a track wider than a 320–375px viewport and cause horizontal overflow).
// `minPx` is the desktop/tablet minimum track width.
export const gridCols = (isMobile: boolean, minPx: number): string =>
  isMobile ? '1fr' : `repeat(auto-fit, minmax(${minPx}px, 1fr))`;

// The dense fiscal-year axis (~19 years, FY2007–FY2025) collides when every
// label renders. The fix is Recharts' own interval="preserveStartEnd" on the
// XAxis: it drops labels that don't fit — measured against the chart's REAL
// rendered width, not the viewport, so a ~280px chart in a desktop grid thins
// just like a phone — while always keeping the first and last (FY2025) labels.
// (Recharts 3's explicit `ticks` prop suppresses the label text on a category
// axis, so preserveStartEnd is the correct native mechanism.) `abbrevYear`
// complements it by shortening labels on narrow charts so more of them survive.
//
// Abbreviate fiscal-year labels ("2007" → "'07") once the chart is narrow, so
// even the retained ticks stay short and legible. Full year at >=768px. A label
// without a 4-digit year (e.g. a projected-period label) is returned unchanged.
export const abbrevYear = (width: number) => (v: string | number): string => {
  const s = String(v);
  if (width >= 768) return s;
  const m = s.match(/(\d{4})/);
  return m ? `'${m[1].slice(2)}` : s;
};

const tick = { fontSize: 11, fill: c.textFaint } as const;

// X axis without a dataKey — callers spread this and add their own
// `dataKey` (e.g. 'year' | 'quarter' | 'x'), so it stays reusable.
export const xAxisBase = {
  tick,
  tickLine: false,
  axisLine: { stroke: c.border },
} as const;

export const yAxisBase = {
  tick,
  tickLine: false,
  axisLine: false as const,
};

// Solid gridline (comparison charts).
export const gridSolid = {
  stroke: c.border,
  strokeDasharray: '3 3' as const,
  vertical: false,
};

// Faint gridline (single-company Trends charts).
export const gridFaint = {
  stroke: c.borderFaint,
  strokeDasharray: '3 3' as const,
  vertical: false,
};

export const tooltipStyle = {
  contentStyle: {
    fontSize: 12, borderRadius: 8, border: `0.5px solid ${c.border}`,
    fontFamily: font.ui, background: c.bg,
  },
  cursor: { fill: c.surface },
};

export const legendProps = {
  iconType: 'circle' as const,
  iconSize: 8,
  wrapperStyle: { fontSize: 12, fontFamily: font.ui },
};
