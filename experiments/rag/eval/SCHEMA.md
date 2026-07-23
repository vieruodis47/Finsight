# Eval Question Schema — v1 (2026-07-09)

Eval sets are JSONL: `questions.v<N>.jsonl` (test/report split) and `questions.v<N>.dev.jsonl` (tuning split). One JSON object per line. **A version is frozen the moment an experiment runs on it** — extending or fixing questions means writing v<N+1>, never editing v<N>.

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Stable unique id (`q001`...). Never reused across versions. |
| `type` | enum | yes | `single-hop` \| `multi-hop` \| `aggregation` \| `temporal` |
| `question` | string | yes | Exactly what gets sent to the variant. |
| `ticker` | string \| list | yes | Company scope. List for cross-company questions. |
| `form` | string \| list | yes | `10-K` / `10-Q` scope. |
| `fiscal_period` | string \| list | yes | e.g. `"FY2024"`, `["FY2024","FY2025"]`. The period(s) the gold facts belong to. |
| `post_cutoff` | bool | yes | true = answerable only from filings newer than the gen model's training data (contamination control). |
| `expected_facts` | list | yes | Gold facts — see below. ≥1 per question. |
| `expected_sources` | list | yes | Gold retrieval targets — see below. |
| `notes` | string | no | Authoring context, verification trail. |

### expected_facts entries

```json
{
  "claim": "Total net sales for fiscal 2024",
  "check": "numeric",              // "numeric" -> deterministic matcher; "judged" -> LLM rubric
  "value": 391035000000,           // numeric checks: canonical value in base units (USD)
  "unit": "USD",
  "tolerance": 0.005,              // relative tolerance (0.5%) — rounding in prose is fine
  "source": {"ticker": "AAPL", "form": "10-K", "fiscal_year": 2024, "xbrl_tag": "RevenueFromContractWithCustomerExcludingAssessedTax"}
}
```

```json
{
  "claim": "Services gross margin exceeded Products gross margin, attributed to mix shift in MD&A",
  "check": "judged"                // non-numeric: judge scores 0/1/2 against this claim
}
```

**Authoring rule (hard):** every `numeric` fact's `value` must be verified against the actual filing before the question ships — via the XBRL facts your own `backend/data_extract` pipeline pulls (record the tag in `source.xbrl_tag`), or by reading the filing. No figure enters the gold set from memory or from an LLM. Unverifiable idea for a question = don't ship it.

### expected_sources entries

```json
{"ticker": "AAPL", "form": "10-K", "fiscal_year": 2024, "section_hint": "Item 7 MD&A - gross margin"}
```

`section_hint` is what retrieval matching keys on (see METRICS.md recall rule). Be as specific as the chunking allows.

## Composition rules (enforced by /rag-eval)

- **≥40% of questions are multi-hop or aggregation** — these differentiate architectures; single-hop mostly ties.
- Include temporal questions requiring ≥2 fiscal years (the cross-year comparisons the graph approach claims to win).
- Include a `post_cutoff: true` subset (aim ≥20%).
- Every question's tickers/forms/periods must be **confirmed ingested** (`/ingest-status/{ticker}`) before the set is used — a recall miss caused by an unindexed filing is an infrastructure bug, not a finding.
- Dev and test splits share no questions; balance types across both.
