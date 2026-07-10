---
description: Audit all cross-runtime API contracts (React <-> Node <-> Python) for drift
---

Audit the integration contracts. For each boundary, report OK / DRIFT / BROKEN with file:line evidence.

1. Enumerate routes on each side:
   - Python: `grep -rn "@app\.\|@router\.\|APIRouter(" backend/data_extract backend/analysis` (note router prefixes)
   - Node: `grep -n "app\.\(get\|post\|put\|delete\|use\)" backend/server.js`
   - Frontend calls: `grep -rn "fetch(\|API_BASE" frontend/services frontend/components`
2. For every frontend call, confirm a matching route exists on the runtime that `API_BASE`/vite proxy actually sends it to. Flag routes served by BOTH runtimes (known: `/api/chat`).
3. For each matched route, diff the shapes: TS interface fields vs Express `res.json(...)` keys vs Pydantic `response_model` fields. Flag missing/extra/renamed fields and optionality mismatches.
4. Check env-var and port assumptions: `VITE_API_BASE`, vite proxy targets, `API_BACKEND_PORT`, uvicorn port.
5. Check Gemini config parity: model names and system prompts in `backend/services/gemini.js` vs `backend/data_extract/rag.py`.

End by updating `.claude/memory/integration-memory.md` with any newly discovered or corrected facts, and write a report to `.claude/evidence/reports/` if anything is BROKEN.
