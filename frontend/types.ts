// 'indexed' = embedding complete and chunks stored in RavenDB (searchable via RAG).
// 'waiting_for_quota' = Gemini daily embedding quota exhausted; retrying with backoff.
export type IndexStatus = 'queued' | 'indexing' | 'indexed' | 'failed' | 'waiting_for_quota';

export interface Document {
  id: string;
  name: string;
  uploadDate: string;
  size: string;
  content: string;
  ticker?: string;
  form?: string;
  sector?: string;            // GICS sector label, e.g. "Consumer Discretionary"
  metrics?: FilingMetrics;    // structured XBRL data from the extractor
  indexStatus?: IndexStatus;  // tracks RavenDB embedding ingest progress
  indexError?: string;        // set when indexStatus === 'failed'
  indexChunks?: number;       // count of chunks stored on success
  uploadDocId?: string;       // set for uploaded files; used to poll /upload-status
}

// --- Extractor output (backend/data_extract/extractor.py -> metrics) ---------
// All fields optional: XBRL extraction may not resolve every concept for every
// filer. Values are in millions of USD unless the name says otherwise.

export interface IncomeStatement {
  total_revenue_millions?: number;
  cost_of_revenue_millions?: number;
  gross_margin_millions?: number;
  gross_margin_pct?: number;
  rd_expense_millions?: number;
  sga_expense_millions?: number;
  total_opex_millions?: number;
  operating_income_millions?: number;
  income_tax_millions?: number;
  net_income_millions?: number;
  eps_basic?: number;
  eps_diluted?: number;
  effective_tax_rate_pct?: number;
}

export interface BalanceSheet {
  cash_and_equivalents_millions?: number;
  total_current_assets_millions?: number;
  total_assets_millions?: number;
  total_current_liabilities?: number;
  total_liabilities_millions?: number;
  shareholders_equity_millions?: number;
  long_term_debt_millions?: number;
  retained_earnings_millions?: number;
  ppe_net_millions?: number;
  inventories_millions?: number;
  accounts_receivable_millions?: number;
  working_capital_millions?: number;
}

export interface CashFlow {
  operating_cash_flow_millions?: number;
  investing_cash_flow_millions?: number;
  financing_cash_flow_millions?: number;
  capex_millions?: number;
  dividends_paid_millions?: number;
  share_repurchases_millions?: number;
  depreciation_amortization?: number;
  share_based_comp_millions?: number;
  free_cash_flow_millions?: number;
}

export interface FilingMetrics {
  income_statement?: IncomeStatement;
  balance_sheet?: BalanceSheet;
  cash_flow?: CashFlow;
  computed_ratios?: Record<string, number>;
  qualitative?: Record<string, unknown>;
}

export interface ChatSource {
  ticker: string;
  form: string;
  chunk_index: number;
  source: string;             // section label (back-compat alias of `section`)
  // --- Deterministic citation fields (built server-side from retrieved chunks) ---
  number?: number;            // 1-based citation number an inline [n] resolves to
  company?: string;           // resolved readable name ("Gap Inc."), not the ticker
  section?: string;           // e.g. "Risk Factors", "MD&A"
  url?: string;               // SEC source URL — used only as the EDGAR href
  accession_number?: string;
  filing_date?: string;
  preview?: string;           // short snippet for the reference row
  text?: string;              // full chunk text revealed in the expander
}

// Inline chart payload built server-side from the SAME XBRL rows that grounded
// the answer (see backend build_graph_chart). The client only renders it — it
// never recomputes a value — so the chart and the answer text always agree.
export interface ChatChartBar { label: string; value: number | null }
export interface ChatChartLinePoint { year: string; value: number | null }
export interface ChatChartSeries { ticker: string; points: ChatChartLinePoint[] }
export interface ChatChart {
  kind: 'bar' | 'line';
  metric: string;
  label: string;
  unit: 'ratio' | 'pct' | 'usd_m' | 'per_share' | 'num';
  caption: string;
  year?: string | null;              // bar: the fiscal year compared
  bars?: ChatChartBar[];             // bar: one entry per company (null = gap)
  years?: string[];                  // line: x-axis fiscal years
  series?: ChatChartSeries[];        // line: one series per company
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: Date;
  sources?: ChatSource[];         // filings that grounded an assistant answer
  validCitations?: number[];      // inline [n] numbers that passed validation (linkify only these)
  retrievalPath?: 'graph' | 'vector' | 'both' | 'none' | 'vector_no_graph'; // which path answered
  streaming?: boolean;            // assistant reply is still streaming in
  error?: boolean;                // stream errored mid-flight (partial text kept)
  chart?: ChatChart;              // optional inline comparison / over-time chart
  // Clarification prompt: FinChat needs to know which company before it can
  // answer. Carries the original question + the loaded companies to offer as
  // quick-pick chips; no retrieval/generation happens until one is chosen.
  clarify?: {
    question: string;                          // the pending question to resume
    companies: { ticker: string; label: string }[];
  };
}

export interface StockDataPoint {
  date: string;
  price: number;
  volume: number;
}

export interface CompanyMetrics {
  symbol: string;
  name: string;
  currentPrice: number;
  change: number;
  changePercent: number;
  high52w: number;
  low52w: number;
  volume: string;
  marketCap: string;
}


export type ViewState = 'dashboard' | 'documents' | 'chat' | 'analysis' | 'help' | 'settings';
