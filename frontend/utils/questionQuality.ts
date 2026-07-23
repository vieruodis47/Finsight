import type { Document } from '../types';
import { companyLabel } from './company';

// ── Shared question-specificity logic ─────────────────────────────────────────
// Single source of truth for "is this question specific enough?" — the same rule
// the Help page teaches ("name the company + year + metric") and the one FinChat
// enforces itself before retrieving. HelpView uses checkSpecificity() for its
// question-checker; ChatInterface uses the company-resolution + primitives below
// for its pre-retrieval clarify gate.

// A fiscal year, or a relative-year phrase ("last year") that still implies one.
export const YEAR_RE =
  /\b(fy\s?20\d{2}|20\d{2}|fiscal(?:\s+year)?|last\s+year|this\s+year|prior\s+year|latest|most\s+recent)\b/i;

// A concrete metric / financial topic (vs. a vague "how's it doing").
export const METRIC_RE =
  /\b(revenue|sales|margin|gross|operating|net\s+income|profit|loss|eps|earnings|ebitda|cash\s*flow|free\s*cash|fcf|capex|debt|equity|assets|liabilities|inventory|turnover|guidance|risk|growth|dividend|buyback|repurchas\w*|segment|tax|valuation|financ\w*|balance\s+sheet)\b/i;

// Cross-company / comparison intent — a multi-company question is NOT a
// single-company ambiguity, so it must never trigger a "which company?" ask.
export const COMPARE_RE =
  /\b(compare|comparison|versus|vs\.?|both|between|head[-\s]?to[-\s]?head|rank|which\s+(company|one|of|firm)|highest|lowest|each\s+(company|of)|all\s+of\s+them|against|side\s+by\s+side)\b/i;

// Pronouns / "the company" — a follow-up that continues the prior company
// without re-naming it.
export const FOLLOWUP_RE =
  /\b(it|its|it's|they|their|them|the\s+company|that\s+company|the\s+firm|the\s+same|this\s+company)\b/i;

export const hasYearMention = (q: string): boolean => YEAR_RE.test(q);
export const hasMetricMention = (q: string): boolean => METRIC_RE.test(q);
export const looksLikeComparison = (q: string): boolean => COMPARE_RE.test(q);
export const looksLikeFollowup = (q: string): boolean => FOLLOWUP_RE.test(q);

// A question is "company-specific" when it asks for a metric/fact about a single
// company — the case that needs a company to be answerable.
export const isCompanySpecific = (q: string): boolean =>
  hasMetricMention(q) || looksLikeFollowup(q);

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Resolve which LOADED companies a question names/implies, in mention order
// (deduped). Matches a ticker as a standalone token (≥2 chars, to avoid stray
// single letters) or the company's name / first name-word on a word boundary.
export function resolveCompaniesInQuestion(question: string, companies: Document[]): Document[] {
  const upper = question.toUpperCase();
  const lower = question.toLowerCase();
  const out: Document[] = [];
  const seen = new Set<string>();

  const add = (doc: Document) => {
    const key = (doc.ticker || doc.name).toUpperCase();
    if (!seen.has(key)) { seen.add(key); out.push(doc); }
  };

  for (const doc of companies) {
    const ticker = (doc.ticker || '').toUpperCase();
    if (ticker.length >= 2 && new RegExp(`\\b${escapeRe(ticker)}\\b`).test(upper)) { add(doc); continue; }

    const label = companyLabel(doc).toLowerCase();
    const first = label.split(/[\s,]+/)[0];
    const name  = (doc.name || '').toLowerCase();
    for (const term of [label, first, name]) {
      if (term && term.length >= 3 && new RegExp(`\\b${escapeRe(term)}\\b`).test(lower)) { add(doc); break; }
    }
  }
  return out;
}

// Convenience: the single company a question resolves to, or null when it names
// none or several.
export function resolveSingleCompany(question: string, companies: Document[]): Document | null {
  const m = resolveCompaniesInQuestion(question, companies);
  return m.length === 1 ? m[0] : null;
}

// ── Generic specificity check (Help page, no loaded context) ──────────────────

// A generic "does it name a company?" heuristic for the Help checker, which has
// no loaded set to resolve against.
const GENERIC_COMPANY_RE =
  /\b(gap|pvh|aeo|american\s+eagle|inditex|h&m|gps|apple|aapl|nvidia|nvda|microsoft|msft|amazon|amzn|tesla|tsla|meta|google|alphabet|googl?|netflix|nflx|walmart|wmt)\b/i;

export interface Specificity {
  hasCompany: boolean;
  hasYear: boolean;
  hasMetric: boolean;
  issues: string[];
  ok: boolean;
}

export function checkSpecificity(question: string): Specificity {
  const q = question.trim();
  const hasCompany = GENERIC_COMPANY_RE.test(q);
  const hasYear = hasYearMention(q);
  const hasMetric = hasMetricMention(q);
  const issues: string[] = [];
  if (!hasCompany) issues.push('• Mention a specific company (e.g. Gap, PVH, AEO)');
  if (!hasYear)    issues.push('• Include a fiscal year (e.g. FY2024)');
  if (!hasMetric)  issues.push('• Name a specific metric or topic (e.g. gross margin, risk factors)');
  return { hasCompany, hasYear, hasMetric, issues, ok: issues.length === 0 };
}
