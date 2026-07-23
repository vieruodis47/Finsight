import React, { useState, useEffect } from 'react';
import { LineChart as LineChartIcon, AlertTriangle, RotateCw } from 'lucide-react';
import {
  LineChart as RechartsLineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts';
import { Document, FilingMetrics } from '../types';
import { c, font } from '../theme';
import CompanyLogo from './CompanyLogo';
import BirdLoader from './BirdLoader';
import { fetchMarketData, fetchMetrics, MarketResponse } from '../services/gemini';
import { companyKey } from '../utils/company';
import { useIsMobile } from '../utils/hooks';
import { gridCols } from '../utils/chart';

interface DashboardProps {
  documents: Document[];
  // Ticker (or name) key of the company to show, uppercased. When omitted,
  // falls back to the most recently added filing.
  selectedTicker?: string | null;
}

// Every widget is one of these at any moment. Loading → its own bird; error →
// its own retry (never an infinite bird); loaded/idle → content.
type Status = 'idle' | 'loading' | 'loaded' | 'error';
interface Async<T> { status: Status; data: T | null; error: string | null; }

// --- Formatting helpers ------------------------------------------------------

// Filing values arrive in millions of USD.
const fmtUSD = (m?: number): string => {
  if (m == null) return '—';
  const a = Math.abs(m);
  if (a >= 1_000_000) return `$${(m / 1_000_000).toFixed(2)}T`;
  if (a >= 1_000)     return `$${(m / 1_000).toFixed(1)}B`;
  return `$${Math.round(m).toLocaleString()}M`;
};

const fmtMoney = (n?: number): string => {
  if (n == null) return '—';
  const a = Math.abs(n);
  if (a >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6)  return `$${(n / 1e6).toFixed(1)}M`;
  return `$${Math.round(n).toLocaleString()}`;
};

const fmtNum = (n?: number): string => {
  if (n == null) return '—';
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return `${Math.round(n)}`;
};

const fmtPrice = (n?: number): string => (n == null ? '—' : `$${n.toFixed(2)}`);
const fmtPct   = (p?: number): string => (p == null ? '—' : `${p.toFixed(1)}%`);
const fmtEps   = (e?: number): string => (e == null ? '—' : `$${e.toFixed(2)}`);
const fmtRatio = (r?: number): string => (r == null ? '—' : r.toFixed(1));

const pctOf = (part?: number, whole?: number): number | undefined =>
  part != null && whole ? (part / whole) * 100 : undefined;

// --- Styles ------------------------------------------------------------------

const card: React.CSSProperties = {
  background: c.surface, borderRadius: 8, padding: '13px 15px',
};
const panel: React.CSSProperties = {
  background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 12, padding: '14px 16px',
};
const lbl: React.CSSProperties = {
  fontSize: 11, color: c.textFaint, textTransform: 'uppercase', letterSpacing: '0.04em', margin: '0 0 4px',
};
const bigNum: React.CSSProperties = { fontSize: 22, fontWeight: 500, color: c.text, margin: 0 };
const sub: React.CSSProperties = { fontSize: 12, color: c.textMuted, margin: '3px 0 0' };
const panelTitle: React.CSSProperties = { fontSize: 13, fontWeight: 500, color: c.text, margin: '0 0 14px' };
const centered: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center',
  justifyContent: 'center', gap: 8, color: c.textFaint, fontSize: 12, textAlign: 'center',
};

// Reserved footprints so a widget never changes height when its bird is swapped
// for content (no layout shift). Each is set to (or just above) the TALLEST
// loaded state so the reserve always dominates in both states: the KPI card
// covers a card with a "…% margin" note, and the panel body covers the market
// snapshot (price + five stat rows), which is the tallest panel.
const CARD_H  = 104;
const PANEL_H = 212;
const CHART_H = 240;

// A metric card: sm bird while its (shared) fundamentals fetch is in flight,
// otherwise the value. On error it shows an em-dash placeholder — the single
// retry lives in the banner above the grid, so we don't stack 8 retry buttons.
const MetricCard: React.FC<{ label: string; value: string; note?: string; loading: boolean; delayMs?: number }> =
  ({ label, value, note, loading, delayMs }) => (
    <div style={{ ...card, minHeight: CARD_H, display: 'flex', flexDirection: 'column', justifyContent: loading ? 'center' : 'flex-start', alignItems: loading ? 'center' : 'stretch' }}>
      {loading ? (
        <BirdLoader variant="sm" ariaLabel={`Loading ${label.toLowerCase()}`} delayMs={delayMs} />
      ) : (
        <>
          <p style={lbl}>{label}</p>
          <p style={bigNum}>{value}</p>
          {note && <p style={sub}>{note}</p>}
        </>
      )}
    </div>
  );

// Small label/value row used inside the market snapshot.
const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0', borderBottom: `0.5px solid ${c.borderFaint}` }}>
    <span style={{ color: c.textMuted }}>{label}</span>
    <span style={{ color: c.text, fontWeight: 500 }}>{value}</span>
  </div>
);

// In-panel error + retry — replaces the bird so a failed fetch never spins forever.
const RetryBox: React.FC<{ label: string; onRetry: () => void }> = ({ label, onRetry }) => (
  <div style={{ ...centered, gap: 10 }} role="alert">
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: c.textMuted }}>
      <AlertTriangle size={14} color={c.neg} /> {label}
    </span>
    <button
      onClick={onRetry}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer',
        fontSize: 12, fontFamily: font.ui, color: c.brandDeep, fontWeight: 500,
        background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 7, padding: '5px 11px',
      }}
    >
      <RotateCw size={13} /> Retry
    </button>
  </div>
);

// Fixed-height panel body: renders the bird / retry / content for one widget so
// loading→loaded never shifts layout.
const PanelBody: React.FC<{
  state: Async<unknown>; minHeight: number; ariaLabel: string; label?: string;
  onRetry: () => void; children: React.ReactNode;
}> = ({ state, minHeight, ariaLabel, label, onRetry, children }) => (
  <div style={{ minHeight, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
    {state.status === 'loading' ? (
      <div style={centered}><BirdLoader variant="full" ariaLabel={ariaLabel} label={label} /></div>
    ) : state.status === 'error' ? (
      <RetryBox label={state.error ?? 'Something went wrong'} onRetry={onRetry} />
    ) : (
      children
    )}
  </div>
);

// --- Component ---------------------------------------------------------------

const Dashboard: React.FC<DashboardProps> = ({ documents, selectedTicker }) => {
  const isMobile = useIsMobile();
  const forTicker = selectedTicker
    ? documents.filter(d => companyKey(d) === selectedTicker.toUpperCase())
    : documents;
  const doc = forTicker.find(d => d.form === '10-K') ?? forTicker[0] ?? documents[0];

  const ticker = doc?.ticker || doc?.name?.match(/^([A-Za-z]{1,5})/)?.[1]?.toUpperCase();
  const name = doc?.name ?? 'No company selected';
  const meta = [doc?.form, doc?.sector, doc?.uploadDate && `added ${doc.uploadDate}`].filter(Boolean).join(' · ');

  // ── Two independent per-widget fetches, keyed on the selected company ───────
  // Fundamentals (8 KPI cards + margin breakdown) come from /metrics; market
  // snapshot + price history come from /market. Separate fetches + separate
  // retry tokens mean a slow chart never blocks the cards, and each widget owns
  // its loading/loaded/error state. Retrying bumps a token to re-run the effect.
  const [metrics, setMetrics] = useState<Async<FilingMetrics>>({ status: 'idle', data: null, error: null });
  const [market, setMarket]   = useState<Async<MarketResponse>>({ status: 'idle', data: null, error: null });
  const [metricsToken, setMetricsToken] = useState(0);
  const [marketToken, setMarketToken]   = useState(0);
  const reloadMetrics = () => setMetricsToken(t => t + 1);
  const reloadMarket  = () => setMarketToken(t => t + 1);

  // Fundamentals: fetch fresh for the ticker; fall back to metrics already on the
  // doc (uploaded filings carry their own and may have no ticker to fetch by).
  useEffect(() => {
    const seed = doc?.metrics ?? null;
    if (!ticker) {
      setMetrics(seed ? { status: 'loaded', data: seed, error: null } : { status: 'idle', data: null, error: null });
      return;
    }
    let cancelled = false;
    setMetrics({ status: 'loading', data: null, error: null });
    fetchMetrics(ticker)
      .then(r => {
        if (cancelled) return;
        const data = r?.metrics ?? seed;
        setMetrics(data
          ? { status: 'loaded', data, error: null }
          : { status: 'error', data: null, error: 'Fundamentals unavailable' });
      })
      .catch(e => {
        if (!cancelled) setMetrics({ status: 'error', data: null, error: e instanceof Error ? e.message : 'Failed to load fundamentals' });
      });
    return () => { cancelled = true; };
  }, [ticker, doc?.id, metricsToken]);

  // Market: yfinance snapshot + 1y history via /market.
  useEffect(() => {
    if (!ticker) { setMarket({ status: 'idle', data: null, error: null }); return; }
    let cancelled = false;
    setMarket({ status: 'loading', data: null, error: null });
    fetchMarketData(ticker, '1y')
      .then(d => { if (!cancelled) setMarket({ status: 'loaded', data: d, error: null }); })
      .catch(e => { if (!cancelled) setMarket({ status: 'error', data: null, error: e instanceof Error ? e.message : 'Market data unavailable' }); });
    return () => { cancelled = true; };
  }, [ticker, marketToken]);

  const m   = metrics.data;
  const inc = m?.income_statement;
  const bal = m?.balance_sheet;
  const cf  = m?.cash_flow;
  const rev = inc?.total_revenue_millions;

  const snap = market.data?.snapshot;
  const change = snap?.change_pct;
  const kpiLoading = metrics.status === 'loading';

  // Margins — single-period, all derivable from the fundamentals.
  const grossPct = inc?.gross_margin_pct ?? pctOf(inc?.gross_margin_millions, rev);
  const opPct    = pctOf(inc?.operating_income_millions, rev);
  const netPct   = pctOf(inc?.net_income_millions, rev);
  const fcfPct   = pctOf(cf?.free_cash_flow_millions, rev);

  const margins = ([
    { name: 'Gross margin',     value: grossPct, color: c.brandDeep },
    { name: 'Operating margin', value: opPct,    color: c.brand },
    { name: 'Net margin',       value: netPct,   color: c.brandLight },
    { name: 'FCF margin',       value: fcfPct,   color: c.accent },
  ].filter(x => x.value != null)) as { name: string; value: number; color: string }[];

  // KPI cards — explicit, statement-grouped order (NOT data-arrival order), so
  // the grid shape is fixed. Row 1 = income statement, row 2 = per-share / cash
  // / balance sheet. Missing values render an em-dash (via the fmt* helpers) so
  // every card is always present and the 4×2 grid never collapses.
  const KPIS: { label: string; value: string; note?: string }[] = [
    // Row 1 — income statement
    { label: 'Revenue',          value: fmtUSD(rev) },
    { label: 'Gross margin',     value: fmtPct(grossPct), note: inc?.gross_margin_millions != null ? `${fmtUSD(inc.gross_margin_millions)} gross profit` : undefined },
    { label: 'Operating income', value: fmtUSD(inc?.operating_income_millions), note: opPct != null ? `${fmtPct(opPct)} margin` : undefined },
    { label: 'Net income',       value: fmtUSD(inc?.net_income_millions), note: netPct != null ? `${fmtPct(netPct)} margin` : undefined },
    // Row 2 — per-share / cash / balance sheet
    { label: 'EPS (diluted)',    value: fmtEps(inc?.eps_diluted ?? inc?.eps_basic) },
    { label: 'Free cash flow',   value: fmtUSD(cf?.free_cash_flow_millions), note: fcfPct != null ? `${fmtPct(fcfPct)} margin` : undefined },
    { label: 'Total assets',     value: fmtUSD(bal?.total_assets_millions) },
    { label: 'Cash & equiv.',    value: fmtUSD(bal?.cash_and_equivalents_millions) },
  ];

  return (
    <div style={{ padding: 22, height: '100%', overflowY: 'auto', fontFamily: font.ui }}>

      {/* Header — real identity */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <CompanyLogo ticker={ticker} website={snap?.website} size={42} radius={8} />
        <div>
          <p style={{ fontSize: 16, fontWeight: 500, color: c.text, margin: 0 }}>{name}</p>
          <p style={{ fontSize: 12, color: c.textMuted, margin: 0 }}>{meta || 'Financial research workspace'}</p>
        </div>
      </div>

      {/* Fundamentals status: gentle hint when nothing to load yet; a single
          retry banner when the shared /metrics fetch failed (not 8 retries). */}
      {metrics.status === 'idle' && !m && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', background: c.surface, borderRadius: 8, marginBottom: 16, fontSize: 13, color: c.textMuted }}>
          <LineChartIcon size={15} />
          Filing fundamentals will appear once this company's XBRL data is fetched from EDGAR.
        </div>
      )}
      {metrics.status === 'error' && (
        <div role="alert" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '10px 14px', background: c.surface, borderRadius: 8, marginBottom: 16, fontSize: 13, color: c.textMuted }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={15} color={c.neg} />
            Couldn't load filing fundamentals.
          </span>
          <button
            onClick={reloadMetrics}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, fontFamily: font.ui, color: c.brandDeep, fontWeight: 500, background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 7, padding: '5px 11px' }}
          >
            <RotateCw size={13} /> Retry
          </button>
        </div>
      )}

      {/* Filing fundamentals — fixed 4-col grid (2-col below 768px, see .kpi-grid
          in index.html). Each card shows its own sm bird while the shared
          fundamentals fetch is in flight, then swaps to its value. */}
      <div className="kpi-grid" style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
        {KPIS.map((k, i) => (
          <MetricCard
            key={k.label}
            label={k.label}
            value={k.value}
            note={k.note}
            loading={kpiLoading}
            delayMs={(i * 70) % 360}
          />
        ))}
      </div>

      {/* Margin breakdown (fundamentals) + Market snapshot (live) */}
      <div style={{ display: 'grid', gridTemplateColumns: gridCols(isMobile, 340), gap: 12, marginBottom: 12 }}>

        <div style={panel}>
          <p style={panelTitle}>Margin breakdown</p>
          <PanelBody state={metrics} minHeight={PANEL_H} ariaLabel="Loading margin breakdown" onRetry={reloadMetrics}>
            {margins.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
                {margins.map(({ name: n, value, color }) => (
                  <div key={n}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                      <span style={{ color: c.textMuted }}>{n}</span>
                      <span style={{ fontWeight: 500, color: c.text }}>{value.toFixed(1)}%</span>
                    </div>
                    <div style={{ height: 7, background: c.borderFaint, borderRadius: 4, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, value))}%`, background: color, borderRadius: 4 }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={centered}>Margin data not available for this filing.</div>
            )}
          </PanelBody>
        </div>

        {/* Market snapshot — live from yfinance */}
        <div style={panel}>
          <p style={panelTitle}>Market snapshot</p>
          <PanelBody state={market} minHeight={PANEL_H} ariaLabel="Loading market snapshot" label="Loading market data…" onRetry={reloadMarket}>
            {snap ? (
              <div style={{ width: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
                  <span style={{ fontSize: 26, fontWeight: 600, color: c.text }}>{fmtPrice(snap.price)}</span>
                  {change != null && (
                    <span style={{ fontSize: 13, fontWeight: 500, color: change >= 0 ? c.pos : c.neg }}>
                      {change >= 0 ? '▲' : '▼'} {Math.abs(change).toFixed(2)}%
                    </span>
                  )}
                </div>
                <Stat label="Market cap"  value={fmtMoney(snap.market_cap)} />
                <Stat label="Volume"      value={fmtNum(snap.volume)} />
                <Stat label="52W high"    value={fmtPrice(snap.high_52w)} />
                <Stat label="52W low"     value={fmtPrice(snap.low_52w)} />
                <Stat label="P/E (ttm)"   value={fmtRatio(snap.pe_ratio)} />
              </div>
            ) : (
              <div style={centered}>Market data unavailable.</div>
            )}
          </PanelBody>
        </div>
      </div>

      {/* Price history — live from yfinance */}
      <div style={panel}>
        <p style={panelTitle}>{ticker ?? 'Price'} price history</p>
        <PanelBody state={market} minHeight={CHART_H} ariaLabel="Loading price history" label="Loading price history…" onRetry={reloadMarket}>
          {market.data && market.data.history.length > 0 ? (
            <ResponsiveContainer width="100%" height={CHART_H}>
              <RechartsLineChart data={market.data.history} margin={{ top: 5, right: 12, left: 0, bottom: 0 }}>
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: c.textFaint }}
                  tickLine={false}
                  axisLine={{ stroke: c.border }}
                  minTickGap={isMobile ? 72 : 48}
                  tickFormatter={(d) => String(d).slice(0, 7)}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: c.textFaint }}
                  tickLine={false}
                  axisLine={{ stroke: c.border }}
                  width={52}
                  domain={['auto', 'auto']}
                  tickFormatter={(v) => `$${Number(v).toFixed(0)}`}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: `0.5px solid ${c.border}`, fontFamily: font.ui }}
                  labelStyle={{ color: c.textMuted }}
                  formatter={(v) => [`$${Number(v).toFixed(2)}`, 'Close']}
                />
                <Line type="monotone" dataKey="close" stroke={c.brand} strokeWidth={2} dot={false} />
              </RechartsLineChart>
            </ResponsiveContainer>
          ) : (
            <div style={centered}>
              <LineChartIcon size={18} color={c.textFaint} />
              Price history unavailable.
            </div>
          )}
        </PanelBody>
      </div>

    </div>
  );
};

export default Dashboard;
