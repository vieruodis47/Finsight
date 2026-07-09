/**
 * Shared company/ticker utilities used across multiple components.
 * Single source of truth for ticker → name and ticker → domain maps.
 */

import type { Document } from '../types';

// ---------------------------------------------------------------------------
// Key derivation
// ---------------------------------------------------------------------------

/** Stable dedup key for a document: ticker or name, uppercased. */
export const companyKey = (d: Document): string =>
  (d.ticker || d.name).toUpperCase();

// ---------------------------------------------------------------------------
// Display names
// ---------------------------------------------------------------------------

export const TICKER_NAMES: Record<string, string> = {
  AAPL: 'Apple',        MSFT: 'Microsoft',     GOOGL: 'Alphabet',    GOOG: 'Alphabet',
  AMZN: 'Amazon',       META: 'Meta',           NVDA: 'Nvidia',       TSLA: 'Tesla',
  NFLX: 'Netflix',      INTC: 'Intel',          AMD: 'AMD',           QCOM: 'Qualcomm',
  AVGO: 'Broadcom',     CRM: 'Salesforce',      ORCL: 'Oracle',       IBM: 'IBM',
  AMAT: 'Applied Materials', MU: 'Micron',
  JPM: 'JPMorgan',      BAC: 'Bank of America', WFC: 'Wells Fargo',   GS: 'Goldman Sachs',
  MS: 'Morgan Stanley', AXP: 'American Express', V: 'Visa',           MA: 'Mastercard',
  BRK: 'Berkshire',     JNJ: 'J&J',             UNH: 'UnitedHealth',
  PFE: 'Pfizer',        MRK: 'Merck',           ABBV: 'AbbVie',       LLY: 'Eli Lilly',
  XOM: 'ExxonMobil',    CVX: 'Chevron',         COP: 'ConocoPhillips',
  WMT: 'Walmart',       TGT: 'Target',          COST: 'Costco',       HD: 'Home Depot',
  MCD: "McDonald's",    NKE: 'Nike',            SBUX: 'Starbucks',    CMG: 'Chipotle',
  DIS: 'Disney',        CMCSA: 'Comcast',
  F: 'Ford',            GM: 'General Motors',
  BA: 'Boeing',         LMT: 'Lockheed Martin', RTX: 'Raytheon',
  CAT: 'Caterpillar',   DE: 'Deere',            MMM: '3M',
  GE: 'GE',             HON: 'Honeywell',
  HPQ: 'HP',            DELL: 'Dell',           HPE: 'HPE',
  EL: 'Estée Lauder',   PG: 'P&G',              KO: 'Coca-Cola',      PEP: 'PepsiCo',
  TPR: 'Tapestry',
};

/** Human-readable company name for a document, falling back to ticker then raw name. */
export const companyLabel = (doc: Document): string => {
  const ticker = doc.ticker?.toUpperCase();
  return (ticker && TICKER_NAMES[ticker]) || ticker || doc.name;
};

// ---------------------------------------------------------------------------
// Favicon domains
// ---------------------------------------------------------------------------

// Fast-path fallback for companies whose yfinance website field is absent or
// slow to arrive. Anything not listed will use the domain from the market API
// once it loads.
export const TICKER_DOMAINS: Record<string, string> = {
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
