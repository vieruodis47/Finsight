/**
 * Minimal cookie-based session middleware for FinSight (no extra deps).
 *
 * - Signed session ID cookie (HMAC-SHA256), httpOnly, sameSite=lax.
 * - In-memory store: sessions vanish on restart. Fine for this prototype;
 *   swap for express-session + a real store before production.
 * - Set SESSION_SECRET in backend/.env.local; otherwise a random secret is
 *   generated per boot (existing cookies become invalid on restart).
 *
 * Exposes on each request: req.sessionID (string), req.session (mutable object).
 */
import crypto from 'crypto';

const COOKIE_NAME = 'finsight.sid';
const TTL_MS = Number(process.env.SESSION_TTL_MS || 1000 * 60 * 60 * 8); // 8h
const SECRET = process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex');
if (!process.env.SESSION_SECRET) {
  console.warn('[session] SESSION_SECRET not set; using an ephemeral secret (sessions reset on restart).');
}

const store = new Map(); // sid -> { data, expiresAt }

function sign(id) {
  const mac = crypto.createHmac('sha256', SECRET).update(id).digest('base64url');
  return `${id}.${mac}`;
}

function unsign(value) {
  const i = value.lastIndexOf('.');
  if (i < 1) return null;
  const id = value.slice(0, i);
  const expected = sign(id);
  const a = Buffer.from(value);
  const b = Buffer.from(expected);
  if (a.length === b.length && crypto.timingSafeEqual(a, b)) return id;
  return null;
}

function parseCookies(header) {
  const out = {};
  if (!header) return out;
  for (const part of header.split(';')) {
    const i = part.indexOf('=');
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

// Periodic cleanup of expired sessions.
setInterval(() => {
  const now = Date.now();
  for (const [sid, s] of store) if (s.expiresAt < now) store.delete(sid);
}, 60_000).unref();

export function sessionMiddleware(req, res, next) {
  const cookies = parseCookies(req.headers.cookie);
  let sid = cookies[COOKIE_NAME] ? unsign(cookies[COOKIE_NAME]) : null;
  const now = Date.now();

  let entry = sid ? store.get(sid) : undefined;
  if (!entry || entry.expiresAt < now) {
    sid = crypto.randomUUID();
    entry = { data: { createdAt: new Date().toISOString() }, expiresAt: now + TTL_MS };
    store.set(sid, entry);
    res.setHeader(
      'Set-Cookie',
      `${COOKIE_NAME}=${encodeURIComponent(sign(sid))}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${Math.floor(TTL_MS / 1000)}`
    );
  } else {
    entry.expiresAt = now + TTL_MS; // sliding expiry
  }

  req.sessionID = sid;
  req.session = entry.data;
  next();
}
