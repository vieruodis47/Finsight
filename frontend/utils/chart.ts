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
