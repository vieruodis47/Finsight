---
description: Review Dockerfiles and deployment workflows against the FinSight deployment checklist (guide, don't rewrite)
argument-hint: [path to Dockerfile/workflow, or blank to review all]
---

Review the Dockerfile(s)/deployment workflow(s): $ARGUMENTS (default: every Dockerfile, compose file, and CI workflow in the repo).

Role: GUIDE, not implementer. Report issues ranked by severity with file:line, explain *why* each is wrong, and pose the fix as a question or exercise. Do not rewrite the files unless explicitly asked.

## Build correctness
- Instruction order: does every RUN only use files/layers that exist above it?
- COPY local files (requirements.txt, package.json, source) instead of curl-ing them from GitHub at build time; no secrets for things already in build context.
- Shell syntax inside RUN: `&&` between commands; no malformed flags (e.g. spaces inside `--mount=type=secret,id=...`).
- Layer caching: dependency files copied and installed BEFORE app source, so code changes don't re-install deps.
- Is the app actually in the image? COPY of source, EXPOSE, and a CMD/ENTRYPOINT that would really start the service.

## FinSight-specific
- Python service: CMD must bind uvicorn to 0.0.0.0:$PORT (Cloud Run injects PORT; never hardcode 8000). Build context must be repo root because the import path is `backend.data_extract.app:app`.
- Node service: multi-stage — stage 1 builds frontend/dist, stage 2 runs server.js with dist baked in. A separate frontend image is NOT part of this architecture; flag any frontend/Dockerfile.
- Base images match runtimes: python:3.11-slim for FastAPI, node:20-slim for Express. Flag python bases in Node/React images (copy-paste artifact).
- Env/secrets: GEMINI_API_KEY, RAVENDB_URLS/DATABASE, PROXY_HEADER, SESSION_SECRET, PY_BACKEND_URL via runtime env / Secret Manager — never baked into the image or .dockerignore-leaked (.env files must be in .dockerignore).
- .dockerignore: node_modules, .venv/myenv, .git, company_data, experiments/rag/results, .claude excluded?

## Cloud Run runtime traps
- RavenDB cannot run on Cloud Run (stateful) — must be RavenDB Cloud / GCE VM.
- In-memory sessions and the in-memory ingest-status registry break under autoscaling — require max-instances=1 or an external store; ingest background threads need CPU-always-allocated or Cloud Run Jobs.
- ADC: local gcloud login doesn't exist in containers; Cloud Run uses the service's service account.

## Wrap-up
- Suggest the verification loop: `docker build` → `docker run -e PORT=8080 ...` → `curl :8080/health`.
- Log recurring/new failure patterns to `.claude/memory/integration-memory.md` (Deployment section) and, for significant findings, an evidence report. Update this checklist when a new class of mistake shows up.
