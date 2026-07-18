import React, { useState, useMemo } from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, Legend,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { FileText, GitCompare, TrendingUp, BarChart3, Download, FileDown, Loader2, AlertCircle, AlertTriangle } from 'lucide-react';
import { Document } from '../types';
import {
  generateSummary, compareDocuments, fetchCompareMetrics, CompareMetricsResult,
  fetchForecast, ForecastResult, exportAnalysisReport,
} from '../services/gemini';
import { c, font, seriesA, seriesB } from '../theme';
import { fmtM, fmtPct, fmtRatio } from '../utils/format';
import { gridSolid, gridCols, abbrevYear, xAxisBase, yAxisBase, tooltipStyle, legendProps as legendBase } from '../utils/chart';
import { useIsMobile } from '../utils/hooks';
import { ResponsiveChart } from './ResponsiveChart';
import { ChartCarousel, CarouselSlide } from './ChartCarousel';
import ForecastPanel from './ForecastPanel';
import TrendsPanel from './TrendsPanel';

interface AnalysisViewProps {
  documents: Document[];
}

const FF = font.ui;

const modeBtn = (active: boolean, isMobile: boolean): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
  padding: '7px 16px', borderRadius: 7, fontSize: 13,
  // On mobile each cell is a 44px-tall touch target inside the 2×2 grid.
  minHeight: isMobile ? 44 : undefined,
  fontWeight: active ? 500 : 400,
  background: active ? c.bg : 'transparent',
  color:      active ? c.brand : c.textMuted,
  border:     active ? `0.5px solid ${c.border}` : 'none',
  cursor: 'pointer', fontFamily: FF,
  transition: 'background 0.1s, color 0.1s',
});

const selectStyle: React.CSSProperties = {
  width: '100%', fontSize: 13,
  padding: '8px 12px',
  border: `0.5px solid ${c.border}`,
  borderRadius: 7, outline: 'none',
  fontFamily: FF, color: c.text,
  background: c.bg, cursor: 'pointer',
};

const primaryBtn = (disabled: boolean): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '8px 18px', borderRadius: 7, fontSize: 13, fontWeight: 500,
  background: disabled ? c.border : c.brandDeep,
  color:      disabled ? c.textFaint : c.onBrand,
  border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
  fontFamily: FF, transition: 'background 0.15s',
});

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, color: c.textMuted, marginBottom: 8,
  textTransform: 'uppercase', letterSpacing: '0.04em',
};

// ── Markdown renderer ─────────────────────────────────────────────────────

const parseBold = (text: string): React.ReactNode => {
  const parts = text.split('**');
  if (parts.length === 1) return text;
  return <>{parts.map((p, j) => j % 2 === 1 ? <strong key={j} style={{ fontWeight: 600 }}>{p}</strong> : p)}</>;
};

const renderMarkdown = (text: string): React.ReactNode => {
  if (!text) return null;
  const lines = text.split('\n');
  const nodes: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Table: consume consecutive | lines
    if (line.trim().startsWith('|')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      // Drop separator rows (|---|---|)
      const rows = tableLines.filter(l => !/^\|[\s|:-]+\|$/.test(l.trim()));
      nodes.push(
        <div key={`tbl-${i}`} style={{ overflowX: 'auto', marginBottom: 14 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <tbody>
              {rows.map((row, ri) => {
                const cells = row.split('|').slice(1, -1); // trim leading/trailing pipes
                const isHeader = ri === 0;
                return (
                  <tr key={ri}>
                    {cells.map((cell, ci) =>
                      isHeader ? (
                        <th key={ci} style={{ padding: '5px 12px', textAlign: 'left', fontWeight: 600, borderBottom: `1px solid ${c.border}`, color: c.text, fontFamily: FF }}>
                          {cell.trim()}
                        </th>
                      ) : (
                        <td key={ci} style={{ padding: '5px 12px', borderBottom: `0.5px solid ${c.borderFaint}`, color: c.text2 }}>
                          {parseBold(cell.trim())}
                        </td>
                      )
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (line.startsWith('## ')) {
      nodes.push(<h2 key={i} style={{ fontSize: 15, fontWeight: 600, color: c.text, margin: '22px 0 6px', fontFamily: font.prose }}>{parseBold(line.slice(3))}</h2>);
    } else if (line.startsWith('# ')) {
      nodes.push(<h1 key={i} style={{ fontSize: 17, fontWeight: 600, color: c.text, margin: '26px 0 8px', fontFamily: font.prose }}>{parseBold(line.slice(2))}</h1>);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      nodes.push(<li key={i} style={{ marginLeft: 18, marginBottom: 5, fontSize: 13, color: c.text2, lineHeight: 1.65 }}>{parseBold(line.slice(2))}</li>);
    } else if (line.trim() === '') {
      nodes.push(<br key={i} />);
    } else {
      nodes.push(<p key={i} style={{ fontSize: 13, color: c.text2, lineHeight: 1.7, marginBottom: 6 }}>{parseBold(line)}</p>);
    }
    i++;
  }

  return nodes;
};

// ── Comparison charts ─────────────────────────────────────────────────────

// Categorical series colours — hue-differentiated (sapphire vs amber), from the
// theme's single-source palette. NOT green/red (those stay directional-only).
// Series B also carries a dash pattern so the two lines are distinguishable in
// greyscale and for colour-vision-deficient users (WCAG 1.4.1 — never colour
// alone).
const COL_A = seriesA.fill;
const COL_B = seriesB.fill;
const DASH_B = seriesB.dash;

// Axis / grid / tooltip look come from the shared primitives (utils/chart). The
// comparison charts key their X axis on the fiscal year and use the solid grid.
const xAxisProps = { ...xAxisBase, dataKey: 'year' as const };
const gridProps = gridSolid;

// Each panel: uppercase title, the chart (wrapped role="img" + aria-label so a
// screen reader announces the computed trend, not an unlabeled SVG), then the
// same description as a visible caption (aria-hidden to avoid a double read).
const ChartPanel: React.FC<{ title: string; description?: string; children: React.ReactNode }> = ({ title, description, children }) => {
  const label = description?.trim() || undefined;
  return (
    <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '14px 16px' }}>
      <p style={{ fontSize: 11, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 10px', fontFamily: FF }}>{title}</p>
      <div role={label ? 'img' : undefined} aria-label={label}>
        {children}
      </div>
      {label && (
        <p aria-hidden="true" style={{ margin: '8px 0 0', fontSize: 12, lineHeight: 1.55, color: c.textMuted, fontFamily: FF }}>
          {label}
        </p>
      )}
    </div>
  );
};

const CompareCharts: React.FC<{ data: CompareMetricsResult }> = ({ data }) => {
  const { a: ta, b: tb } = data.tickers;

  // Shared legend look + a per-pair formatter mapping the a/b series keys to
  // the two tickers.
  const legendProps = { ...legendBase, formatter: (val: string) => (val === 'a' ? ta : tb) };

  const mkTooltip = (fmt: (v: number | null) => string) => ({
    ...tooltipStyle,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    formatter: (v: any, name: any) => [fmt(v as number | null), (name as string) === 'a' ? ta : tb],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    labelFormatter: (yr: any) => `FY ${yr}`,
  });

  // Deterministic, server-computed descriptions keyed by series metric.
  const D = data.descriptions ?? {};

  // All series share one common ~19-year fiscal axis. The label-collision bug is
  // density vs. the chart's REAL rendered width (a chart in a 3-column desktop
  // grid is only ~280px wide and collides just like a phone), so each XAxis gets
  // interval="preserveStartEnd" — Recharts drops labels that don't fit by its own
  // measured axis width while always keeping the first and last (FY2025) — plus a
  // width-based abbreviation ('07) that shortens labels so more survive.
  //
  // Each chart is defined once, then arranged either as the desktop row grid or,
  // on mobile, as one-chart-per-slide in a swipeable carousel.
  const slides: CarouselSlide[] = [
    {
      key: 'revenue', label: 'Revenue',
      node: (
        <ChartPanel title="Revenue" description={D.revenue}>
          <ResponsiveChart height={210}>
            {(w) => (
            <BarChart data={data.revenue} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
              <YAxis {...yAxisBase} width={56} tickFormatter={v => fmtM(v).replace('$', '')} />
              <Tooltip {...mkTooltip(fmtM)} />
              <Legend {...legendProps} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
            )}
          </ResponsiveChart>
        </ChartPanel>
      ),
    },
    {
      key: 'net_income', label: 'Net Income',
      node: (
        <ChartPanel title="Net Income" description={D.net_income}>
          <ResponsiveChart height={210}>
            {(w) => (
            <BarChart data={data.net_income} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
              <YAxis {...yAxisBase} width={56} tickFormatter={v => fmtM(v).replace('$', '')} />
              <Tooltip {...mkTooltip(fmtM)} />
              <Legend {...legendProps} />
              <ReferenceLine y={0} stroke={c.border} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
            )}
          </ResponsiveChart>
        </ChartPanel>
      ),
    },
    ...(
      [
        ['gross_margin_pct',     'Gross Margin %'],
        ['operating_margin_pct', 'Operating Margin %'],
        ['net_margin_pct',       'Net Margin %'],
      ] as const
    ).map(([key, label]): CarouselSlide => ({
      key, label,
      node: (
        <ChartPanel title={label} description={D[key]}>
          <ResponsiveChart height={165}>
            {(w) => (
            <LineChart data={data[key]} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
              <YAxis {...yAxisBase} width={40} tickFormatter={v => `${v}%`} />
              <Tooltip {...mkTooltip(fmtPct)} />
              <Legend {...legendProps} />
              <ReferenceLine y={0} stroke={c.border} />
              <Line type="monotone" dataKey="a" stroke={COL_A} strokeWidth={2} dot={false} connectNulls name="a" />
              <Line type="monotone" dataKey="b" stroke={COL_B} strokeWidth={2} strokeDasharray={DASH_B} dot={false} connectNulls name="b" />
            </LineChart>
            )}
          </ResponsiveChart>
        </ChartPanel>
      ),
    })),
    {
      key: 'revenue_growth_pct', label: 'Revenue Growth %',
      node: (
        <ChartPanel title="Revenue Growth %" description={D.revenue_growth_pct}>
          <ResponsiveChart height={200}>
            {(w) => (
            <BarChart data={data.revenue_growth_pct} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
              <YAxis {...yAxisBase} width={44} tickFormatter={v => `${v}%`} />
              <Tooltip {...mkTooltip(fmtPct)} />
              <Legend {...legendProps} />
              <ReferenceLine y={0} stroke={c.border} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
            )}
          </ResponsiveChart>
        </ChartPanel>
      ),
    },
    {
      key: 'free_cash_flow', label: 'Free Cash Flow',
      node: (
        <ChartPanel title="Free Cash Flow" description={D.free_cash_flow}>
          <ResponsiveChart height={200}>
            {(w) => (
            <BarChart data={data.free_cash_flow} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
              <YAxis {...yAxisBase} width={56} tickFormatter={v => fmtM(v).replace('$', '')} />
              <Tooltip {...mkTooltip(fmtM)} />
              <Legend {...legendProps} />
              <ReferenceLine y={0} stroke={c.border} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
            )}
          </ResponsiveChart>
        </ChartPanel>
      ),
    },
    {
      key: 'debt_to_equity', label: 'Debt-to-Equity',
      node: (
        <ChartPanel title="Debt-to-Equity" description={D.debt_to_equity}>
          <ResponsiveChart height={180}>
            {(w) => (
            <LineChart data={data.debt_to_equity} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
              <YAxis {...yAxisBase} width={40} tickFormatter={fmtRatio} />
              <Tooltip {...mkTooltip(fmtRatio)} />
              <Legend {...legendProps} />
              <Line type="monotone" dataKey="a" stroke={COL_A} strokeWidth={2} dot={false} connectNulls name="a" />
              <Line type="monotone" dataKey="b" stroke={COL_B} strokeWidth={2} strokeDasharray={DASH_B} dot={false} connectNulls name="b" />
            </LineChart>
            )}
          </ResponsiveChart>
        </ChartPanel>
      ),
    },
    {
      key: 'current_ratio', label: 'Current Ratio',
      node: (
        <ChartPanel title="Current Ratio" description={D.current_ratio}>
          <ResponsiveChart height={180}>
            {(w) => (
            <LineChart data={data.current_ratio} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} tickFormatter={abbrevYear(w)} interval="preserveStartEnd" />
              <YAxis {...yAxisBase} width={40} tickFormatter={fmtRatio} />
              <Tooltip {...mkTooltip(fmtRatio)} />
              <Legend {...legendProps} />
              <ReferenceLine y={1} stroke={c.border} strokeDasharray="4 4" />
              <Line type="monotone" dataKey="a" stroke={COL_A} strokeWidth={2} dot={false} connectNulls name="a" />
              <Line type="monotone" dataKey="b" stroke={COL_B} strokeWidth={2} strokeDasharray={DASH_B} dot={false} connectNulls name="b" />
            </LineChart>
            )}
          </ResponsiveChart>
        </ChartPanel>
      ),
    },
  ];

  const intro = (
    <p style={{ fontSize: 12, color: c.textMuted, margin: 0, lineHeight: 1.6 }}>
      Multi-year XBRL comparison for <strong style={{ color: seriesA.ink }}>{ta}</strong> vs{' '}
      <strong style={{ color: seriesB.ink }}>{tb}</strong>, aligned to a common fiscal-year axis.
      Captions are statistical descriptions of historical filings, not investment advice.
    </p>
  );

  // Responsive carousel at every width: 3-up ≥1200px, 2-up ≥768px, 1-up below.
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {intro}
      <ChartCarousel slides={slides} label={`${ta} vs ${tb} comparison charts`} />
    </div>
  );
};

// ── PDF export ────────────────────────────────────────────────────────────
// Server-composed, vector, print-ready PDF (charts + the SAME deterministic
// descriptions shown here + forecast values/CI/R²). Shows progress and surfaces
// a clear error instead of a silent no-op.
const ExportPdfButton: React.FC<{ ticker: string }> = ({ ticker }) => {
  const [exporting, setExporting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setErr(null);
    setExporting(true);
    try {
      await exportAnalysisReport(ticker);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Export failed.');
    } finally {
      setExporting(false);
    }
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
      <button
        onClick={run}
        disabled={exporting}
        aria-label={`Export ${ticker} analysis as PDF`}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 7,
          fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', fontFamily: FF,
          background: exporting ? c.surfaceAlt : c.bg, color: exporting ? c.textMuted : c.brand,
          border: `0.5px solid ${c.border}`, cursor: exporting ? 'default' : 'pointer',
        }}
        onMouseEnter={e => { if (!exporting) e.currentTarget.style.background = c.surface; }}
        onMouseLeave={e => { if (!exporting) e.currentTarget.style.background = c.bg; }}
      >
        {exporting
          ? <><Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Preparing PDF…</>
          : <><FileDown size={14} /> Export PDF</>}
      </button>
      {err && (
        <span role="alert" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: c.neg }}>
          <AlertCircle size={12} style={{ flexShrink: 0 }} /> {err}
        </span>
      )}
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────

const AnalysisView: React.FC<AnalysisViewProps> = ({ documents }) => {
  const isMobile = useIsMobile();
  const [mode, setMode]                           = useState<'summary' | 'compare' | 'forecast' | 'trends'>('summary');
  const [selectedDocForSummary, setSelectedDoc]   = useState('');
  const [trendsDocId, setTrendsDocId]             = useState('');
  const [summaryResult, setSummaryResult]         = useState('');
  const [doc1Id, setDoc1Id]                       = useState('');
  const [doc2Id, setDoc2Id]                       = useState('');
  const [compareResult, setCompareResult]         = useState('');
  const [chartData, setChartData]                 = useState<CompareMetricsResult | null>(null);
  const [forecastDocId, setForecastDocId]         = useState('');
  const [forecastData, setForecastData]           = useState<ForecastResult | null>(null);
  const [isLoading, setIsLoading]                 = useState(false);
  const [error, setError]                         = useState<string | null>(null);

  const handleForecast = async () => {
    const doc = documents.find(d => d.id === forecastDocId);
    if (!doc?.ticker) { setError('Pick a filing with a ticker to forecast (EDGAR filings, not uploads).'); return; }
    setIsLoading(true); setError(null); setForecastData(null);
    try {
      setForecastData(await fetchForecast(doc.ticker));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Forecast failed.');
    } finally {
      setIsLoading(false);
    }
  };

  const docA = documents.find(d => d.id === doc1Id);
  const docB = documents.find(d => d.id === doc2Id);
  const aSector = docA?.sector;

  const bCandidates  = documents.filter(d => d.id !== doc1Id);
  const sameSector   = aSector ? bCandidates.filter(d => d.sector === aSector) : [];
  const otherSector  = aSector ? bCandidates.filter(d => d.sector !== aSector) : bCandidates;
  const sectorMismatch = !!(docA?.sector && docB?.sector && docA.sector !== docB.sector);

  const withLoading = async (fn: () => Promise<void>) => {
    setIsLoading(true);
    setError(null);
    try { await fn(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Operation failed.'); }
    finally { setIsLoading(false); }
  };

  const handlePickA = (id: string) => {
    setDoc1Id(id);
    if (id === doc2Id) setDoc2Id('');
  };

  const handleGenerateSummary = async () => {
    if (!selectedDocForSummary) return;
    const doc = documents.find(d => d.id === selectedDocForSummary);
    if (!doc) return;
    setSummaryResult('');
    await withLoading(() => generateSummary(doc.content).then(setSummaryResult));
  };

  const handleCompare = async () => {
    if (!doc1Id || !doc2Id || doc1Id === doc2Id) {
      setError('Please select two different documents to compare.'); return;
    }
    if (!docA || !docB) return;
    if (!docA.content) {
      setError(`"${docA.name}" has no text content yet — remove it and re-fetch to rebuild.`); return;
    }
    if (!docB.content) {
      setError(`"${docB.name}" has no text content yet — remove it and re-fetch to rebuild.`); return;
    }
    setChartData(null);
    setCompareResult('');
    await withLoading(async () => {
      const textPromise = compareDocuments(
        docA.name, docA.content.slice(0, 30_000),
        docB.name, docB.content.slice(0, 30_000),
      );
      // Charts fetch runs in parallel; failure is non-fatal
      const chartsPromise = docA.ticker && docB.ticker
        ? fetchCompareMetrics(docA.ticker, docB.ticker).catch(() => null)
        : Promise.resolve(null);
      const [text, charts] = await Promise.all([textPromise, chartsPromise]);
      setCompareResult(text);
      if (charts) setChartData(charts);
    });
  };

  const handleExport = (content: string, filename: string) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([content], { type: 'text/markdown' }));
    a.download = `${filename}.md`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
  };

  return (
    <div style={{ padding: 22, height: '100%', overflowY: 'auto', fontFamily: FF, background: c.bg }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <p style={{ fontSize: 15, fontWeight: 500, color: c.text, margin: '0 0 2px' }}>Deep analysis</p>
        <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>Generate structured summaries or compare multiple filings.</p>
      </div>

      {/* Mode toggle. On desktop it's a single inline pill row; below the mobile
          breakpoint the four labels can't fit 375px in one row (they overflow to
          ~450px), so it becomes a full-width 2×2 grid with 44px touch targets. */}
      <div
        style={
          isMobile
            ? { display: 'grid', gridTemplateColumns: '1fr 1fr', background: c.surfaceAlt, borderRadius: 8, padding: 3, gap: 2, marginBottom: 20 }
            : { display: 'inline-flex', background: c.surfaceAlt, borderRadius: 8, padding: 3, gap: 2, marginBottom: 20 }
        }
      >
        <button style={modeBtn(mode === 'summary', isMobile)} onClick={() => setMode('summary')}>
          <FileText size={14} />
          Structured summary
        </button>
        <button style={modeBtn(mode === 'compare', isMobile)} onClick={() => setMode('compare')}>
          <GitCompare size={14} />
          Compare documents
        </button>
        <button style={modeBtn(mode === 'forecast', isMobile)} onClick={() => setMode('forecast')}>
          <TrendingUp size={14} />
          Forecast
        </button>
        <button style={modeBtn(mode === 'trends', isMobile)} onClick={() => setMode('trends')}>
          <BarChart3 size={14} />
          Trends
        </button>
      </div>

      {/* Error */}
      {error && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '12px 14px', background: c.negSurface, border: `0.5px solid ${c.negBorder}`, borderRadius: 8, marginBottom: 16, color: c.neg, fontSize: 13 }}>
          <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          {error}
        </div>
      )}

      {/* Summary mode */}
      {mode === 'summary' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px' }}>
            <label style={labelStyle}>Select document to summarize</label>
            <div style={{ display: 'flex', gap: 10 }}>
              <select
                style={{ ...selectStyle, flex: 1 }}
                value={selectedDocForSummary}
                onChange={e => setSelectedDoc(e.target.value)}
                onFocus={e  => (e.target.style.borderColor = c.brand)}
                onBlur={e   => (e.target.style.borderColor = c.border)}
              >
                <option value="">— Select a document —</option>
                {documents.map(d => <option key={d.id} value={d.id}>{d.name}{d.sector ? ` — ${d.sector}` : ''}</option>)}
              </select>
              <button
                onClick={handleGenerateSummary}
                disabled={!selectedDocForSummary || isLoading}
                style={primaryBtn(!selectedDocForSummary || isLoading)}
                onMouseEnter={e => { if (selectedDocForSummary && !isLoading) e.currentTarget.style.background = c.brandDeepHover; }}
                onMouseLeave={e => { if (selectedDocForSummary && !isLoading) e.currentTarget.style.background = c.brandDeep; }}
              >
                {isLoading
                  ? <><Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Generating…</>
                  : <><FileText size={14} /> Generate</>
                }
              </button>
            </div>
          </div>

          {summaryResult && (
            <ResultCard
              content={summaryResult}
              onExport={() => handleExport(summaryResult, 'Summary_Report')}
            />
          )}
        </div>
      )}

      {/* Forecast mode */}
      {mode === 'forecast' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px' }}>
            <label style={labelStyle}>Forecast a company's core metrics</label>
            <div style={{ display: 'flex', gap: 10 }}>
              <select
                style={{ ...selectStyle, flex: 1 }}
                value={forecastDocId}
                onChange={e => setForecastDocId(e.target.value)}
                onFocus={e => (e.target.style.borderColor = c.brand)}
                onBlur={e  => (e.target.style.borderColor = c.border)}
              >
                <option value="">— Select a filing —</option>
                {documents.filter(d => d.ticker).map(d => (
                  <option key={d.id} value={d.id}>{d.name}{d.sector ? ` — ${d.sector}` : ''}</option>
                ))}
              </select>
              <button
                onClick={handleForecast}
                disabled={!forecastDocId || isLoading}
                style={primaryBtn(!forecastDocId || isLoading)}
                onMouseEnter={e => { if (forecastDocId && !isLoading) e.currentTarget.style.background = c.brandDeepHover; }}
                onMouseLeave={e => { if (forecastDocId && !isLoading) e.currentTarget.style.background = c.brandDeep; }}
              >
                {isLoading
                  ? <><Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Forecasting…</>
                  : <><TrendingUp size={14} /> Forecast</>
                }
              </button>
              {(() => {
                const doc = documents.find(d => d.id === forecastDocId);
                return doc?.ticker ? <ExportPdfButton ticker={doc.ticker} /> : null;
              })()}
            </div>
          </div>

          {forecastData && <ForecastPanel data={forecastData} />}
        </div>
      )}

      {/* Trends mode */}
      {mode === 'trends' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px' }}>
            <label style={labelStyle}>Chart a company's multi-year financials</label>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <select
                style={{ ...selectStyle, flex: 1, minWidth: 220 }}
                value={trendsDocId}
                onChange={e => setTrendsDocId(e.target.value)}
                onFocus={e => (e.target.style.borderColor = c.brand)}
                onBlur={e  => (e.target.style.borderColor = c.border)}
              >
                <option value="">— Select a filing —</option>
                {documents.filter(d => d.ticker).map(d => (
                  <option key={d.id} value={d.id}>{d.name}{d.sector ? ` — ${d.sector}` : ''}</option>
                ))}
              </select>
              {(() => {
                const doc = documents.find(d => d.id === trendsDocId);
                // The PDF is the full single-company report (trends + forecast),
                // built server-side from the same numbers/descriptions on screen.
                return doc?.ticker ? <ExportPdfButton ticker={doc.ticker} /> : null;
              })()}
            </div>
          </div>

          {(() => {
            const doc = documents.find(d => d.id === trendsDocId);
            return doc?.ticker ? <TrendsPanel key={doc.ticker} ticker={doc.ticker} /> : null;
          })()}
        </div>
      )}

      {/* Compare mode */}
      {mode === 'compare' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: gridCols(isMobile, 340), gap: 14, marginBottom: 14 }}>

              {/* Document A */}
              <div>
                <label style={labelStyle}>Document A — baseline</label>
                <select
                  style={selectStyle}
                  value={doc1Id}
                  onChange={e => handlePickA(e.target.value)}
                  onFocus={e  => (e.target.style.borderColor = c.brand)}
                  onBlur={e   => (e.target.style.borderColor = c.border)}
                >
                  <option value="">— Select first document —</option>
                  {documents.map(d => <option key={d.id} value={d.id}>{d.name}{d.sector ? ` — ${d.sector}` : ''}</option>)}
                </select>
                {docA?.sector && (
                  <p style={{ fontSize: 11, color: c.textMuted, margin: '6px 0 0' }}>Sector: {docA.sector}</p>
                )}
              </div>

              {/* Document B — grouped same-sector first */}
              <div>
                <label style={labelStyle}>Document B — comparison</label>
                <select
                  style={selectStyle}
                  value={doc2Id}
                  onChange={e => setDoc2Id(e.target.value)}
                  onFocus={e  => (e.target.style.borderColor = c.brand)}
                  onBlur={e   => (e.target.style.borderColor = c.border)}
                >
                  <option value="">— Select second document —</option>
                  {aSector ? (
                    <>
                      {sameSector.length > 0 && (
                        <optgroup label={`Same sector — ${aSector}`}>
                          {sameSector.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                        </optgroup>
                      )}
                      {otherSector.length > 0 && (
                        <optgroup label="Other sectors">
                          {otherSector.map(d => <option key={d.id} value={d.id}>{d.name}{d.sector ? ` — ${d.sector}` : ''}</option>)}
                        </optgroup>
                      )}
                    </>
                  ) : (
                    bCandidates.map(d => <option key={d.id} value={d.id}>{d.name}{d.sector ? ` — ${d.sector}` : ''}</option>)
                  )}
                </select>
                {docB?.sector && (
                  <p style={{ fontSize: 11, color: c.textMuted, margin: '6px 0 0' }}>Sector: {docB.sector}</p>
                )}
              </div>
            </div>

            {sectorMismatch && (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 14px', background: c.warnSurface, border: `0.5px solid ${c.warnBorder}`, borderRadius: 8, marginBottom: 14, color: c.warnFg, fontSize: 13, lineHeight: 1.55 }}>
                <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                <span>
                  <strong>Cross-sector comparison blocked.</strong> {docA?.sector} vs {docB?.sector} — margins, turnover ratios, and risk factors differ structurally across sectors and would produce misleading results. Select two companies in the same sector to proceed.
                </span>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={handleCompare}
                disabled={!doc1Id || !doc2Id || doc1Id === doc2Id || isLoading || sectorMismatch}
                style={primaryBtn(!doc1Id || !doc2Id || doc1Id === doc2Id || isLoading || sectorMismatch)}
                onMouseEnter={e => { if (doc1Id && doc2Id && doc1Id !== doc2Id && !isLoading && !sectorMismatch) e.currentTarget.style.background = c.brandDeepHover; }}
                onMouseLeave={e => { if (doc1Id && doc2Id && doc1Id !== doc2Id && !isLoading && !sectorMismatch) e.currentTarget.style.background = c.brandDeep; }}
              >
                {isLoading
                  ? <><Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Comparing…</>
                  : <><GitCompare size={14} /> Compare documents</>
                }
              </button>
            </div>
          </div>

          {chartData && <CompareCharts data={chartData} />}

          {compareResult && (
            <ResultCard
              content={compareResult}
              onExport={() => handleExport(compareResult, 'Comparison_Report')}
            />
          )}
        </div>
      )}

    </div>
  );
};

// ── Result card ───────────────────────────────────────────────────────────

const ResultCard: React.FC<{
  content: string;
  onExport: () => void;
}> = ({ content, onExport }) => {
  const [exportHovered, setExportHovered] = useState(false);
  const rendered = useMemo(() => renderMarkdown(content), [content]);

  return (
    <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '18px 20px', position: 'relative' }}>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <p style={{ fontSize: 11, color: c.textFaint, textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
          AI-generated analysis <span style={{ marginLeft: 4 }}>· grounded in your filings</span>
        </p>
        <button
          onClick={onExport}
          onMouseEnter={() => setExportHovered(true)}
          onMouseLeave={() => setExportHovered(false)}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            fontSize: 12, padding: '4px 10px', borderRadius: 6,
            border: `0.5px solid ${c.border}`,
            background: exportHovered ? c.surface : c.bg,
            color: exportHovered ? c.brand : c.textMuted,
            cursor: 'pointer', fontFamily: font.ui,
            transition: 'background 0.1s, color 0.1s',
          }}
        >
          <Download size={13} /> Export .md
        </button>
      </div>

      <div style={{ fontFamily: font.prose, fontSize: 13, lineHeight: 1.75, color: c.text2 }}>
        {rendered}
      </div>
    </div>
  );
};

export default AnalysisView;
