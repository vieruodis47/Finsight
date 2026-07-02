/**
 * Forwards FinSight API requests from Node (:5000) to the Python/FastAPI
 * service (:8000), which owns all Gemini calls (RAG, summaries, comparisons).
 *
 * Node stays responsible for auth (Vertex ADC proxy), sessions, and serving
 * the React bundle; Python stays responsible for data + AI.
 */
import fetch from 'node-fetch';

export const PY_BACKEND_URL = process.env.PY_BACKEND_URL || 'http://127.0.0.1:8000';

export async function pythonApiForwarder(req, res) {
  const url = PY_BACKEND_URL + req.originalUrl;
  const init = {
    method: req.method,
    headers: {
      'Content-Type': req.headers['content-type'] || 'application/json',
      Accept: req.headers['accept'] || 'application/json',
      'X-Session-Id': req.sessionID || '',
    },
  };
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = JSON.stringify(req.body ?? {});
  }

  try {
    const upstream = await fetch(url, init);
    res.status(upstream.status);
    const contentType = upstream.headers.get('content-type');
    if (contentType) res.set('Content-Type', contentType);
    res.send(await upstream.text());
  } catch (err) {
    console.error(`[pyProxy] ${req.method} ${req.originalUrl} -> ${url} failed:`, err.message);
    res.status(502).json({
      error: 'Python backend unreachable',
      detail: `Is the FastAPI service running? Expected at ${PY_BACKEND_URL}. Start it with: npm run dev-python`,
    });
  }
}
