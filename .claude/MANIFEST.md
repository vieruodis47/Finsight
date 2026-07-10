# Change Manifest (AHE decision observability)

Every non-trivial edit — application seam code or harness files — gets an entry with a falsifiable prediction. Next verification pass sets the verdict. Ineffective edits get reverted (git, file-level).

Format:

## M-<n> — <date> — <component: app-seam | agent | command | memory | hook>
- **Evidence:** report/observation that motivated the edit
- **Root cause:** inferred cause
- **Edit:** files changed, one-line summary
- **Predicted fixes:** what should now work (testable)
- **At-risk regressions:** what this could break (testable)
- **Verdict:** pending | confirmed | reverted (+ date, evidence)

---

## M-1 — 2026-07-01 — harness (seed)
- **Evidence:** AHE paper (arXiv:2604.25850); repo audit of frontend/backend seams
- **Root cause:** no harness existed; integration knowledge lived nowhere
- **Edit:** seeded `.claude/` — gemini-integration agent, 4 commands, memory, evidence corpus, trace hook, this manifest
- **Predicted fixes:** integration tasks start with correct seam facts (duplicate /api/chat, model/prompt drift, env surfaces); failures leave reusable evidence
- **At-risk regressions:** hook overhead on every tool call; memory could go stale if not maintained
- **Verdict:** pending

## M-2 — 2026-07-01 — app-seam
- **Evidence:** M-1 audit: duplicate `/api/chat` (Node + Python), model drift (2.5-flash vs 1.5-flash), prompt drift, frontend bypassing Node, README missing Python run instructions
- **Root cause:** Node retained a template-era Gemini path; no single owner per responsibility
- **Edit:** Python owns ALL Gemini calls (rag.py, gemini-1.5-flash default). Node = sessions (`services/session.js`), FinSight API forwarding to :8000 (`services/pyProxy.js`), Vertex ADC proxy (untouched), serves `frontend/dist`. `services/gemini.js` -> throwing tombstone. Frontend `API_BASE` -> same-origin; vite proxies all API paths to :5000. Root scripts: `dev-python`, 3-way `dev`, `build`, `start`. README rewritten; requirements.txt gained google-genai, python-dotenv, ravendb, yfinance, numpy, pandas
- **Predicted fixes:** one Gemini owner/model/prompt; sessions on every API call (X-Session-Id reaches Python); `npm run dev` boots all three; production = build + `npm start`
- **At-risk regressions:** anything importing `askGemini` now throws (intended); dev API calls fail if Node is down even though Python is up (extra hop); `/api-proxy` behavior must remain identical (mounted after forwarder — verify); `npm run dev` fails if venv inactive
- **Verdict:** pending — verify by running the three servers with real keys

## M-3 — 2026-07-02 — harness (RAG experimentation)
- **Evidence:** user request to prove GraphRAG superiority vs Naive/Agentic/Modular RAG; code audit showing production pipeline is actually Naive/vector RAG (no graph structures in embeddings.py/rag.py)
- **Root cause:** harness had no experiment substrate; team's architecture belief ("we use GraphRAG") contradicted the code
- **Edit:** added `agents/rag-experiment.md`; commands `/rag-experiment`, `/rag-eval`, `/rag-verdict`; `EXPERIMENTS.md` pre-registration ledger + leaderboard; `memory/rag-memory.md` (with the GraphRAG correction); `evidence/experiments/`; repo substrate `experiments/rag/` (eval schema, results conventions); defined variant contract for `backend/data_extract/rag_variants/`
- **Predicted fixes:** architecture claims become pre-registered, falsifiable experiments; eval-set versioning prevents mid-experiment drift; slice-by-question-type reporting surfaces where architectures actually differ
- **At-risk regressions:** experiments need live GEMINI_API_KEY + RavenDB + ingested filings (agent instructed to halt, not simulate); LLM-judge scores need the mandated 10% manual spot-check to stay trustworthy
- **Verdict:** pending — validated by the first completed /rag-experiment round

## M-4 — 2026-07-02 — app-seam (extraction output path)
- **Evidence:** user report: data_extract CLI dumps `<TICKER>_<FORM>.json` into the repo root (cwd-relative path in extractor.py `__main__`)
- **Root cause:** `output_file` was a bare relative filename, so output landed wherever the command ran
- **Edit:** `extractor.py`: added `OUTPUT_DIR = <repo root>/company_data` anchored via `Path(__file__)`; CLI now mkdirs and writes there. Grep confirmed no code reads the root JSONs (company_data copies already existed)
- **Predicted fixes:** `python -m backend.data_extract.extractor <TICKER>` writes to `company_data/` from any cwd; repo root stays clean
- **At-risk regressions:** any external script/notebook expecting `./<TICKER>_10K.json` in cwd breaks (none found in repo)
- **Verdict:** pending

## M-5 — 2026-07-06 — harness (deployment guidance)
- **Evidence:** review of draft Dockerfiles on `deployment` branch: pip-install-before-COPY ordering, curl-ing requirements.txt from GitHub with a secret mount, malformed RUN (`pip install --upgrade pip pip install -r ...`), space in `--mount=type=secret, id=env`, no source/CMD/EXPOSE in image, frontend/Dockerfile is a python:3.11-slim copy-paste
- **Root cause:** no deployment-review component in the harness; Dockerfile knowledge lived only in chat
- **Edit:** added `commands/docker-review.md` (severity-ranked checklist: build correctness, FinSight-specific rules, Cloud Run traps; guide-not-implementer mode); added Deployment section to integration memory; `docs/architecture.svg` documents current vs planned deployment
- **Predicted fixes:** every future Dockerfile/workflow iteration gets the same checklist via /docker-review; repeat mistakes (ordering, copy-paste bases, missing CMD) get caught without re-deriving the review
- **At-risk regressions:** checklist could go stale as Cloud Run evolves — command instructs updating it when new mistake classes appear
- **Verdict:** pending — confirmed when the next /docker-review catches a real issue

## M-6 — 2026-07-06 — harness (Cloud Run runbook)
- **Evidence:** user request for run instructions covering all deploy scenarios once Dockerfiles/compose are done
- **Root cause:** deployment knowledge scattered across chat; no runbook in repo
- **Edit:** added `docs/DEPLOY.md` — pre-deploy code checklist ($PORT/0.0.0.0 gap in server.js flagged), one-time GCP setup, build/push, scenarios: backend-only, node+bundle, full stack, backend lockdown (IAM vs shared header), static-frontend alternative, day-2 ops, cost guardrails
- **Predicted fixes:** user can deploy any subset without re-deriving env vars/flags; max-instances=1 correctness constraint is documented where it's needed
- **At-risk regressions:** gcloud flags may drift from current docs (doc says verify); PORT checklist item requires either env workaround or code change before first deploy
- **Verdict:** pending — confirmed by first successful deploy following it

## M-9 — 2026-07-09 — app-seam (Gemini model id + credential fix)
- **Evidence:** user replaced GEMINI_API_KEY in .env.local; new key authenticates but `gemini-3.1-lite` returns 404 NOT_FOUND — the catalogue has `gemini-3.1-flash-lite`, no `gemini-3.1-lite` (team's 2026-07-07 model decision recorded a phantom id)
- **Root cause:** model id transcribed from memory, never validated against ListModels; expired key masked the 404 (auth failed before model resolution)
- **Edit:** GEMINI_GEN_MODEL="gemini-3.1-flash-lite" in backend/.env.python + .env.local; working key synced into .env.python (Python loads that file, user had updated .env.local only)
- **Predicted fixes:** generation works in experiments AND production /api/chat (old id would 404 there too); embeddings unaffected (gemini-embedding-001 exists)
- **At-risk regressions:** if the team intended a different 3.1 tier (e.g. flash vs flash-lite), quality/cost differ — verify with them; rag.py fallback default is still gemini-1.5-flash when env is missing
- **Verdict:** pending — confirmed by E-1 completing + a manual /api/chat check

## M-8 — 2026-07-09 — harness + app-seam (RAG experiment substrate built)
- **Evidence:** user request to compare RAG architectures per METRICS.md/SCHEMA.md; papers (Lewis RAG, FLARE, HyDE, Adaptive-RAG, CRAG, Self-RAG, RAPTOR, REPLUG, Modular RAG, MS GraphRAG, KG-RAG, agentic surveys) as design references
- **Root cause:** variant contract and eval machinery existed only as specs; no implementation
- **Edit:** `backend/data_extract/rag_variants/` (common.py instrumentation via shared-client wrapper — tokens/calls/inputs metered identically for all variants; naive/graph/hyde/agentic/modular + 4 prompt-axis variants; registry). `experiments/rag/runner.py` (shared, resume-safe, timeout, config-hash), `scorer.py` (METRICS.md v1 exact: deterministic numeric matcher w/ unit+period rules, blinded judges R1–R4, disk cache, slice aggregation), `ingest_eval_corpus.py` (N-year ingest + ingest-cost report). Eval v1: 16 test + 8 dev, all numerics XBRL-verified AND literal-string-verified in indexed sections; composition rules validated. E-1/E-2/E-3 pre-registered.
- **Predicted fixes:** any architecture claim is now a one-command experiment; scorer prevents per-paper metric drift (single implementation, versioned rubrics)
- **At-risk regressions:** client-wrapper metering monkeypatches the genai singleton (order-sensitive if other code re-creates the client); numeric matcher's sentence heuristic may under-credit answers with figures in tables (fallback judge logs these); infra: RavenDB now behind raven-proxy:8081 (data volume was empty — full re-ingest required); GEMINI_API_KEY in env files is an invalid AQ.-prefixed token (401) — runs blocked until replaced
- **Verdict:** pending — machinery smoke-tested offline (matcher unit cases pass, registry imports); confirmed when E-1 completes end-to-end
- **Report:** experiments/rag/RUNBOOK.md documents the execution path

## M-7 — 2026-07-07 — app-seam (prompt consolidation)
- **Evidence:** merge conflict in backend/services/gemini.js — teammate's improved structured prompt (Answer/Evidence/Takeaways, conflict-handling, exact-figure rules) landed on the dead Node path; user kept teammate's file but it is unreferenced (server.js no longer imports it)
- **Root cause:** prompt improvements were made on the Node Gemini path after that path was removed from serving traffic
- **Edit:** merged teammate's prompt into rag.py SYSTEM_PROMPT (the one that actually serves /api/chat), preserving the original inline [TICKER FORM #N] citation rules; gemini.js left as user resolved it (dead code)
- **Predicted fixes:** /api/chat answers gain structured format, conflict handling, exact-figure discipline, while keeping citations
- **At-risk regressions:** longer system prompt = more tokens per call; "respond exactly with..." sentence may appear alongside NO_CONTEXT_MESSAGE inconsistently; structured headers may not suit short factual queries (prompt says "when appropriate")
- **Verdict:** pending — check first real chat responses for format + citations
