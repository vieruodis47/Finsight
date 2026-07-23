# FinSight

A hybrid GraphRAG financial research assistant. Load SEC 10-K filings, then ask
natural-language questions and get answers grounded in both **structured XBRL
financial data** (revenue, margins, ratios) and **unstructured filing text**
(risk factors, MD&A, guidance). Two retrieval paths — a SPARQL graph and a
vector similarity index — are selected per-question by a keyword heuristic
router with no LLM call needed for routing.

Embeddings run **in-process** with the MIT-licensed `bge-m3` model (1024-dim,
no API, no quota); answer generation uses Gemini.

> **Architecture deep-dive:** see [ARCHITECTURE.md](./ARCHITECTURE.md) for the
> service topology, the GraphRAG router, the embedding design, the data
> pipeline, the RavenDB storage model, and the full component map.

---

## At a glance

```
Browser ─▶ Node/Express (server.js) ─▶ Python/FastAPI (data_extract/app.py)
                │                              │
     serves React SPA + Vertex          ├─▶ RavenDB (chunks, metrics, jobs)
     AI auth proxy                      ├─▶ bge-m3 in-process (1024-dim embeddings)
                                        └─▶ Gemini / Vertex AI (answer generation)
```

- **Node/Express** serves the React bundle, proxies Vertex AI (auth + rate
  limiting + SSRF guard), and forwards API routes to Python.
- **Python/FastAPI** runs the filing pipeline, the GraphRAG router, the ingest
  queue, and the market/search/compare endpoints.
- **RavenDB** stores filing chunks (with embedding vectors), XBRL metrics,
  ingest manifests, and queue state.
- **bge-m3** (via `sentence-transformers`) embeds text on-CPU, in-process — the
  same encoder for ingest and query.
- **Gemini** (`gemini-1.5-flash` by default) generates the grounded answers.

Key API routes forwarded to Python: `/extract`, `/metrics`, `/api/chat`,
`/market`, `/search`, `/compare-metrics`, `/indexed`, `/ingest-status`,
`/health`.

---

## Setup — local development

### Prerequisites

- Docker Desktop (for the compose stack)
- Node.js 20+
- Python 3.11+
- A running RavenDB instance (see below)
- Gemini API key ([free tier](https://aistudio.google.com)) — used for answer
  **generation** only; embeddings are local and need no key
- Google Cloud project with Vertex AI API enabled (for the Node auth proxy)

> On first run the `bge-m3` weights (~2 GB) are downloaded to the
> `sentence-transformers` cache. The Docker image bakes them in at build time;
> native dev fetches them once on the first embed.

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

# Python dependencies (includes torch CPU + sentence-transformers)
pip install -r requirements.txt
```

### Environment variables

Create two env files (both are gitignored):

**`backend/.env.python`** — Python/FastAPI service:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | **yes** | — | Gemini API key for answer **generation** |
| `RAVENDB_URLS` | no | `http://127.0.0.1:8080` | Comma-separated RavenDB node URLs |
| `RAVENDB_DATABASE` | no | `finsight` | RavenDB database name |
| `RAVENDB_CERT_PATH` | no | — | Path to client cert PEM (RavenDB Cloud only) |
| `GEMINI_GEN_MODEL` | no | `gemini-1.5-flash` | Generation model name |
| `EMBED_MODEL` | no | `BAAI/bge-m3` | In-process embedding model |
| `EMBED_MODEL_REVISION` | no | pinned `5617a9f…` | HF revision (keep in sync with the baked image) |
| `EMBED_DIM` | no | `1024` | Embedding dimension (fixed by bge-m3; must match existing index) |
| `EMBED_BATCH` | no | `32` | Texts per encode batch |
| `SEC_USER_AGENT` | no | `FinSight contact@example.com` | SEC rate-limit header — set to your own email |
| `FRONTEND_ORIGIN` | no | — | CORS allowed origin (e.g. `http://localhost:5173`) |
| `UPLOAD_MAX_MB` | no | `50` | Max file size for PDF/TXT uploads |

> **Embeddings are quota-free.** Because bge-m3 runs in-process, there is no
> per-day/per-minute embedding quota. The legacy `QUOTA_DEADLINE_HOURS` var and
> the `waiting_for_quota` job states remain in the code but no longer fire.

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

# Dry run (no embedding, no writes)
python -m backend.scripts.bulk_ingest --tickers AAPL --dry-run
```

The script loads `backend/.env.python` automatically and skips already-indexed
tickers.

---

## Deployment — Google Cloud Run

Two Cloud Run services:

| Service | Image source | What it runs |
|---|---|---|
| `node-service` | `backend/Dockerfile.node` | Express + React bundle + Vertex auth proxy |
| `python-service` | `backend/Dockerfile.python` | FastAPI + ingest queue + GraphRAG + bge-m3 |

**Infrastructure:**
- Container images stored in **Artifact Registry**. `Dockerfile.python` installs
  CPU-only `torch` from the PyTorch CPU wheel index and bakes the pinned bge-m3
  weights into an image layer, so a scaled-to-zero instance never does a runtime
  model fetch.
- Secrets (API keys, RavenDB client cert) in **Secret Manager**, mounted as
  env vars or files into the Cloud Run services.
- Database: **RavenDB Cloud**; the Python service connects with a client
  certificate PEM mounted from Secret Manager.
- `node-service` reaches `python-service` via `PY_BACKEND_URL` over the
  Cloud Run internal network.

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
├── ARCHITECTURE.md                # Deep-dive: topology, router, pipeline, storage
├── compose.yaml                   # Docker Compose: node + python services
├── package.json                   # NPM workspace root; dev scripts
├── requirements.txt               # Python dependencies (incl. torch + bge-m3)
│
├── backend/
│   ├── server.js                  # Node/Express: serves SPA, Vertex proxy, pyProxy
│   ├── Dockerfile.node            # Two-stage: Vite build → Express runtime
│   ├── Dockerfile.python          # python:3.11-slim → CPU torch + baked bge-m3 → uvicorn
│   ├── data_extract/              # FastAPI app, embeddings, extractor, endpoints
│   ├── graph/                     # GraphRAG router + RDF/SPARQL graph
│   ├── analysis/                  # Standalone offline analysis tools
│   ├── scripts/bulk_ingest.py     # CLI bulk ingestion; resumable
│   ├── services/                  # pyProxy.js, session.js
│   └── company_name/              # SEC ticker → CIK registry
│
├── frontend/
│   ├── App.tsx                    # Root shell: layout, routing, document state
│   ├── components/                # Dashboard, ChatInterface, CompareView, …
│   ├── services/gemini.ts         # Frontend fetch() wrappers for backend APIs
│   └── utils/                     # Ticker maps + React hooks
│
└── .github/workflows/deploy.yml   # CI/CD: WIF auth → docker build → Cloud Run
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the annotated, file-by-file
component map.

---

## Known limitations

**Graph requires a filing extract after a fresh database.** The in-memory RDF
graph is rebuilt at startup from the `FilingMetrics` RavenDB collection. If it
is populated, graph features are available immediately. If empty (fresh
database), structured metric questions fall back to `vector_no_graph` until the
first `/extract/{ticker}` call.

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
