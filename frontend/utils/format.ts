// Shared metric value formatters — used by the comparison charts (AnalysisView)
// and the compare-view metrics panel so both render $M / % / ratio identically.
// $M means the input is already in millions (see backend compare_metrics._compute).

export const fmtM = (v: number | null | undefined): string => {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
};

export const fmtPct = (v: number | null | undefined): string =>
  v == null ? '—' : `${v.toFixed(1)}%`;

export const fmtRatio = (v: number | null | undefined): string =>
  v == null ? '—' : v.toFixed(2);

// Raw-USD magnitude formatter — input is dollars (NOT millions). Scales to
// $T / $B / $M. Shared by the single-company Trends charts and the Forecast
// panel so both render magnitudes identically. Non-finite / null → "—".
// (Distinct from fmtM above, whose input is already in millions.)
export const fmtUSD = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${Math.round(v).toLocaleString()}`;
};
