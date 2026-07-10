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
