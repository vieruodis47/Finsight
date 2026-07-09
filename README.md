# FinSight

A hybrid GraphRAG financial research assistant. Load SEC 10-K filings, then ask
natural-language questions and get answers grounded in both **structured XBRL
financial data** (revenue, margins, ratios) and **unstructured filing text**
(risk factors, MD&A, guidance). Two retrieval paths — a SPARQL graph and a
vector similarity index — are selected per-question by a keyword heuristic
router with no LLM call needed for routing.

---

## Architecture

```
Browser  (:5173 dev / :5001 Docker)
  │
  ▼
Node / Express  (server.js, :5000 internal)
  ├── GET  /*          →  serves frontend/dist  (React SPA)
  ├── POST /api-proxy  →  Vertex AI  (auth-proxied, rate-limited)
  └── /api  /extract  /ingest-status  /market  /search  /compare-metrics
              │  pyProxy.js
              ▼
Python / FastAPI  (data_extract/app.py, :8000)
  ├── GET  /extract/{ticker}         EDGAR fetch → XBRL parse → chunk → embed
  ├── POST /api/chat                 GraphRAG router → Gemini generation
  ├── GET  /market/{ticker}          yfinance live quote + price history
  ├── GET  /search?q=                SEC company registry search
  ├── GET  /compare-metrics?a=&b=    multi-year XBRL for two tickers
  └── POST /upload  /ingest-retry  /upload-retry  (file ingest + polling)
              │
              ├──► RavenDB
              │      FilingChunks      (text + 1536-dim embedding vectors)
              │      IngestManifests   (dedup / already-indexed gate)
              │      IngestJobs        (queue state, persisted across restarts)
              │      FilingMetrics     (structured XBRL; rehydrates graph on boot)
              │
              └──► Gemini API
                     gemini-embedding-001  (text → 1536-dim vector)
                     gemini-2.5-flash      (grounded answer generation)
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

## Hybrid GraphRAG routing

`backend/graph/router.py` routes each question without calling an LLM. It
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
  │
  ▼
embeddings.py: text chunked → gemini-embedding-001 (1536-dim)
               FilingChunks stored in RavenDB  (text + embedding + ticker/form metadata)
               IngestManifest written  (accession number → dedup gate for re-adds)
               IngestJob updated  (queued → indexing → indexed / failed / waiting_for_quota)
  │
  ▼
graph/router.py: register_filing() → XBRL metrics saved to FilingMetrics collection
                 in-memory RDF graph rebuilt from updated registry
```

**Ingest queue.** A single background thread drains one filing at a time to
stay within the Gemini free-tier RPM limit. `IngestJobs` documents persist
queue state across restarts. When the daily embedding quota is exhausted, jobs
transition to `waiting_for_quota` with exponential backoff (30 min → 60 →
120 → 360 min max) and are retried automatically. After 72 hours the job is
marked `failed`.

**Already-indexed check.** Before embedding, `check_already_indexed()` looks
up the accession number in `IngestManifests`. If found, the filing is skipped:
no embedding calls, no quota consumed, status returns `indexed` immediately.

**RavenDB collections:**

| Collection | Content |
|---|---|
| `FilingChunks` | Chunked filing text + 1536-dim `embedding` vector |
| `IngestManifests` | One doc per indexed filing; accession number for dedup |
| `IngestJobs` | Queue state (queued / indexing / indexed / failed / waiting_for_quota) |
| `FilingMetrics` | XBRL structured metrics per ticker/year; rehydrates the RDF graph on startup |

### RDF graph

`graph/rdf_graph.py` builds an in-memory OWL graph from the numeric metric
categories (`income_statement`, `balance_sheet`, `cash_flow`,
`computed_ratios`). Qualitative prose lives only in `FilingChunks`.

Ontology namespace: `http://finsight.io/ontology#`  
Classes: `fs:Company`, `fs:Filing`, `fs:FinancialMetric`

---

## Setup — local development

### Prerequisites

- Docker Desktop (for the compose stack)
- Node.js 20+
- Python 3.11+
- A running RavenDB instance (see below)
- Gemini API key ([free tier](https://aistudio.google.com); embedding quota is 1 000 req/day)
- Google Cloud project with Vertex AI API enabled (for the Node auth proxy)

### RavenDB

Run a standalone container outside Compose — the Python service connects to it
via `host.docker.internal`:

```bash
docker run -d --name ravendb \
  -p 8080:8080 -p 38888:38888 \
  -e RAVEN_Setup_Mode=None \
  -e RAVEN_License_Eula_Accepted=true \
  -e RAVEN_Security_UnsecuredAccessAllowed=PublicNetwork \
  ravendb/ravendb
```

Then create a database named `finsight` in the RavenDB Studio at
`http://localhost:8080`.

For **RavenDB Cloud**, set `RAVENDB_URLS` to your cluster URL and
`RAVENDB_CERT_PATH` to the path of your combined client certificate PEM file.

### Clone and install

```bash
git clone https://github.com/ramaniarun2003/finsight.git
cd finsight

# Node dependencies (root workspace + frontend + backend)
npm install

# Python dependencies
pip install -r requirements.txt
```

### Environment variables

Create two env files (both are gitignored):

**`backend/.env.python`** — Python/FastAPI service:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | **yes** | — | Gemini API key for embeddings + generation |
| `RAVENDB_URLS` | no | `http://127.0.0.1:8080` | Comma-separated RavenDB node URLs |
| `RAVENDB_DATABASE` | no | `finsight` | RavenDB database name |
| `RAVENDB_CERT_PATH` | no | — | Path to client cert PEM (RavenDB Cloud only) |
| `GEMINI_GEN_MODEL` | no | `gemini-1.5-flash` | Generation model name |
| `EMBED_DIM` | no | `1536` | Embedding dimension (must match existing index) |
| `EMBED_BATCH` | no | `8` | Chunks per embedding API call |
| `EMBED_BATCH_DELAY` | no | `1.0` | Seconds between embedding batches |
| `SEC_USER_AGENT` | no | `FinSight contact@example.com` | SEC rate-limit header — set to your own email |
| `FRONTEND_ORIGIN` | no | — | CORS allowed origin (e.g. `http://localhost:5173`) |
| `UPLOAD_MAX_MB` | no | `50` | Max file size for PDF/TXT uploads |
| `QUOTA_DEADLINE_HOURS` | no | `72` | Hours before a quota-stalled job is marked failed |

Minimal `backend/.env.python`:
```
GEMINI_API_KEY=<your-key>
RAVENDB_URLS=http://127.0.0.1:8080
RAVENDB_DATABASE=finsight
SEC_USER_AGENT=YourName your@email.com
```

**`backend/.env.local`** — Node/Express service:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | **yes** | — | GCP project ID (Vertex AI auth proxy) |
| `GOOGLE_CLOUD_LOCATION` | **yes** | — | GCP region (e.g. `us-central1`) |
| `PROXY_HEADER` | **yes** | — | Auth header name for the Vertex proxy |
| `PY_BACKEND_URL` | no | `http://127.0.0.1:8000` | Python service URL |
| `SESSION_SECRET` | no | — | Session cookie secret |
| `SESSION_TTL_MS` | no | — | Session TTL in milliseconds |
| `API_PAYLOAD_MAX_SIZE` | no | `7mb` | Express JSON body size limit |
| `PORT` | no | `5000` | Injected by Cloud Run; local uses `API_BACKEND_PORT` |

**`frontend/.env`** (optional):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `VITE_API_BASE` | no | `''` (same-origin) | Override API base URL for remote deployments |

### Run

**Docker Compose (recommended):**

```bash
docker compose up --build
```

App is at `http://localhost:5001`.

**Native dev (hot-reload):**

```bash
npm run dev
```

Starts Vite (`:5173`), Node (`:5000`), and Python uvicorn (`:8000`) concurrently.
App is at `http://localhost:5173`.

### Ingest a filing

**Via the UI:** Open the Documents tab → search for a company → click "Fetch
filing". The filing is fetched from SEC EDGAR, embedded, and stored in RavenDB.
Status polls every 2.5 seconds (queued → indexing → indexed).

**Via CLI (bulk):**

```bash
# Single ticker
python -m backend.scripts.bulk_ingest --tickers AAPL

# Multiple tickers
python -m backend.scripts.bulk_ingest --tickers AAPL,MSFT,NVDA

# From a text file (one ticker per line)
python -m backend.scripts.bulk_ingest --file tickers.txt

# Dry run (no embedding calls, no quota consumed)
python -m backend.scripts.bulk_ingest --tickers AAPL --dry-run
```

The script loads `backend/.env.python` automatically. It skips
already-indexed tickers and stops cleanly on daily quota exhaustion — re-run
the next day to continue from where it left off.

---

## Deployment — Google Cloud Run

Two Cloud Run services:

| Service | Image source | What it runs |
|---|---|---|
| `node-service` | `backend/Dockerfile.node` | Express + React bundle + Vertex auth proxy |
| `python-service` | `backend/Dockerfile.python` | FastAPI + ingest queue + GraphRAG |

**Infrastructure:**
- Container images stored in **Artifact Registry**
- Secrets (API keys, RavenDB client cert) in **Secret Manager**, mounted as
  env vars or files into the Cloud Run services
- Database: **RavenDB Cloud**; the Python service connects with a client
  certificate PEM mounted from Secret Manager
- `node-service` reaches `python-service` via `PY_BACKEND_URL` over the
  Cloud Run internal network

**CI/CD (`.github/workflows/deploy.yml`):**

Every push to `main` triggers:
1. GCP auth via **Workload Identity Federation** (no stored service account keys)
2. `docker build` + `docker push` directly on the GitHub Actions runner
   (bypasses Cloud Build to avoid VPC Service Controls restrictions on Cloud Logging)
3. `gcloud run services update --image ...` — image-only update that preserves
   all existing env vars and secret mounts configured in the console

To deploy to your own project, update `PROJECT`, `REGION`, and `REGISTRY` in
`deploy.yml`, configure a Workload Identity Pool for your GitHub repo, and
grant the deploy service account `roles/run.developer` and
`roles/artifactregistry.writer`.

---

## Project structure

```
finsight/
├── compose.yaml                   # Docker Compose: node + python services
├── package.json                   # NPM workspace root; dev scripts
├── requirements.txt               # Python dependencies
│
├── backend/
│   ├── server.js                  # Node/Express: serves SPA, Vertex proxy, pyProxy
│   ├── Dockerfile.node            # Two-stage: Vite build → Express runtime
│   ├── Dockerfile.python          # python:3.11-slim → uvicorn
│   ├── .env.local                 # Node env (gitignored)
│   ├── .env.python                # Python env (gitignored)
│   │
│   ├── data_extract/
│   │   ├── app.py                 # FastAPI app + ingest queue daemon
│   │   ├── embeddings.py          # RavenDB client, Gemini embed, ingest/search
│   │   ├── extractor.py           # Pipeline orchestrator: EDGAR → metrics + sections
│   │   ├── sec_client.py          # All SEC EDGAR network calls
│   │   ├── facts.py               # XBRL → standardized financial fields
│   │   ├── ratios.py              # Computed financial ratios (ROE, current ratio, …)
│   │   ├── sections.py            # Filing section splitter (Risk Factors, MD&A, …)
│   │   ├── rag.py                 # RAG: retrieve chunks → Gemini generation
│   │   ├── compare_metrics.py     # /compare-metrics endpoint
│   │   ├── market.py              # /market endpoint (yfinance)
│   │   ├── search.py              # /search endpoint (SEC registry)
│   │   ├── sectors.py             # SIC code → GICS sector mapper
│   │   └── text_metrics.py        # Regex fallback metric extractor
│   │
│   ├── graph/
│   │   ├── router.py              # GraphRAG router: classifier + answer orchestrator
│   │   └── rdf_graph.py           # RDF/SPARQL graph (rdflib), OWL ontology
│   │
│   ├── analysis/                  # Standalone offline analysis tools
│   │   ├── charts.py              # Plotly chart generator
│   │   └── metrics.py             # XBRL extractor (standalone)
│   │
│   ├── scripts/
│   │   └── bulk_ingest.py         # CLI bulk ingestion; quota-aware, resumable
│   │
│   ├── services/
│   │   ├── pyProxy.js             # Node → Python HTTP forwarder
│   │   └── session.js             # Express session middleware
│   │
│   └── company_name/
│       └── sec_companies.json     # Full SEC ticker → CIK registry (~12 000 companies)
│
├── frontend/
│   ├── App.tsx                    # Root shell: layout, routing, document state
│   ├── types.ts                   # TypeScript types (Document, FilingMetrics, …)
│   ├── theme.ts                   # Design tokens: colors, fonts, breakpoints
│   ├── vite.config.ts             # Vite config + dev proxy to Node (:5000)
│   │
│   ├── components/
│   │   ├── Dashboard.tsx          # Metrics cards + margin chart + market snapshot
│   │   ├── ChatInterface.tsx      # Finch chat: markdown, citations, filter pills
│   │   ├── DocumentManager.tsx    # Filing fetch/upload, status badges, retry
│   │   ├── AnalysisView.tsx       # AI summary + two-company XBRL comparison charts
│   │   ├── HelpView.tsx           # Question tips, quality checker, FAQ
│   │   ├── GettingStarted.tsx     # Onboarding screen (no filings loaded)
│   │   ├── SplashScreen.tsx       # First-load landing screen
│   │   ├── SearchDropdown.tsx     # Autocomplete company dropdown
│   │   └── CompanyLogo.tsx        # Favicon-based company logo with fallbacks
│   │
│   ├── services/
│   │   └── gemini.ts              # All frontend fetch() wrappers for backend APIs
│   │
│   └── utils/
│       ├── company.ts             # Ticker → name/domain maps, companyLabel()
│       └── hooks.ts               # useDebounce, useIsTablet (matchMedia)
│
└── .github/
    └── workflows/
        └── deploy.yml             # CI/CD: WIF auth → docker build → Cloud Run deploy
```

---

## Known limitations

**Gemini embedding quota.** The free tier allows 1 000 embedding requests per
day. A typical 10-K produces ~200–400 chunks. Filings that hit the daily quota
automatically retry with exponential backoff (30 min → 6 hr max). Use
`bulk_ingest.py` to spread large jobs across multiple days; already-indexed
filings are always skipped.

**Graph requires a filing extract after Python restart.** The in-memory RDF
graph is rebuilt at startup from the `FilingMetrics` RavenDB collection. If
`FilingMetrics` is populated, graph features are available immediately. If the
collection is empty (fresh database), structured metric questions fall back to
`vector_no_graph` until the first `/extract/{ticker}` call.

**Silent DB degradation on startup.** RavenDB connection calls in the FastAPI
lifespan handler are wrapped in `try/except`. If RavenDB is unreachable, the
service still reports healthy and graph/vector features silently degrade. Check
logs for `Could not load FilingMetrics` or connection errors.

**Responsive layout.** The frontend targets desktop (>1024 px) and tablet
(768–1024 px). Mobile layout is best-effort.

**XBRL extraction accuracy.** Metrics are extracted from standardized us-gaap
concept names. Some filers use non-standard or legacy tags; missing fields are
left absent rather than estimated. Always verify key figures against the
original SEC filing.
