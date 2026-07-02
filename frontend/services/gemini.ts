import { ChatSource, FilingMetrics } from '../types';

// Same-origin by default: all API calls go through the Node server (:5000),
// which owns sessions/auth and forwards FinSight routes to Python (:8000).
// In dev, Vite proxies these paths to Node (see vite.config.ts).
// Set VITE_API_BASE only to point at a remote deployment.
const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export interface ChatResult {
  answer: string;
  sources: ChatSource[];
}

export interface AskOptions {
  ticker?: string;
  form?: '10-K' | '10-Q';
  k?: number;
}

export async function askFinSight(question: string, opts: AskOptions = {}): Promise<ChatResult> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, ...opts }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Chat failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as ChatResult;
}

export async function generateSummary(content: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Summary failed (${res.status}): ${msg}`);
  }
  const data = (await res.json()) as { summary: string };
  return data.summary;
}

export async function compareDocuments(
  nameA: string,
  contentA: string,
  nameB: string,
  contentB: string,
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name_a: nameA, content_a: contentA, name_b: nameB, content_b: contentB }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Compare failed (${res.status}): ${msg}`);
  }
  const data = (await res.json()) as { comparison: string };
  return data.comparison;
}

export interface ExtractResponse {
  ticker: string;
  form: string;
  filing_date: string;
  accession_number: string;
  source_url: string;
  char_count: number;
  metrics: FilingMetrics;
  sections?: Record<string, string>;
  sector?: string;
}

// Key narrative sections in 10-K order; financial_statements omitted because
// the numbers are already captured in metrics.
const SECTION_ORDER = ['business', 'risk_factors', 'mda'] as const;
const PER_SECTION_CAP = 20_000;

export function buildContent(sections: Record<string, string>): string {
  const parts: string[] = [];
  for (const key of SECTION_ORDER) {
    const text = sections[key];
    if (!text) continue;
    parts.push(`## ${key.replace(/_/g, ' ').toUpperCase()}\n${text.slice(0, PER_SECTION_CAP)}`);
  }
  return parts.join('\n\n');
}

export async function extractCompany(ticker: string, form: '10-K' | '10-Q' = '10-K'): Promise<ExtractResponse> {
  const res = await fetch(`${API_BASE}/extract/${encodeURIComponent(ticker)}?form=${form}`);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Extract failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as ExtractResponse;
}

// --- Ingest status polling --------------------------------------------------

export interface IngestStatus {
  status: 'indexing' | 'indexed' | 'failed' | 'unknown';
  chunks: number;
  error?: string;
}

export async function getIngestStatus(ticker: string, form: string): Promise<IngestStatus> {
  const res = await fetch(
    `${API_BASE}/ingest-status/${encodeURIComponent(ticker)}?form=${encodeURIComponent(form)}`,
  );
  if (!res.ok) throw new Error(`Ingest status check failed (${res.status})`);
  return (await res.json()) as IngestStatus;
}

// --- Market data ------------------------------------------------------------

export interface MarketSnapshot {
  price?: number;
  market_cap?: number;
  volume?: number;
  high_52w?: number;
  low_52w?: number;
  pe_ratio?: number;
  change_pct?: number;
  website?: string;
}

export interface MarketHistoryPoint {
  date: string;
  close: number;
}

export interface MarketResponse {
  ticker: string;
  period: string;
  snapshot: MarketSnapshot;
  history: MarketHistoryPoint[];
}

export async function fetchMarketData(ticker: string, period = '1y'): Promise<MarketResponse> {
  const res = await fetch(`${API_BASE}/market/${encodeURIComponent(ticker)}?period=${period}`);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Market fetch failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as MarketResponse;
}

// Company name/ticker search over the SEC registry (~10 k entries).
export interface SearchResult {
  name: string;
  ticker: string;
}

export async function searchCompanies(q: string): Promise<SearchResult[]> {
  if (!q.trim()) return [];
  try {
    const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(q.trim())}`);
    if (!res.ok) return [];
    return (await res.json()) as SearchResult[];
  } catch {
    return [];
  }
}

// Multi-year side-by-side metrics for two tickers (powers comparison charts).
export interface ComparePoint {
  year: string;
  a: number | null;
  b: number | null;
}

export interface CompareMetricsResult {
  tickers: { a: string; b: string };
  revenue: ComparePoint[];
  net_income: ComparePoint[];
  gross_margin_pct: ComparePoint[];
  operating_margin_pct: ComparePoint[];
  net_margin_pct: ComparePoint[];
  revenue_growth_pct: ComparePoint[];
  free_cash_flow: ComparePoint[];
  debt_to_equity: ComparePoint[];
  current_ratio: ComparePoint[];
}

export async function fetchCompareMetrics(a: string, b: string): Promise<CompareMetricsResult> {
  const res = await fetch(
    `${API_BASE}/compare-metrics?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
  );
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Compare metrics failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as CompareMetricsResult;
}
