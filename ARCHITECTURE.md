# FinSight — Architecture

This document describes how FinSight is put together: the service topology, the
hybrid GraphRAG retrieval router, the data pipeline, and the storage model. For
setup, environment variables, and deployment, see [README.md](./README.md).

FinSight is a hybrid **GraphRAG** financial research assistant. It loads SEC
10-K filings and answers natural-language questions grounded in both
**structured XBRL financial data** (revenue, margins, ratios) and
**unstructured filing text** (risk factors, MD&A, guidance). Two retrieval
paths — a SPARQL graph and a vector similarity index — are selected per-question
by a keyword-heuristic router, with no LLM call needed for routing.

---

## Service topology

```
Browser  (:5173 dev / :5001 Docker)
  │
  ▼
Node / Express  (server.js, :5000 internal)
  ├── GET  /*          →  serves frontend/dist  (React SPA)
  ├── POST /api-proxy  →  Vertex AI  (auth-proxied, rate-limited, SSRF-guarded)
  └── pythonApiForwarder (services/pyProxy.js) forwards these route prefixes:
        /api  /extract  /ingest-status  /market  /metrics  /search
        /compare-metrics  /indexed  /health
              │
              ▼
Python / FastAPI  (data_extract/app.py, :8000)
  ├── GET  /extract/{ticker}         EDGAR fetch → XBRL parse → chunk → embed
  ├── GET  /metrics/{ticker}         embed-free XBRL read for the dashboard
  ├── POST /api/chat                 GraphRAG router → Gemini generation
  ├── GET  /market/{ticker}          yfinance live quote + price history (60s cache)
  ├── GET  /search?q=                SEC company registry search
  ├── GET  /compare-metrics?a=&b=    multi-year XBRL for two tickers (cached)
  ├── GET  /indexed?tickers=         which tickers are fully embedded/searchable
  └── POST /upload  /ingest-retry  /upload-retry  (file ingest + polling)
              │
              ├──► RavenDB
              │      FilingChunks      (text + 1024-dim bge-m3 embedding vectors)
              │      IngestManifests   (dedup / already-indexed gate)
              │      IngestJobs        (queue state, persisted across restarts)
              │      FilingMetrics     (structured XBRL; rehydrates graph on boot)
              │
              ├──► bge-m3  (in-process, sentence-transformers)
              │      BAAI/bge-m3       (text → 1024-dim vector; ingest + query)
              │
              └──► Gemini / Vertex AI
                     gemini-1.5-flash  (grounded answer generation)
```

**Request flow for a chat question:**

1. Browser `POST /api/chat` → Vite proxy (dev) or Node (prod)
2. Node forwards via `pyProxy.js` to FastAPI `POST /api/chat`
3. `graph/router.py` classifies the question (keyword heuristics, no LLM)
4. Depending on path: SPARQL over in-memory RDF graph, vector search in
   RavenDB, or both in parallel
5. Retrieved context passed to Gemini for a grounded, cited answer
6. Response includes `retrieval_path` so the UI can show the source badge

---

## Embeddings — bge-m3 (in-process)

Embeddings are produced **in-process** by
[`sentence-transformers`](https://www.sbert.net/) running the MIT-licensed
`BAAI/bge-m3` model (`backend/data_extract/embeddings.py`). There is **no
embedding API and no per-day / per-minute quota** — encoding happens on the
FastAPI host's CPU.

| Property | Value |
|---|---|
| Model | `BAAI/bge-m3` (`EMBED_MODEL`), pinned revision `5617a9f…` (`EMBED_MODEL_REVISION`) |
| Dimension | **1024** (`EMBED_DIM`) — fixed by the model |
| Encoder | **Symmetric** — same encoder for documents and queries |
| Normalization | Every vector L2-normalized for cosine consistency with the stored corpus |
| Runtime | CPU-only `torch`; weights baked into the Docker image at build time (`HF_HOME` cache) |

Notable consequences of the in-process design:

- `embed_texts(texts, task_type)` keeps `task_type` in its signature for
  backwards compatibility, but **ignores it** — bge-m3 applies no task prefix or
  document/query asymmetry.
- `DailyQuotaExceededError` / `PerMinuteQuotaError` remain **defined** and are
  still **caught** upstream (in `app.py`, `router.py`, `bulk_ingest.py`), but
  they are **never raised** anymore. The quota/backoff machinery is legacy from
  the previous Gemini-embedding path and is effectively dormant.
- A dimension guard refuses to store any vector whose length ≠ `EMBED_DIM`,
  crashing loudly rather than silently corrupting the index.

> **History:** FinSight originally embedded with Gemini `gemini-embedding-001`
> (1536-dim) under a 1,000 req/day free-tier quota. PR #34 migrated to
> in-process bge-m3 (1024-dim). Stored-document parity was validated to cosine
> ≥ 0.99997, and the model/torch/transformers versions are pinned exactly so a
> CI rebuild embeds identically and can't silently shift the vector space.

**Answer generation still uses Gemini** (`gemini-1.5-flash` by default, via
`GEMINI_GEN_MODEL`) through the `google-genai` client / Vertex AI proxy. Only
the *embedding* step moved off Gemini.

---

## Hybrid GraphRAG routing

`backend/graph/router.py` routes each question **without calling an LLM**. It
applies four compiled regex sets to the question text:

| Pattern set | Examples |
|---|---|
| `_METRIC_KW` | revenue, net income, gross margin, EPS, free cash flow, debt, ROE |
| `_STRUCTURED_KW` | compare, versus, rank, highest, lowest, which company |
| `_NARRATIVE_KW` | risk factors, MD&A, strategy, guidance, segment, supply chain |
| `_YEAR_RE` | FY2024, fiscal 2023, 2022 |

**Routing decision:**

| Signals present | Path | Meaning |
|---|---|---|
| metric + year, or structured comparison | `graph` | SPARQL over in-memory RDF graph |
| direct-lookup phrasing + metric + year | `graph` | overrides any narrative keyword |
| narrative only | `vector` | RavenDB vector similarity search |
| narrative + (structured keyword or year) | `both` | parallel graph + vector, merged |
| graph chosen but in-memory graph is empty | `vector_no_graph` | transparent fallback |

The four paths surface as source badges in the chat UI:
`◉ financial data` / `◉ filing text` / `◉ financial data + filing text` /
`◎ filing text · graph data not loaded`.

The in-memory graph is populated when `/extract/{ticker}` is called and also
rehydrated from the `FilingMetrics` RavenDB collection on startup, so
structured metric queries survive server restarts without re-ingesting.

Vector search is **scoped to the named companies** in the question, so chunks
from one company never leak into another company's answer.

---

## Data pipeline

### Filing ingest (EDGAR or upload)

```
Ticker input
  │
  ▼
sec_client.py: CIK lookup → filing list → document URL → PDF/text fetch + parse
  │
  ▼
extractor.py: XBRL companyfacts API → income / balance / cash-flow metrics
              narrative sections extracted from filing text
              validation.py sanity-checks metrics (balance-sheet identity, etc.)
  │
  ▼
embeddings.py: text chunked → bge-m3 in-process encode (1024-dim, L2-normalized)
               FilingChunks stored in RavenDB  (text + embedding + ticker/form metadata)
               IngestManifest written  (accession number → dedup gate for re-adds)
               IngestJob updated  (queued → indexing → indexed / failed)
  │
  ▼
graph/router.py: register_filing() → XBRL metrics saved to FilingMetrics collection
                 in-memory RDF graph rebuilt from updated registry
                 caches (/indexed, /compare-metrics) invalidated
```

**Ingest queue.** A single background thread drains one filing at a time.
`IngestJobs` documents persist queue state across restarts. (The queue's
quota-backoff states — `waiting_for_quota`, exponential retry, 72-hour deadline
via `QUOTA_DEADLINE_HOURS` — are inherited from the Gemini-embedding era and no
longer trigger now that embedding is in-process and quota-free.)

**Already-indexed check.** Before embedding, `check_already_indexed()` looks
up the accession number in `IngestManifests`. If found, the filing is skipped:
no re-embedding, status returns `indexed` immediately.

**Embed-free reads.** `/metrics/{ticker}` (`filing_metrics.py`) and
`/indexed` (`indexed.py`) never touch the embedder. The dashboard's
fundamentals are a pure XBRL/DB read; embedding is a separate step that only
FinChat's vector search needs. A pasted `/company/:ticker` URL renders the
dashboard through `/metrics` without any embedding work.

### RavenDB collections

| Collection | Content |
|---|---|
| `FilingChunks` | Chunked filing text + 1024-dim `embedding` vector |
| `IngestManifests` | One doc per indexed filing; accession number for dedup |
| `IngestJobs` | Queue state (queued / indexing / indexed / failed / waiting_for_quota) |
| `FilingMetrics` | XBRL structured metrics per ticker/year; rehydrates the RDF graph on startup |

### RDF graph

`graph/rdf_graph.py` builds an in-memory OWL graph from the numeric metric
categories (`income_statement`, `balance_sheet`, `cash_flow`,
`computed_ratios`). Qualitative prose lives only in `FilingChunks`.

- Ontology namespace: `http://finsight.io/ontology#`
- Classes: `fs:Company`, `fs:Filing`, `fs:FinancialMetric`

---

## Performance & caching

- **`/market`** responses cached in-process, 60s TTL.
- **`/compare-metrics`** cached keyed on `frozenset({a, b})`; invalidated on
  ingest.
- **`/indexed`** cached as one bulk manifest set, 60s TTL, invalidated on
  `register_filing()`. Fails soft — a RavenDB hiccup degrades to "nothing is
  indexed" rather than a 5xx.
- **`both` chat path** runs graph + vector retrieval in parallel.

---

## Component map

### Backend (`backend/`)

| File | Responsibility |
|---|---|
| `server.js` | Node/Express: serves the SPA, Vertex auth proxy, forwards Python routes |
| `services/pyProxy.js` | Node → Python HTTP forwarder |
| `services/session.js` | Express session middleware |
| `data_extract/app.py` | FastAPI app + ingest queue daemon |
| `data_extract/embeddings.py` | RavenDB client, bge-m3 encode, ingest/search |
| `data_extract/extractor.py` | Pipeline orchestrator: EDGAR → metrics + sections |
| `data_extract/sec_client.py` | All SEC EDGAR network calls |
| `data_extract/facts.py` | XBRL → standardized financial fields |
| `data_extract/ratios.py` | Computed financial ratios (ROE, current ratio, …) |
| `data_extract/sections.py` | Filing section splitter (Risk Factors, MD&A, …) |
| `data_extract/validation.py` | Sanity checks on extracted metrics |
| `data_extract/rag.py` | RAG: retrieve chunks → Gemini generation |
| `data_extract/filing_metrics.py` | `/metrics/{ticker}` — embed-free dashboard read |
| `data_extract/indexed.py` | `/indexed` — manifest-based "is this ticker searchable?" |
| `data_extract/compare_metrics.py` | `/compare-metrics` endpoint |
| `data_extract/market.py` | `/market` endpoint (yfinance) |
| `data_extract/search.py` | `/search` endpoint (SEC registry) |
| `data_extract/sectors.py` | SIC code → GICS sector mapper |
| `data_extract/text_metrics.py` | Regex fallback metric extractor |
| `graph/router.py` | GraphRAG router: classifier + answer orchestrator |
| `graph/rdf_graph.py` | RDF/SPARQL graph (rdflib), OWL ontology |
| `analysis/*` | Standalone offline analysis tools (charts, metrics, predictions) |
| `scripts/bulk_ingest.py` | CLI bulk ingestion; resumable, skips already-indexed |
| `company_name/sec_companies.json` | Full SEC ticker → CIK registry (~12,000 companies) |

### Frontend (`frontend/`)

| File | Responsibility |
|---|---|
| `App.tsx` | Root shell: layout, routing, document state |
| `types.ts` | TypeScript types (Document, FilingMetrics, …) |
| `theme.ts` | Design tokens: colors, fonts, breakpoints |
| `vite.config.ts` | Vite config + dev proxy to Node (:5000) |
| `components/Dashboard.tsx` | Metrics cards + margin chart + market snapshot |
| `components/ChatInterface.tsx` | Finch chat: markdown, citations, filter pills |
| `components/DocumentManager.tsx` | Filing fetch/upload, status badges, retry |
| `components/AnalysisView.tsx` | AI summary + two-company XBRL comparison charts |
| `components/CompareView.tsx` | Peer-comparison view (key metrics + charts) |
| `components/PeerPicker.tsx` | Peer-selection controls for the compare view |
| `components/PriceCompareChart.tsx` | Normalized price-change comparison chart |
| `components/FinChatStrip.tsx` | Scoped, gated FinChat strip inside the compare view |
| `components/HelpView.tsx` | Question tips, quality checker, FAQ |
| `components/GettingStarted.tsx` | Onboarding screen (no filings loaded) |
| `components/SplashScreen.tsx` | First-load landing screen |
| `components/SearchDropdown.tsx` | Autocomplete company dropdown |
| `components/CompanyLogo.tsx` | Favicon-based company logo with fallbacks |
| `services/gemini.ts` | Frontend fetch() wrappers for backend APIs |
| `utils/company.ts` | Ticker → name/domain maps, `companyLabel()` |
| `utils/hooks.ts` | `useDebounce`, `useIsTablet` (matchMedia) |

---

## Known limitations

**Graph requires a filing extract after a fresh database.** The in-memory RDF
graph is rebuilt at startup from the `FilingMetrics` RavenDB collection. If it
is populated, graph features are available immediately; if empty (fresh
database), structured metric questions fall back to `vector_no_graph` until the
first `/extract/{ticker}` call.

**Silent DB degradation on startup.** RavenDB calls in the FastAPI lifespan
handler are wrapped in `try/except`. If RavenDB is unreachable, the service
still reports healthy and graph/vector features silently degrade. Check logs
for `Could not load FilingMetrics` or connection errors.

**Responsive layout.** The frontend targets desktop (>1024 px) and tablet
(768–1024 px). Mobile layout is best-effort.

**XBRL extraction accuracy.** Metrics are extracted from standardized us-gaap
concept names. Some filers use non-standard or legacy tags; missing fields are
left absent rather than estimated. Always verify key figures against the
original SEC filing.
