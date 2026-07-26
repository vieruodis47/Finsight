import { ChatSource, FilingMetrics, ChatChart } from '../types';
// Re-exported so chart consumers can import the type from the service layer.
export type { ChatChart } from '../types';

// Same-origin by default: all API calls go through the Node server (:5000),
// which owns sessions/auth and forwards FinSight routes to Python (:8000).
// In dev, Vite proxies these paths to Node (see vite.config.ts).
// Set VITE_API_BASE only to point at a remote deployment.
const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export interface ChatResult {
  answer: string;
  sources: ChatSource[];
  validCitations?: number[];
  retrievalPath?: 'graph' | 'vector' | 'both' | 'none' | 'vector_no_graph';
  chart?: ChatChart;
}

export interface AskOptions {
  ticker?: string;
  // Explicit vector-search scope sent to /api/chat. The compare-view FinChat
  // strip passes [anchor, peer] so a pair question is confined to those two
  // companies even when it names neither. Omitted by ChatInterface, so its
  // behaviour is unchanged (the backend field is additive/optional).
  tickers?: string[];
  form?: '10-K';
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
  const data = await res.json() as { answer: string; sources: ChatSource[]; valid_citations?: number[]; retrieval_path?: string };
  return {
    answer: data.answer,
    sources: data.sources,
    validCitations: data.valid_citations ?? [],
    retrievalPath: data.retrieval_path as ChatResult['retrievalPath'],
  };
}

export interface ChatStreamHandlers {
  // Called with each incremental text delta as it arrives.
  onToken: (delta: string) => void;
  // Called once when the stream completes, carrying the reference list, the
  // validated inline-citation numbers, and the retrieval path. Citations resolve
  // here (at completion), never per-token.
  onDone: (meta: { sources: ChatSource[]; validCitations: number[]; retrievalPath?: ChatResult['retrievalPath']; chart?: ChatChart }) => void;
  // Called on a mid-stream failure; any text already delivered via onToken stays.
  onError: (message: string) => void;
}

// Real token streaming over /api/chat/stream. The response is NDJSON: one JSON
// event per line ({type:"token"|"done"|"error"}). We read the body as a stream
// and dispatch events as they arrive — no waiting for the full response. The
// gateway forwards this route unbuffered (see backend/services/pyProxy.js).
export async function askFinSightStream(
  question: string,
  opts: AskOptions,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
      body: JSON.stringify({ question, ...opts }),
      signal,
    });
  } catch (e) {
    handlers.onError(e instanceof Error ? e.message : 'Network error');
    return;
  }

  if (!res.ok || !res.body) {
    const msg = await res.text().catch(() => res.statusText);
    handlers.onError(`Chat failed (${res.status}): ${msg}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let erroredOrDone = false;

  const handleLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let evt: { type: string; text?: string; sources?: ChatSource[]; valid_citations?: number[]; retrieval_path?: string; message?: string; chart?: ChatChart };
    try {
      evt = JSON.parse(trimmed);
    } catch {
      return; // ignore a malformed/partial line
    }
    if (evt.type === 'token' && evt.text) {
      handlers.onToken(evt.text);
    } else if (evt.type === 'done') {
      erroredOrDone = true;
      handlers.onDone({
        sources: evt.sources ?? [],
        validCitations: evt.valid_citations ?? [],
        retrievalPath: evt.retrieval_path as ChatResult['retrievalPath'],
        chart: evt.chart,
      });
    } else if (evt.type === 'error') {
      erroredOrDone = true;
      handlers.onError(evt.message ?? 'The response was interrupted.');
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // NDJSON: process every complete line, keep the trailing partial in buffer.
      let nl: number;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        handleLine(line);
      }
    }
    // Flush any trailing line without a newline.
    if (buffer.trim()) handleLine(buffer);
  } catch (e) {
    // The connection dropped mid-stream. Surface an error unless we already
    // saw a done/error event; partial text delivered so far is preserved.
    if (!erroredOrDone) {
      handlers.onError(e instanceof Error ? e.message : 'The connection was lost.');
    }
    return;
  }

  // The stream ended without a `done` or `error` event. A well-formed response
  // always terminates with one of those, so reaching here means the connection
  // was truncated mid-flight (e.g. the backend dropped). Surface it as an error;
  // any partial text already delivered via onToken is preserved by the caller.
  if (!erroredOrDone) {
    handlers.onError('The connection closed before the response finished.');
  }
}

// Download the server-composed Analysis PDF (charts + deterministic descriptions
// + forecast) for a ticker. Fetches the blob and triggers a browser download.
// Throws with the backend's detail message on failure so the caller can surface it.
export async function exportAnalysisReport(ticker: string, peers: string[] = []): Promise<void> {
  // Loaded companies (optional) add the "Peer distribution" page to the PDF.
  const qs = peers.map(p => `peers=${encodeURIComponent(p)}`).join('&');
  const res = await fetch(`${API_BASE}/analysis/report/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ''}`);
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail || detail; } catch { /* non-JSON error body */ }
    throw new Error(`Export failed (${res.status}): ${detail}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `FinSight_${ticker.toUpperCase()}_Analysis.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Download the server-composed two-company Comparison PDF (every comparison
// chart + the SAME deterministic captions shown on screen + the on-screen
// AI-generated analysis carried VERBATIM — the server never re-runs an LLM, so
// the PDF matches the UI exactly). POST because the narrative + display context
// ride in the body. Triggers a browser download; throws the backend's detail on
// failure so the caller can surface it (never a silent no-op).
export interface CompareReportContext {
  companyA?: string;
  companyB?: string;
  sectorA?: string;
  sectorB?: string;
  analysis?: string;   // the exact on-screen AI-generated markdown
}

export async function exportCompareReport(
  a: string,
  b: string,
  ctx: CompareReportContext = {},
): Promise<void> {
  const res = await fetch(`${API_BASE}/analysis/compare-report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      a, b,
      company_a: ctx.companyA, company_b: ctx.companyB,
      sector_a: ctx.sectorA, sector_b: ctx.sectorB,
      analysis: ctx.analysis,
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail || detail; } catch { /* non-JSON error body */ }
    throw new Error(`Export failed (${res.status}): ${detail}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const el = document.createElement('a');
  el.href = url;
  el.download = `FinSight_${a.toUpperCase()}_vs_${b.toUpperCase()}_Comparison.pdf`;
  document.body.appendChild(el);
  el.click();
  el.remove();
  URL.revokeObjectURL(url);
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
// Sections to include in the LLM context, in reading order (financial_statements
// excluded — numbers are already captured in structured metrics).
const SECTION_ORDER = ['business', 'risk_factors', 'mda'] as const;
// Per-section character cap: keeps combined context under ~60k chars (~15k tokens)
// so we stay within Gemini's effective attention window for long filings.
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

export async function extractCompany(ticker: string, form: '10-K' = '10-K'): Promise<ExtractResponse> {
  const res = await fetch(`${API_BASE}/extract/${encodeURIComponent(ticker)}?form=${form}`);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Extract failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as ExtractResponse;
}

// --- Ingest status polling --------------------------------------------------

export interface IngestStatus {
  status: 'queued' | 'indexing' | 'indexed' | 'failed' | 'unknown' | 'waiting_for_quota';
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

export async function retryIngest(ticker: string, form: string): Promise<void> {
  const res = await fetch(`${API_BASE}/ingest-retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticker, form }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Retry failed (${res.status}): ${msg}`);
  }
}

// --- File upload ------------------------------------------------------------

export interface UploadResponse {
  doc_id: string;
  filename: string;
  char_count: number;
  ticker_label: string;
}

export async function uploadFile(file: File): Promise<UploadResponse> {
  const body = new FormData();
  body.append('file', file);
  const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(msg || `Upload failed (${res.status})`);
  }
  return (await res.json()) as UploadResponse;
}

export async function getUploadStatus(docId: string): Promise<IngestStatus> {
  const res = await fetch(`${API_BASE}/upload-status/${encodeURIComponent(docId)}`);
  if (!res.ok) throw new Error(`Upload status check failed (${res.status})`);
  return (await res.json()) as IngestStatus;
}

export async function retryUpload(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/upload-retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc_id: docId }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Retry failed (${res.status}): ${msg}`);
  }
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

// --- Forecast (statistical trend projection) --------------------------------

export interface ForecastMetric {
  metric: string;                         // e.g. "revenue", "gross_margin_pct"
  unit: 'usd' | 'pct';
  history: { year: string; value: number }[];
  predicted_value: number;
  confidence_low: number;
  confidence_high: number;
  next_label: string;                     // e.g. "FY2027 (projected)"
  trend: 'improving' | 'declining' | 'stable';
  reliability: 'high' | 'moderate' | 'low';
  r_squared: number;
  anomaly_years: string[];
  // Deterministic, server-computed one-sentence description (templated from the
  // figures above — never LLM-generated numbers). Used as visible caption +
  // chart accessible text.
  description?: string;
}

export interface ForecastResult {
  ticker: string;
  metrics: ForecastMetric[];
}

export async function fetchForecast(ticker: string): Promise<ForecastResult> {
  const res = await fetch(`${API_BASE}/analysis/prediction/${encodeURIComponent(ticker)}`);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Forecast failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as ForecastResult;
}

// --- Analysis "Trends" charts (ported from the offline charts.py) -----------
// All three read the tag-merged, fiscal-year-correct metrics layer, so series
// are never truncated to a legacy XBRL tag (see /analysis/trends etc.).

export interface TrendPoint {
  year: string;
  revenue: number | null;
  net_income: number | null;
  cogs: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  gross_margin_pct: number | null;
  operating_margin_pct: number | null;
  net_margin_pct: number | null;
}

export interface TrendsResult {
  ticker: string;
  currency: 'usd';
  points: TrendPoint[];
  // Per-chart descriptions, keyed by metric/chart id (revenue, net_income,
  // gross_margin_pct, operating_margin_pct, net_margin_pct, cost_structure,
  // revenue_vs_income). Deterministically templated server-side.
  descriptions?: Record<string, string>;
}

export async function fetchTrends(ticker: string): Promise<TrendsResult> {
  const res = await fetch(`${API_BASE}/analysis/trends/${encodeURIComponent(ticker)}`);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Trends failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as TrendsResult;
}

export interface QuarterPoint {
  quarter: 'Q1' | 'Q2' | 'Q3' | 'Q4';
  revenue: number | null;
  cogs: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
}

export interface QuarterlyResult {
  ticker: string;
  currency: 'usd';
  fy: string;
  points: QuarterPoint[];
  // Keyed by quarterly metric (revenue, gross_profit, operating_income, net_income).
  descriptions?: Record<string, string>;
}

export async function fetchQuarterly(ticker: string): Promise<QuarterlyResult> {
  const res = await fetch(`${API_BASE}/analysis/quarterly/${encodeURIComponent(ticker)}`);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Quarterly failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as QuarterlyResult;
}

export interface DistributionResult {
  ticker: string;
  metric: string;
  unit: 'usd' | 'pct';
  mean: number;
  std: number;
  points: { year: string; value: number; is_anomaly: boolean }[];
  description?: string;
}

export async function fetchDistribution(ticker: string, metric: string): Promise<DistributionResult> {
  const res = await fetch(
    `${API_BASE}/analysis/distribution/${encodeURIComponent(ticker)}?metric=${encodeURIComponent(metric)}`,
  );
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Distribution failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as DistributionResult;
}

// Loaded-peer distribution box plots: three key ratios spread across the target
// + the other loaded companies, with the target positioned on each spectrum.
// Real data only (companies that don't load are skipped server-side); a metric
// with fewer than `min_peers` reporters comes back `sufficient: false`.
export interface PeerDistributionMetric {
  key: string;
  label: string;
  unit: 'pct' | 'ratio';
  n: number;
  companies: { ticker: string; value: number; is_target: boolean }[];
  target_value: number | null;
  sufficient: boolean;
  min: number | null;
  q1: number | null;
  median: number | null;
  q3: number | null;
  max: number | null;
  description: string;
}

export interface PeerDistributionResult {
  ticker: string;
  peers: string[];
  min_peers: number;
  metrics: PeerDistributionMetric[];
}

export async function fetchPeerDistribution(ticker: string, peers: string[]): Promise<PeerDistributionResult> {
  const qs = peers.map(p => `peers=${encodeURIComponent(p)}`).join('&');
  const res = await fetch(
    `${API_BASE}/analysis/peer-distribution/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ''}`,
  );
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Peer distribution failed (${res.status}): ${msg}`);
  }
  return (await res.json()) as PeerDistributionResult;
}

// Trailing price returns (1M/3M/6M/1Y), computed client-side from the existing
// /market daily-close history so we add no new market egress path. Each return
// anchors to the close at-or-before the target date (or the earliest close if
// the window predates our history).
export interface PeriodReturns {
  m1: number | null;
  m3: number | null;
  m6: number | null;
  y1: number | null;
}

export async function fetchReturns(ticker: string): Promise<PeriodReturns> {
  const empty: PeriodReturns = { m1: null, m3: null, m6: null, y1: null };
  const m = await fetchMarketData(ticker, '1y').catch(() => null);
  const h = m?.history ?? [];
  if (h.length === 0) return empty;

  const last = h[h.length - 1];
  const lastDate = new Date(last.date);
  const retFor = (daysAgo: number): number | null => {
    const target = new Date(lastDate);
    target.setDate(target.getDate() - daysAgo);
    let best = h[0]; // fall back to earliest close if the window predates history
    for (const p of h) {
      if (new Date(p.date) <= target) best = p; else break;
    }
    if (!best.close) return null;
    return ((last.close - best.close) / best.close) * 100;
  };

  return { m1: retFor(30), m3: retFor(91), m6: retFor(182), y1: retFor(365) };
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
  // Per-metric descriptions keyed by series key (revenue, net_income, …). Each
  // states the latest common year, the gap, and every ticker's covered range +
  // in-window gaps — so a non-overlapping comparison reads as such.
  descriptions?: Record<string, string>;
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

// Single-ticker dashboard metrics — the read-only, embed-free counterpart to
// /extract. Backs the /company/:ticker deep link: renders the dashboard for
// any valid SEC ticker without ever enqueueing embedding work. Fails soft to
// null (404 = no such ticker/filing, or a transient error) so a deep link
// degrades to the empty dashboard state rather than crashing.
export interface MetricsResponse {
  ticker: string;
  form: string;
  filing_date: string;
  fiscal_year_end: string;
  accession_number: string;
  sector: string;
  metrics: FilingMetrics;
  source: 'ravendb' | 'sec';
}

export async function fetchMetrics(ticker: string): Promise<MetricsResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/metrics/${encodeURIComponent(ticker)}`);
    if (!res.ok) return null;
    return (await res.json()) as MetricsResponse;
  } catch {
    return null;
  }
}

// Whether each ticker has a completed IngestManifest (fully embedded and
// searchable), used to gate the ingest CTA on deep links. Fails soft to
// "not indexed" on any error — unknown and not-indexed are the same thing to
// the UI, and the alternative (throwing) would block rendering the dashboard
// shell over a transient network blip.
export async function fetchIndexedStatus(tickers: string[]): Promise<Record<string, boolean>> {
  const upper = tickers.map(t => t.toUpperCase());
  if (upper.length === 0) return {};
  try {
    const res = await fetch(`${API_BASE}/indexed?tickers=${encodeURIComponent(upper.join(','))}`);
    if (!res.ok) return Object.fromEntries(upper.map(t => [t, false]));
    return (await res.json()) as Record<string, boolean>;
  } catch {
    return Object.fromEntries(upper.map(t => [t, false]));
  }
}
