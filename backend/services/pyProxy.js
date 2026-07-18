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
    // Forward the body as BINARY. Using upstream.text() here decodes the bytes as
    // UTF-8, which silently corrupts non-text responses like the Analysis PDF
    // (mangled flate streams). Buffering the raw bytes is correct for JSON too.
    const contentDisposition = upstream.headers.get('content-disposition');
    if (contentDisposition) res.set('Content-Disposition', contentDisposition);
    res.send(Buffer.from(await upstream.arrayBuffer()));
  } catch (err) {
    console.error(`[pyProxy] ${req.method} ${req.originalUrl} -> ${url} failed:`, err.message);
    res.status(502).json({
      error: 'Python backend unreachable',
      detail: `Is the FastAPI service running? Expected at ${PY_BACKEND_URL}. Start it with: npm run dev-python`,
    });
  }
}

/**
 * Streaming variant for endpoints that return a chunked/NDJSON stream
 * (currently /api/chat/stream). The default forwarder above calls
 * `res.send(await upstream.text())`, which BUFFERS the entire upstream body
 * before responding — that silently defeats token streaming (the browser gets
 * the whole answer at once). Here we instead pipe the upstream Node stream
 * straight to the client and disable buffering/transforms, so chunks arrive
 * incrementally.
 */
export async function streamingApiForwarder(req, res) {
  const url = PY_BACKEND_URL + req.originalUrl;
  const init = {
    method: req.method,
    headers: {
      'Content-Type': req.headers['content-type'] || 'application/json',
      Accept: 'application/x-ndjson',
      'X-Session-Id': req.sessionID || '',
    },
    body: JSON.stringify(req.body ?? {}),
  };

  try {
    const upstream = await fetch(url, init);
    res.status(upstream.status);
    res.set('Content-Type', upstream.headers.get('content-type') || 'application/x-ndjson');
    // No compression, no proxy buffering, keep the connection open for chunks.
    res.set('Cache-Control', 'no-cache, no-transform');
    res.set('X-Accel-Buffering', 'no');
    res.set('Connection', 'keep-alive');
    // Send small chunks immediately rather than coalescing them (Nagle off).
    res.socket?.setNoDelay?.(true);
    res.flushHeaders?.();

    // node-fetch (v3) exposes the body as a Node Readable, so pipe streams the
    // response chunk-by-chunk with no intermediate buffering.
    upstream.body.on('error', (err) => {
      console.error(`[pyProxy stream] upstream error on ${req.originalUrl}:`, err.message);
      res.end();
    });
    upstream.body.pipe(res);
  } catch (err) {
    console.error(`[pyProxy stream] ${req.method} ${req.originalUrl} -> ${url} failed:`, err.message);
    if (!res.headersSent) {
      res.status(502).json({
        error: 'Python backend unreachable',
        detail: `Is the FastAPI service running? Expected at ${PY_BACKEND_URL}.`,
      });
    } else {
      res.end();
    }
  }
}
