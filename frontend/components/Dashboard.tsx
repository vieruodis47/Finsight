import React, { useState, useEffect } from 'react';
import { LineChart as LineChartIcon, Loader2 } from 'lucide-react';
import {
  LineChart as RechartsLineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts';
import { Document } from '../types';
import { c, font } from '../theme';
import CompanyLogo from './CompanyLogo';
import { fetchMarketData, MarketResponse } from '../services/gemini';

interface DashboardProps {
  documents: Document[];
  // Ticker (or name) key of the company to show, uppercased. When omitted,
  // falls back to the most recently added filing.
  selectedTicker?: string | null;
}

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
  height: 150, display: 'flex', flexDirection: 'column', alignItems: 'center',
  justifyContent: 'center', gap: 8, color: c.textFaint, fontSize: 12, textAlign: 'center',
};

const MetricCard: React.FC<{ label: string; value: string; note?: string }> = ({ label, value, note }) => (
  <div style={card}>
    <p style={lbl}>{label}</p>
    <p style={bigNum}>{value}</p>
    {note && <p style={sub}>{note}</p>}
  </div>
);

// Small label/value row used inside the market snapshot.
const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0', borderBottom: `0.5px solid ${c.borderFaint}` }}>
    <span style={{ color: c.textMuted }}>{label}</span>
    <span style={{ color: c.text, fontWeight: 500 }}>{value}</span>
  </div>
);

const companyKey = (d: Document) => (d.ticker || d.name).toUpperCase();

// --- Component ---------------------------------------------------------------

const Dashboard: React.FC<DashboardProps> = ({ documents, selectedTicker }) => {
  const forTicker = selectedTicker
    ? documents.filter(d => companyKey(d) === selectedTicker.toUpperCase())
    : documents;
  const doc = forTicker.find(d => d.form === '10-K') ?? forTicker[0] ?? documents[0];

  const ticker = doc?.ticker || doc?.name?.match(/^([A-Za-z]{1,5})/)?.[1]?.toUpperCase();
  const name = doc?.name ?? 'No company selected';
  const meta = [doc?.form, doc?.sector, doc?.uploadDate && `added ${doc.uploadDate}`].filter(Boolean).join(' · ');

  const m   = doc?.metrics;
  const inc = m?.income_statement;
  const bal = m?.balance_sheet;
  const cf  = m?.cash_flow;
  const rev = inc?.total_revenue_millions;

  // Margins — single-period, all derivable from one filing.
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

  // --- Market data (yfinance via /market), fetched per selected company ------
  const [market, setMarket] = useState<{ data: MarketResponse | null; loading: boolean; error: string | null }>(
    { data: null, loading: false, error: null }
  );

  useEffect(() => {
    if (!ticker) { setMarket({ data: null, loading: false, error: null }); return; }
    let cancelled = false;
    setMarket({ data: null, loading: true, error: null });
    fetchMarketData(ticker, '1y')
      .then(d => { if (!cancelled) setMarket({ data: d, loading: false, error: null }); })
      .catch(e => { if (!cancelled) setMarket({ data: null, loading: false, error: e instanceof Error ? e.message : 'Market data unavailable' }); });
    return () => { cancelled = true; };
  }, [ticker]);

  const snap = market.data?.snapshot;
  const change = snap?.change_pct;

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

      {!m && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', background: c.surface, borderRadius: 8, marginBottom: 16, fontSize: 13, color: c.textMuted }}>
          <LineChartIcon size={15} />
          Filing fundamentals will appear once this company's XBRL data is fetched from EDGAR.
        </div>
      )}

      {/* Filing fundamentals — from the extractor */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        <MetricCard label="Revenue"          value={fmtUSD(rev)} />
        <MetricCard label="Gross margin"     value={fmtPct(grossPct)} note={inc?.gross_margin_millions != null ? `${fmtUSD(inc.gross_margin_millions)} gross profit` : undefined} />
        <MetricCard label="Operating income" value={fmtUSD(inc?.operating_income_millions)} note={opPct != null ? `${fmtPct(opPct)} margin` : undefined} />
        <MetricCard label="Net income"       value={fmtUSD(inc?.net_income_millions)} note={netPct != null ? `${fmtPct(netPct)} margin` : undefined} />
        <MetricCard label="EPS (diluted)"    value={fmtEps(inc?.eps_diluted ?? inc?.eps_basic)} />
        <MetricCard label="Free cash flow"   value={fmtUSD(cf?.free_cash_flow_millions)} note={fcfPct != null ? `${fmtPct(fcfPct)} margin` : undefined} />
        <MetricCard label="Total assets"     value={fmtUSD(bal?.total_assets_millions)} />
        <MetricCard label="Cash & equiv."    value={fmtUSD(bal?.cash_and_equivalents_millions)} />
      </div>

      {/* Margin breakdown (filled) + Market snapshot (live) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>

        <div style={panel}>
          <p style={panelTitle}>Margin breakdown</p>
          {margins.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
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
        </div>

        {/* Market snapshot — live from yfinance */}
        <div style={panel}>
          <p style={panelTitle}>Market snapshot</p>
          {market.loading ? (
            <div style={centered}>
              <Loader2 size={18} color={c.textFaint} style={{ animation: 'spin 1s linear infinite' }} />
              Loading market data…
            </div>
          ) : snap ? (
            <div>
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
            <div style={centered}>{market.error ?? 'Market data unavailable.'}</div>
          )}
        </div>
      </div>

      {/* Price history — live from yfinance */}
      <div style={panel}>
        <p style={panelTitle}>{ticker ?? 'Price'} price history</p>
        {market.loading ? (
          <div style={centered}>
            <Loader2 size={18} color={c.textFaint} style={{ animation: 'spin 1s linear infinite' }} />
            Loading price history…
          </div>
        ) : market.data && market.data.history.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <RechartsLineChart data={market.data.history} margin={{ top: 5, right: 12, left: 0, bottom: 0 }}>
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: c.textFaint }}
                tickLine={false}
                axisLine={{ stroke: c.border }}
                minTickGap={48}
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
            {market.error ?? 'Price history unavailable.'}
          </div>
        )}
      </div>

    </div>
  );
};

export default Dashboard;
