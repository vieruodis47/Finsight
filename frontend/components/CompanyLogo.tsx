import React, { useState, useEffect } from 'react';
import { Building2 } from 'lucide-react';
import { c } from '../theme';

// Fast-path fallback for companies whose yfinance website field is absent or
// slow to arrive. Extend freely; anything not listed will use the domain
// from the market API once it loads.
const TICKER_DOMAINS: Record<string, string> = {
  AAPL: 'apple.com',    MSFT: 'microsoft.com', NVDA: 'nvidia.com',
  GOOGL: 'google.com',  GOOG: 'google.com',    AMZN: 'amazon.com',
  META: 'meta.com',     TSLA: 'tesla.com',     NFLX: 'netflix.com',
  NKE: 'nike.com',      GPS: 'gap.com',        PVH: 'pvh.com',     AEO: 'ae.com',
  LULU: 'lululemon.com', UAA: 'underarmour.com', DECK: 'deckers.com', CROX: 'crocs.com',
  WMT: 'walmart.com',  TGT: 'target.com',     COST: 'costco.com',
  DIS: 'disney.com',   SBUX: 'starbucks.com', MCD: 'mcdonalds.com',
  KO: 'coca-cola.com', PEP: 'pepsico.com',
  INTC: 'intel.com',   AMD: 'amd.com',        IBM: 'ibm.com',
  CRM: 'salesforce.com', ORCL: 'oracle.com',  ADBE: 'adobe.com',
  V: 'visa.com',       MA: 'mastercard.com',  JPM: 'jpmorganchase.com', BAC: 'bankofamerica.com',
};

const googleFavicon = (domain: string) =>
  `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;

interface CompanyLogoProps {
  ticker?: string;
  /** Hostname from the market API (e.g. "www.costco.com"). Takes priority over the hardcoded map. */
  website?: string;
  size?: number;
  radius?: number;
}

const CompanyLogo: React.FC<CompanyLogoProps> = ({ ticker, website, size = 42, radius = 8 }) => {
  const domain = website || (ticker ? TICKER_DOMAINS[ticker.toUpperCase()] : undefined);
  const [failed, setFailed] = useState(false);

  // Reset failed state when the domain changes (e.g. market data arrives after mount).
  useEffect(() => { setFailed(false); }, [domain]);

  const base: React.CSSProperties = {
    width: size, height: size, borderRadius: radius, flexShrink: 0,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  };

  if (domain && !failed) {
    return (
      <div style={{ ...base, background: c.bg, border: `0.5px solid ${c.border}`, overflow: 'hidden' }}>
        <img
          src={googleFavicon(domain)}
          alt={ticker || domain}
          onError={() => setFailed(true)}
          style={{ width: '68%', height: '68%', objectFit: 'contain' }}
        />
      </div>
    );
  }

  if (ticker) {
    return (
      <div style={{ ...base, background: c.brandTint }}>
        <span style={{ fontSize: Math.round(size * 0.31), fontWeight: 500, color: c.brand }}>
          {ticker}
        </span>
      </div>
    );
  }

  return (
    <div style={{ ...base, background: c.surfaceAlt }}>
      <Building2 size={Math.round(size * 0.43)} color={c.textMuted} />
    </div>
  );
};

export default CompanyLogo;
