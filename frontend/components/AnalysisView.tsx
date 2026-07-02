import React, { useState, useMemo } from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import { FileText, GitCompare, Download, Loader2, AlertCircle, AlertTriangle } from 'lucide-react';
import { Document } from '../types';
import { generateSummary, compareDocuments, fetchCompareMetrics, CompareMetricsResult } from '../services/gemini';
import { c, font } from '../theme';

interface AnalysisViewProps {
  documents: Document[];
}

const FF = font.ui;

const btn = (active: boolean): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '7px 16px', borderRadius: 7, fontSize: 13,
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
        <table key={`tbl-${i}`} style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 14 }}>
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

const COL_A = c.brandDeep;
const COL_B = c.accent;

const xAxisProps = {
  dataKey: 'year' as const,
  tick: { fontSize: 11, fill: c.textFaint },
  tickLine: false,
  axisLine: { stroke: c.border },
};

const yAxisBase = {
  tick: { fontSize: 11, fill: c.textFaint },
  tickLine: false,
  axisLine: false as const,
};

const gridProps = {
  stroke: c.border,
  strokeDasharray: '3 3' as const,
  vertical: false,
};

const tooltipStyle = {
  contentStyle: {
    fontSize: 12, borderRadius: 8, border: `0.5px solid ${c.border}`,
    fontFamily: FF, background: c.bg,
  },
  cursor: { fill: c.surface },
};

const fmtM  = (v: number | null | undefined): string => {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
};
const fmtPct   = (v: number | null | undefined): string => v == null ? '—' : `${v.toFixed(1)}%`;
const fmtRatio = (v: number | null | undefined): string => v == null ? '—' : v.toFixed(2);

const ChartPanel: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '14px 16px' }}>
    <p style={{ fontSize: 11, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 10px', fontFamily: FF }}>{title}</p>
    {children}
  </div>
);

const CompareCharts: React.FC<{ data: CompareMetricsResult }> = ({ data }) => {
  const { a: ta, b: tb } = data.tickers;

  const legendFmt = (val: string) => val === 'a' ? ta : tb;
  const legendProps = {
    formatter: legendFmt,
    iconType: 'circle' as const,
    iconSize: 8,
    wrapperStyle: { fontSize: 12, fontFamily: FF },
  };

  const mkTooltip = (fmt: (v: number | null) => string) => ({
    ...tooltipStyle,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    formatter: (v: any, name: any) => [fmt(v as number | null), (name as string) === 'a' ? ta : tb],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    labelFormatter: (yr: any) => `FY ${yr}`,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Row 1: Revenue | Net Income */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <ChartPanel title="Revenue">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={data.revenue} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisBase} width={56} tickFormatter={v => fmtM(v).replace('$', '')} />
              <Tooltip {...mkTooltip(fmtM)} />
              <Legend {...legendProps} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Net Income">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={data.net_income} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisBase} width={56} tickFormatter={v => fmtM(v).replace('$', '')} />
              <Tooltip {...mkTooltip(fmtM)} />
              <Legend {...legendProps} />
              <ReferenceLine y={0} stroke={c.border} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

      {/* Row 2: Gross Margin | Operating Margin | Net Margin */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        {(
          [
            ['gross_margin_pct',     'Gross Margin %'],
            ['operating_margin_pct', 'Operating Margin %'],
            ['net_margin_pct',       'Net Margin %'],
          ] as const
        ).map(([key, label]) => (
          <ChartPanel key={key} title={label}>
            <ResponsiveContainer width="100%" height={165}>
              <LineChart data={data[key]} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid {...gridProps} />
                <XAxis {...xAxisProps} />
                <YAxis {...yAxisBase} width={40} tickFormatter={v => `${v}%`} />
                <Tooltip {...mkTooltip(fmtPct)} />
                <Legend {...legendProps} />
                <ReferenceLine y={0} stroke={c.border} />
                <Line type="monotone" dataKey="a" stroke={COL_A} strokeWidth={2} dot={false} connectNulls name="a" />
                <Line type="monotone" dataKey="b" stroke={COL_B} strokeWidth={2} dot={false} connectNulls name="b" />
              </LineChart>
            </ResponsiveContainer>
          </ChartPanel>
        ))}
      </div>

      {/* Row 3: Revenue Growth | Free Cash Flow */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <ChartPanel title="Revenue Growth %">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.revenue_growth_pct} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisBase} width={44} tickFormatter={v => `${v}%`} />
              <Tooltip {...mkTooltip(fmtPct)} />
              <Legend {...legendProps} />
              <ReferenceLine y={0} stroke={c.border} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Free Cash Flow">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.free_cash_flow} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisBase} width={56} tickFormatter={v => fmtM(v).replace('$', '')} />
              <Tooltip {...mkTooltip(fmtM)} />
              <Legend {...legendProps} />
              <ReferenceLine y={0} stroke={c.border} />
              <Bar dataKey="a" fill={COL_A} radius={[3, 3, 0, 0]} maxBarSize={22} name="a" />
              <Bar dataKey="b" fill={COL_B} radius={[3, 3, 0, 0]} maxBarSize={22} name="b" />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

      {/* Row 4: Debt-to-Equity | Current Ratio */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <ChartPanel title="Debt-to-Equity">
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data.debt_to_equity} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisBase} width={40} tickFormatter={fmtRatio} />
              <Tooltip {...mkTooltip(fmtRatio)} />
              <Legend {...legendProps} />
              <Line type="monotone" dataKey="a" stroke={COL_A} strokeWidth={2} dot={false} connectNulls name="a" />
              <Line type="monotone" dataKey="b" stroke={COL_B} strokeWidth={2} dot={false} connectNulls name="b" />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Current Ratio">
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data.current_ratio} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisBase} width={40} tickFormatter={fmtRatio} />
              <Tooltip {...mkTooltip(fmtRatio)} />
              <Legend {...legendProps} />
              <ReferenceLine y={1} stroke={c.border} strokeDasharray="4 4" />
              <Line type="monotone" dataKey="a" stroke={COL_A} strokeWidth={2} dot={false} connectNulls name="a" />
              <Line type="monotone" dataKey="b" stroke={COL_B} strokeWidth={2} dot={false} connectNulls name="b" />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────

const AnalysisView: React.FC<AnalysisViewProps> = ({ documents }) => {
  const [mode, setMode]                           = useState<'summary' | 'compare'>('summary');
  const [selectedDocForSummary, setSelectedDoc]   = useState('');
  const [summaryResult, setSummaryResult]         = useState('');
  const [doc1Id, setDoc1Id]                       = useState('');
  const [doc2Id, setDoc2Id]                       = useState('');
  const [compareResult, setCompareResult]         = useState('');
  const [chartData, setChartData]                 = useState<CompareMetricsResult | null>(null);
  const [isLoading, setIsLoading]                 = useState(false);
  const [error, setError]                         = useState<string | null>(null);

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

      {/* Mode toggle */}
      <div style={{ display: 'inline-flex', background: c.surfaceAlt, borderRadius: 8, padding: 3, gap: 2, marginBottom: 20 }}>
        <button style={btn(mode === 'summary')} onClick={() => setMode('summary')}>
          <FileText size={14} />
          Structured summary
        </button>
        <button style={btn(mode === 'compare')} onClick={() => setMode('compare')}>
          <GitCompare size={14} />
          Compare documents
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

      {/* Compare mode */}
      {mode === 'compare' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>

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
