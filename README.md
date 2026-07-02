# FinSight

SEC-filing research assistant: a React frontend, a Node.js middle tier, and a Python/FastAPI AI service.

This project is intended for demonstration and prototyping purposes only. It is not intended for use in a production environment.

## Architecture

```
Browser
  │
  ▼
React (Vite dev :5173 / built bundle served by Node)
  │  all API calls, same origin
  ▼
Node.js / Express (:5000)          ← auth (Google ADC Vertex proxy), sessions, serves React bundle
  │  forwards /api, /extract, /ingest-status, /market, /search, /compare-metrics, /health
  ▼
Python / FastAPI (:8000)           ← ALL Gemini calls (gemini-1.5-flash), RAG, SEC data, RavenDB
```

Only the Python service talks to Gemini (via `google-genai`, model `gemini-1.5-flash` by default). Node never calls Gemini; it owns browser sessions (signed cookie, `X-Session-Id` forwarded to Python), the authenticated Vertex AI proxy (`/api-proxy`, `/ws-proxy`), and serving the production frontend bundle.

## Prerequisites

*   **Node.js and npm** (Node 20+ recommended).
*   **Python 3.11+** with `pip`.
*   **[Google Cloud SDK / gcloud CLI](https://cloud.google.com/sdk/docs/install)** — only needed for the Vertex AI proxy routes:
    ```bash
    gcloud init
    gcloud auth application-default login
    ```

## Project Structure

*   `frontend/` — React + Vite app (TypeScript).
*   `backend/server.js`, `backend/services/` — Node/Express: sessions (`session.js`), Python forwarding (`pyProxy.js`), Vertex AI proxy.
*   `backend/data_extract/` — Python/FastAPI: SEC extraction, RAG chat, market data, search. Entry point `app.py`.
*   `backend/analysis/`, `backend/company_name/` — Python analysis and SEC registry helpers.
*   `tests/` — pytest suites for the Python backend.

## Environment Variables

### Node — `backend/.env.local`

*   `API_BACKEND_HOST` / `API_BACKEND_PORT`: where the Node server listens (default `127.0.0.1:5000`).
*   `API_PAYLOAD_MAX_SIZE`: max request payload (e.g. `5mb`).
*   `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`: required at boot (Vertex proxy).
*   `PROXY_HEADER`: required at boot; shared secret for `/api-proxy` requests.
*   `PY_BACKEND_URL`: Python service URL (default `http://127.0.0.1:8000`).
*   `SESSION_SECRET`: secret for signing session cookies (random per boot if unset).
*   `SESSION_TTL_MS`: session lifetime (default 8 hours).

### Python — `backend/.env.python`

*   `GEMINI_API_KEY`: Gemini Developer API key. (If unset, `embeddings.get_genai_client()` falls back to Vertex mode via ADC.)
*   `GEMINI_GEN_MODEL`: generation model (default `gemini-1.5-flash` — leave as is for now).
*   `RAVENDB_URLS` / `RAVENDB_DATABASE`: RavenDB vector store for RAG.
*   `FRONTEND_ORIGIN`: CORS origin for direct access (default `http://localhost:5173`; irrelevant when calls go through Node).

### Frontend

*   `VITE_API_BASE`: leave unset for same-origin (recommended); set only to point at a remote API.

## Setup

From the repo root:

```bash
# 1. Node + frontend dependencies
npm install

# 2. Python environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Then create/fill `backend/.env.local` and `backend/.env.python` (see above).

## Running (development)

**Option A — everything at once** (requires the Python venv active in the same shell):

```bash
npm run dev
```

This starts, via `concurrently`:
*   **vite** — React dev server at http://localhost:5173
*   **node** — Express at http://localhost:5000 (nodemon)
*   **python** — FastAPI at http://localhost:8000 (uvicorn --reload)

Open http://localhost:5173. Vite proxies all API paths to Node, which forwards FinSight routes to Python.

**Option B — three terminals** (easier to read logs):

```bash
# Terminal 1 — Python AI service (venv active)
npm run dev-python
# or directly: python -m uvicorn backend.data_extract.app:app --reload --port 8000

# Terminal 2 — Node server
npm run dev-backend

# Terminal 3 — React dev server
npm run dev-frontend
```

Quick health checks:

```bash
curl http://localhost:8000/health          # Python directly
curl http://localhost:5000/health          # Python via Node forwarder
curl http://localhost:5000/api/session     # Node session endpoint
```

## Running (production-style)

```bash
npm run build     # builds frontend/dist
npm run dev-python &   # or run uvicorn under a process manager
npm start         # Node serves frontend/dist + APIs at :5000
```

Open http://localhost:5000 — Node serves the React bundle and all API traffic.

## Tests

```bash
# Python (venv active)
python -m pytest tests/ -q

# Node syntax check
node --check backend/server.js
```

## Notes

*   `/api/chat`, `/api/summary`, `/api/compare` are implemented **only** in `backend/data_extract/rag.py`. The former Node implementation was removed (see `backend/services/gemini.js` tombstone and `.claude/MANIFEST.md`).
*   Do not modify the Vertex AI proxy machinery in `server.js` (rate limiter, SSRF guards) unless you know what you're doing.
*   Claude Code users: this repo has an integration harness under `.claude/` — start with `/contract-check`.
