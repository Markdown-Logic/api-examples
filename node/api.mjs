import { randomInt } from 'node:crypto';
import { setTimeout as sleep } from 'node:timers/promises';

export function origin(value) {
  const u = new URL(value);
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname);
  if ((u.protocol !== 'https:' && !(u.protocol === 'http:' && loopback)) ||
      u.username || u.password || u.search || u.hash || u.pathname !== '/') {
    throw new Error('Use a canonical HTTPS origin; HTTP is allowed only on loopback.');
  }
  return u.origin;
}
const safe = value => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(value) ? value : undefined;

export class ApiError extends Error {
  constructor(status, body, requestId) {
    const guidance = status === 401 ? 'Authentication refused. Reconnect or replace a revoked credential; do not retry blindly.'
      : status === 423 ? 'Content is temporarily read-only. Keep the generated input; wait for conversion, read and review current state, then deliberately retry.'
      : status === 409 ? 'Conflict. Keep input and compare current content; do not refresh a revision and overwrite automatically.'
      : status === 429 ? 'Rate limited. Pause; mutations are not automatically retried.'
      : 'Request refused. Review permissions, plan and configuration.';
    super(guidance);
    this.status = status;
    this.code = safe(body?.code);
    this.reason = safe(body?.details?.reason);
    this.requestId = safe(requestId) ?? safe(body?.requestId);
  }
}

// Three GET attempts at most. Retry-After is a minimum; larger waits stop this demo.
export function retryDelay(header, attempt, now = Date.now()) {
  let wait;
  if (header && /^\d+$/.test(header.trim())) wait = Number(header.trim()) * 1000;
  else if (header && Number.isFinite(Date.parse(header))) wait = Math.max(0, Date.parse(header) - now);
  else wait = 1000 * 2 ** attempt;
  if (!Number.isFinite(wait) || wait > 5000) return null;
  return Math.min(5000, wait + randomInt(0, 101));
}

async function send(url, init) {
  // The deadline remains active while the response body is consumed.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(url, { ...init, redirect: 'manual', signal: controller.signal });
    const bytes = Buffer.from(await response.arrayBuffer());
    return { response, bytes };
  } catch {
    throw new Error(init.method === 'GET'
      ? 'Network request failed or timed out. Read failed; retry deliberately.'
      : 'Write response unavailable or timed out; outcome uncertain. Keep input and reconcile current state before another mutation.');
  } finally { clearTimeout(timer); }
}

export async function connect(env = process.env) {
  const base = origin(env.MDLOGIC_API_ORIGIN || 'https://api.markdownlogic.com');
  let token = env.MDLOGIC_TOKEN;
  if (!token) {
    if (!env.MDLOGIC_CLIENT_ID || !env.MDLOGIC_CLIENT_SECRET) throw new Error('Set MDLOGIC_TOKEN or server-side client credentials.');
    const issuer = origin(env.MDLOGIC_OAUTH_ISSUER || 'https://auth.markdownlogic.com');
    const form = new URLSearchParams({ grant_type: 'client_credentials', client_id: env.MDLOGIC_CLIENT_ID,
      client_secret: env.MDLOGIC_CLIENT_SECRET, scope: 'projects:read documents:read documents:write' });
    const { response, bytes } = await send(`${issuer}/oauth/token`, { method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' }, body: form });
    let body = {}; try { body = JSON.parse(bytes); } catch { /* sanitized below */ }
    if (!response.ok || typeof body.access_token !== 'string') throw new Error('Token exchange refused. Check the credential and granted scopes; reconnect if revoked.');
    token = body.access_token;
  }
  return async function request(method, path, body, binary = false) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const { response, bytes } = await send(base + path, { method,
        headers: { authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      let data = {}; if (!binary || !response.ok) { try { data = JSON.parse(bytes); } catch { /* untrusted text omitted */ } }
      if (response.ok) return binary ? bytes : data;
      const error = new ApiError(response.status, data, response.headers.get('x-request-id'));
      if (method !== 'GET' || response.status !== 429 || attempt === 2) throw error;
      const delay = retryDelay(response.headers.get('retry-after'), attempt);
      if (delay === null) throw error;
      await sleep(delay);
    }
  };
}
