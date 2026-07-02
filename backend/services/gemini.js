/**
 * REMOVED (2026-07-01): Node no longer calls Gemini.
 *
 * All Gemini generation lives in the Python/FastAPI service:
 *   backend/data_extract/rag.py  (model: GEMINI_GEN_MODEL, default gemini-1.5-flash)
 * Node forwards /api/* to it via backend/services/pyProxy.js.
 *
 * This file is kept as a tombstone so stale imports fail loudly.
 * See .claude/MANIFEST.md entry M-2. Safe to delete.
 */
export function askGemini() {
  throw new Error(
    'askGemini was removed from Node. Gemini calls live in the Python service (backend/data_extract/rag.py); use the /api/chat route forwarded by pyProxy.js.'
  );
}
