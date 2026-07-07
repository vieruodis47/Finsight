# FinSight — Docker & Cloud Run

## Docker architecture

FinSight ships as **two images plus one external database**. The split follows the runtime ownership already in the code: Python owns AI/data, Node owns sessions/auth/serving, and RavenDB holds state — so state never lives inside a container.

```
┌─────────────────────────────┐   ┌──────────────────────────────┐
│ finsight-node                │   │ finsight-python               │
│ (multi-stage build)          │   │ (python:3.11-slim)            │
│                              │   │                               │
│ stage 1: node:20             │   │ COPY requirements.txt → pip   │
│   npm ci + vite build        │──▶│ COPY backend/                 │
│   → frontend/dist            │   │ CMD uvicorn ...app:app        │
│ stage 2: node:20-slim        │   │     --host 0.0.0.0 --port $PORT│
│   COPY dist + backend JS     │   │                               │
│   CMD node server.js         │   │ Gemini · RAG · SEC · market   │
│ sessions · Vertex proxy ·    │   └──────────────┬───────────────┘
│ pyProxy → PY_BACKEND_URL     │                  │
└─────────────────────────────┘                  ▼
                                   ┌──────────────────────────────┐
                                   │ RavenDB — NOT containerized   │
                                   │ on Cloud Run (stateful).      │
                                   │ compose: ravendb/ravendb svc  │
                                   │ cloud: RavenDB Cloud / GCE VM │
                                   └──────────────────────────────┘
```

Design decisions and why:

- **Two images, not three.** The React bundle is baked into `finsight-node` at build time (multi-stage), because Node already serves `frontend/dist` with an SPA fallback. A separate frontend image/nginx would add a hop and break same-origin session cookies. `frontend/Dockerfile` should not exist in this architecture.
- **Build context is the repo root** for both images. Python imports as `backend.data_extract.app:app` and the Node build needs `frontend/` + `backend/` — so `docker build -f backend/data_extract/Dockerfile .` (note the final `.`), never from inside the subfolder.
- **Dependency layers before source layers.** `COPY requirements.txt` / `COPY package*.json` and install first, `COPY` source after — code edits then reuse the cached dependency layer instead of re-installing on every build.
- **Configuration is injected at runtime, never baked in.** `GEMINI_API_KEY`, `RAVENDB_URLS/DATABASE`, `SESSION_SECRET`, `PROXY_HEADER`, `PY_BACKEND_URL` arrive as env vars (compose: `env_file`; Cloud Run: Secret Manager). `.env.local` / `.env.python` are in `.dockerignore`, and `VITE_API_BASE` stays unset at build time so the bundle is same-origin.
- **Ports:** containers listen on `$PORT` (Cloud Run injects it, typically 8080). Locally, compose maps them back to the familiar 5000/8000. Both services must bind `0.0.0.0` — a `127.0.0.1` bind looks healthy in logs but is unreachable from outside the container.
- **compose.yaml is the local mirror of the cloud topology:** three services (`node`, `python`, `ravendb`), one network, a named volume for RavenDB data, `depends_on: python` for node. What differs in the cloud is only *where* each box runs — the wiring (env var names, URLs, ports) is identical, which is what makes local testing meaningful.
- **Known stateful traps** (constrain scaling until fixed): sessions live in Node process memory and ingest status lives in Python process memory → both services run with `max-instances=1` on Cloud Run; Python also needs CPU-always-allocated so background ingestion threads survive after the response returns.

Local workflow:

```bash
docker compose up --build       # full stack + RavenDB at localhost:5000
docker compose logs -f python   # follow one service
docker compose down             # keep RavenDB volume; add -v to wipe it
```

---

# Cloud Run Deployment Guide

Assumes your `Dockerfile`s and `compose.yaml` are done. You run the commands; this doc is the map. Verify flag names against current docs — Cloud Run evolves.

## 0. Code checklist before ANY deploy (one-time)

Cloud Run injects the listen port as `$PORT` and requires binding `0.0.0.0`. The current code doesn't do either by default:

- [ ] **Node**: `server.js` reads `API_BACKEND_PORT` (not `PORT`) and defaults host to `127.0.0.1`. Either set env `API_BACKEND_PORT=8080` + `API_BACKEND_HOST=0.0.0.0` on the service (no code change), or make the code read `PORT` as fallback.
- [ ] **Python**: container CMD must be `uvicorn backend.data_extract.app:app --host 0.0.0.0 --port $PORT`.
- [ ] Frontend built with `VITE_API_BASE` **unset** (same-origin through Node).
- [ ] `.env.local` / `.env.python` in `.dockerignore` — secrets come from Secret Manager, never the image.
- [ ] RavenDB reachable from GCP (RavenDB Cloud URL or GCE VM) — it cannot run on Cloud Run.

## 1. One-time GCP setup

```bash
gcloud config set project $GOOGLE_CLOUD_PROJECT
gcloud config set run/region us-central1        # pick your region

gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com

# Image repository
gcloud artifacts repositories create finsight \
  --repository-format=docker --location=us-central1

# Secrets (repeat per secret)
echo -n "<value>" | gcloud secrets create GEMINI_API_KEY --data-file=-
echo -n "<value>" | gcloud secrets create SESSION_SECRET --data-file=-
echo -n "<value>" | gcloud secrets create PROXY_HEADER --data-file=-
# + RAVENDB_URLS if it embeds credentials
```

Grant the Cloud Run runtime service account `roles/secretmanager.secretAccessor`, and (for the Vertex proxy) `roles/aiplatform.user`.

## 2. Build & push images

From the **repo root** (build context must include `backend/` and `requirements.txt`):

```bash
REGION=us-central1
REPO=$REGION-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/finsight

# Option A: local Docker
docker build -f backend/data_extract/Dockerfile -t $REPO/finsight-python:v1 .
docker build -f backend/Dockerfile           -t $REPO/finsight-node:v1 .
gcloud auth configure-docker $REGION-docker.pkg.dev
docker push $REPO/finsight-python:v1 && docker push $REPO/finsight-node:v1

# Option B: no local Docker needed
gcloud builds submit --tag $REPO/finsight-python:v1 .   # with the right -f via cloudbuild.yaml
```

## 3. Scenario A — Backend only (Python API)

Use when: iterating on the API, or the frontend runs elsewhere (local dev, Vercel, etc.).

```bash
gcloud run deploy finsight-python \
  --image $REPO/finsight-python:v1 \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest \
  --set-env-vars GEMINI_GEN_MODEL=gemini-1.5-flash,RAVENDB_URLS=<url>,RAVENDB_DATABASE=<db> \
  --memory 1Gi --cpu 1 \
  --min-instances 0 --max-instances 1 \
  --no-cpu-throttling \
  --allow-unauthenticated        # TEMPORARY: see Scenario D to lock down
```

- `--max-instances 1` + `--no-cpu-throttling`: required because ingest status lives in process memory and ingestion runs in background threads.
- Test: `curl $(gcloud run services describe finsight-python --format='value(status.url)')/health`
- If the frontend calls this directly (no Node), set `FRONTEND_ORIGIN=<frontend url>` for CORS and `VITE_API_BASE=<this service url>` at frontend build time.

## 4. Scenario B — Frontend + middle tier (Node, bundle baked in)

Use when: Python is already deployed (or running elsewhere) and you're iterating on UI/Node.

```bash
PY_URL=$(gcloud run services describe finsight-python --format='value(status.url)')

gcloud run deploy finsight-node \
  --image $REPO/finsight-node:v1 \
  --set-secrets SESSION_SECRET=SESSION_SECRET:latest,PROXY_HEADER=PROXY_HEADER:latest \
  --set-env-vars API_BACKEND_PORT=8080,API_BACKEND_HOST=0.0.0.0,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=us-central1,PY_BACKEND_URL=$PY_URL \
  --memory 512Mi \
  --max-instances 1 \
  --allow-unauthenticated
```

- `--max-instances 1` because sessions are in-memory. Raise only after moving sessions to Redis/Memorystore.
- Test: open the service URL — Node serves the React bundle; `curl <url>/api/session` proves sessions; `curl <url>/health` proves the forward to Python.

## 5. Scenario C — Full stack from scratch

Order matters (Node needs Python's URL):

1. Deploy `finsight-python` (Scenario A).
2. Deploy `finsight-node` (Scenario B) with `PY_BACKEND_URL` pointing at it.
3. Smoke test through the front door: `curl -X POST <node-url>/api/chat -H 'Content-Type: application/json' -d '{"question":"test"}'`.

## 6. Scenario D — Locking down the backend (recommended follow-up)

`--allow-unauthenticated` on Python means anyone with the URL can hit your Gemini quota. Two options, cheapest first:

1. **Shared-header check** (no infra): Python middleware rejects requests missing a header Node sends (reuse the `PROXY_HEADER` pattern). Weak but better than nothing.
2. **Proper service-to-service auth**: redeploy Python with `--no-allow-unauthenticated`; grant Node's service account `roles/run.invoker` on it; Node's `pyProxy.js` must then attach an ID token (`google-auth-library`'s `getIdTokenClient(PY_URL)`) to each forward. Small code change — ask for a review when you do it.

Note: `--ingress internal` requires VPC networking between the services; for a prototype, IAM auth (option 2) is the simpler lockdown.

## 7. Scenario E — Frontend as pure static hosting (alternative)

If you ever split the frontend off Node: build `frontend/dist` with `VITE_API_BASE=<node-or-python url>` and host on Firebase Hosting or a GCS bucket + load balancer. Trade-off: you lose same-origin cookies (sessions need `SameSite=None; Secure` + CORS with credentials). Not recommended while sessions live in Node.

## 8. Day-2 operations

```bash
gcloud run services list
gcloud run services logs read finsight-python --limit 50      # or tail with --follow if supported
gcloud run revisions list --service finsight-node
gcloud run services update-traffic finsight-node --to-revisions <rev>=100   # rollback
gcloud run services delete finsight-python                    # teardown
```

Redeploys: bump the tag (`:v2`), push, `gcloud run deploy ... --image ...:v2`. Each deploy creates a revision; traffic splitting gives you canaries for free.

## 9. Cost guardrails (student project)

- `--min-instances 0` everywhere you can tolerate cold starts (Node yes; Python only if ingest isn't running).
- `--max-instances 1` is a hard spending cap (and correctness requirement here anyway).
- Set a billing budget alert on the project before the first deploy.
