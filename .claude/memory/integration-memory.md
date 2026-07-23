# FinSight Integration Memory (long-term)

Maintained by the gemini-integration agent. Append/correct facts after every task. Never wipe; supersede with dated corrections.

## Verified seam map (2026-07-01)

- Frontend `frontend/services/gemini.ts`: `API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'` -> Python FastAPI. Calls `/api/chat`, `/api/summary`, `/api/compare`.
- Vite proxy (`frontend/vite.config.ts`): only `/api-proxy` and `/ws-proxy` -> Node :5000. Plain `/api/*` is NOT proxied.
- Python routers (`backend/data_extract/app.py`): rag.py prefix `/api` (chat/summary/compare), market.py prefix `/market`, search.py prefix `/search`, compare_metrics.py NO prefix. Also `/health`, `/extract/{ticker}`, `/ingest-status/{ticker}`.
- Node `backend/server.js` (:5000): `/api/chat` -> `services/gemini.js askGemini()`; `/api-proxy` + `/ws-proxy` Vertex AI proxy with GoogleAuth ADC, rate-limited, SSRF-guarded. Exits at boot if `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, or `PROXY_HEADER` unset.
- Gemini access: Node = `@google/genai`, model `gemini-2.5-flash`, `GEMINI_API_KEY` (throws at import if missing). Python = `google-genai` via `embeddings.get_genai_client()` (key mode if `GEMINI_API_KEY` set, else Vertex mode), model `GEMINI_GEN_MODEL ?? gemini-1.5-flash`.
- Python RAG: RavenDB vector search (`RAVENDB_URLS`, `RAVENDB_DATABASE`) -> grounded generation with inline citation tags `[TICKER FORM #N]`.
- Tests: `tests/backend_tests/data_extract_unit_tests/` (pytest). No frontend or Node tests as of 2026-07-01.

## Known issues / open questions

- DUPLICATION: `/api/chat` implemented in both Node and Python with different models and prompts. Frontend default hits Python. Node's copy may be dead code from the Vertex AI Studio template — confirm before removing.
- Prompt drift: FinSight system prompt duplicated in `gemini.js` (no citation rule) and `rag.py` (citation rule).
- `compare_metrics.py` router has no prefix — verify its routes don't collide with app-level routes.
- README's `npm run dev` starts frontend+Node only; the Python FastAPI service must be started separately (uvicorn, port 8000).

## Pitfalls learned

- (add entries here: date — pitfall — how detected — rule to avoid it)

## Rewire 2026-07-01 (supersedes parts of the seam map above)

- Gemini is called ONLY from Python (`rag.py`, `GEMINI_GEN_MODEL ?? gemini-1.5-flash`). Node's `services/gemini.js` is a throwing tombstone — do not re-import.
- Node (:5000) now: `sessionMiddleware` (signed cookie `finsight.sid`, in-memory store, `SESSION_SECRET`/`SESSION_TTL_MS`), `GET /api/session`, forwards `/api /extract /ingest-status /market /search /compare-metrics /health` to `PY_BACKEND_URL ?? http://127.0.0.1:8000` (adds `X-Session-Id`), serves `frontend/dist` + SPA fallback when it exists. Vertex proxy untouched.
- Ordering facts: `app.get('/api/session')` is defined BEFORE the forwarder so it wins; Express mount `'/api'` does NOT match `/api-proxy` (path-boundary matching); in vite.config.ts `/api-proxy` must stay listed before `/api` (prefix order matters there).
- Frontend `API_BASE` defaults to `''` (same-origin). Dev: Vite proxies all API prefixes to Node :5000. `FRONTEND_ORIGIN` CORS in app.py now only matters for direct :8000 access.
- Python env file is `backend/.env.python` (loaded by app.py before imports). Node env file is `backend/.env.local`.
- Root scripts: `dev` = vite+node+python via concurrently (needs venv active); `dev-python`; `build`; `start`.

## Pitfalls learned

- 2026-07-01 — OneDrive-synced repo: the shell sandbox mount can lag minutes behind file-tool writes (saw truncated `server.js` mid-sync). Rule: on unexpected truncation/syntax errors in bash, re-check with the Read tool before assuming the file is broken; verify against a /tmp copy if needed.
- 2026-07-02 — Extraction outputs: `extractor.py` CLI writes `<TICKER>_<FORM>.json` to `OUTPUT_DIR` = repo-root `company_data/` (anchored via `Path(__file__).parents[2]`, not cwd). `app.py /extract` returns JSON only, never writes. Nothing in the repo reads these JSON artifacts.

## Deployment (2026-07-06)

- Branch: `deployment`. Target: two Cloud Run services (finsight-node public, finsight-python internal ingress); RavenDB CANNOT run on Cloud Run — RavenDB Cloud or GCE VM.
- Draft Dockerfiles exist at `backend/data_extract/Dockerfile` and `frontend/Dockerfile` (the latter is a python-base copy-paste and should likely be deleted — Node serves the bundle). Known draft bugs logged in MANIFEST M-5; run /docker-review on each iteration.
- Cloud Run traps for THIS codebase: in-memory sessions (session.js) and in-memory ingest-status registry (app.py) break under autoscaling → max-instances=1 for demos; uvicorn must bind $PORT; ADC comes from the service account, not gcloud login.
- Architecture diagram (current + planned): `docs/architecture.svg`.
- 2026-07-06 — Deployment doc consolidated at repo-root `README.Docker.md` (Docker architecture description + Cloud Run guide). `docs/DEPLOY.md` deleted by user; the earlier "move" left only a docker-init stub, content restored from session context (M-6 updated). `docs/architecture.svg` also appears deleted from docs/ — re-present if user asks.
- 2026-07-07 — Docker build failed with "invalid file request .claude/agents/.probe": stray probe file (OneDrive sync state) inside build context. Fix + prevention: .dockerignore must exclude `.claude/`, `.env*`, `.venv/`, `myenv/`, `company_data/`, `experiments/`, `tests/`, `docs/` — also shrinks context from ~60MB to a few MB. Delete .probe (user-side). RavenDB local: container needs no pre-setup (Unsecured mode), but the `finsight` database must be created once via Studio (localhost:8080) — python client does not auto-create it.
- 2026-07-07 — MILESTONE: docker compose stack builds and runs (node + python + ravendb) on `deployment` branch. Final Dockerfile fixes: stage 1 uses root-lockfile workspace install (`npm ci --workspace=frontend`; frontend/package-lock.json is stale — recommended git rm), node image uses built-in `node` user (NO useradd; exit code 9 = user exists), python image needs `useradd app`. Remaining before cloud: RavenDB `finsight` db creation via Studio, GEMINI_API_KEY into .env.python, then Artifact Registry push + Cloud Run Scenario C.
- 2026-07-07 — Merge conflict pitfall: `git add . && git commit` during unresolved merge committed conflict markers into .gitignore and backend/services/gemini.js (found via `git grep -n -e "^<<<<<<< " -e "^>>>>>>> "`; fixed by hand + `commit --amend`). Semantic conflict: teammate improved Node askGemini prompt (structured Answer/Evidence/Takeaways, conflict-handling rules) while deployment branch tombstoned it — resolution: keep tombstone, PORT the improved prompt into rag.py SYSTEM_PROMPT (pending). Team is actively committing to the Node Gemini path — coordinate before merges.
- 2026-07-07 — Model standard changed (team decision, arrived via main merge): generation model is now `gemini-3.1-lite` (rag.py default). SUPERSEDES all earlier gemini-1.5-flash references. Gotcha: any GEMINI_GEN_MODEL line in a developer's .env.python overrides the code default — remove/update it. Embedding model unchanged (gemini-embedding-001). gemini.js (dead code) still says 2.5-flash — irrelevant to runtime.
