import { randomInt } from 'node:crypto';
import { setTimeout as sleep } from 'node:timers/promises';

/** Accept only an origin so credentials cannot be sent through a configured path. */
export function origin(value) {
  const url = new URL(value);
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  const secure = url.protocol === 'https:';
  const localHttp = url.protocol === 'http:' && loopback;
  if ((!secure && !localHttp) || url.username || url.password ||
      url.search || url.hash || url.pathname !== '/') {
    throw new Error('Use a canonical HTTPS origin; HTTP is allowed only on loopback.');
  }
  return url.origin;
}

function safeMetadata(value) {
  return typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(value)
    ? value
    : undefined;
}

function guidance(status) {
  switch (status) {
    case 401:
      return 'Authentication refused. Reconnect or replace a revoked credential; do not retry blindly.';
    case 423:
      return 'Content is temporarily read-only. Keep the generated input; wait for conversion, read and review current state, then deliberately retry.';
    case 409:
      return 'Conflict. Keep input and compare current content; do not refresh a revision and overwrite automatically.';
    case 429:
      return 'Rate limited. Pause; mutations are not automatically retried.';
    default:
      return 'Request refused. Review permissions, plan and configuration.';
  }
}

/** Expose a small allowlist of metadata rather than arbitrary server error text. */
export class ApiError extends Error {
  constructor(status, body, requestId) {
    super(guidance(status));
    this.status = status;
    this.code = safeMetadata(body?.code);
    this.reason = safeMetadata(body?.details?.reason);
    this.requestId = safeMetadata(requestId) ?? safeMetadata(body?.requestId);
  }
}

/**
 * Retry-After is a minimum. Return null when it exceeds this example's budget,
 * rather than shortening the server's requested delay. Jitter stays within 5s.
 */
export function retryDelay(header, attempt, now = Date.now()) {
  let wait;
  if (header && /^\d+$/.test(header.trim())) {
    wait = Number(header.trim()) * 1000;
  } else if (header && Number.isFinite(Date.parse(header))) {
    wait = Math.max(0, Date.parse(header) - now);
  } else {
    wait = 1000 * 2 ** attempt;
  }
  if (!Number.isFinite(wait) || wait > 5000) {
    return null;
  }
  return Math.min(5000, wait + randomInt(0, 101));
}

/** Bound the entire request, including reading a response that stalls mid-body. */
async function send(url, init) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    // Redirects are refused: the destination is not part of our trusted origin.
    const response = await fetch(url, {
      ...init,
      redirect: 'manual',
      signal: controller.signal,
    });
    const bytes = Buffer.from(await response.arrayBuffer());
    return { response, bytes };
  } catch {
    throw new Error(init.method === 'GET'
      ? 'Network request failed or timed out. Read failed; retry deliberately.'
      : 'Write response unavailable or timed out; outcome uncertain. Keep input and reconcile current state before another mutation.');
  } finally {
    clearTimeout(timer);
  }
}

function parseJson(bytes) {
  try {
    return JSON.parse(bytes);
  } catch {
    // HTML/proxy errors and other untrusted text must not enter logs.
    return {};
  }
}

/**
 * Configure one server-side connection. This illustrates client credentials for
 * the application's own account; a person's connection uses the documented
 * authorization flow and supplies its access token through MDLOGIC_TOKEN.
 */
export async function connect(env = process.env, { scope = 'projects:read documents:read documents:write' } = {}) {
  const base = origin(env.MDLOGIC_API_ORIGIN || 'https://api.markdownlogic.com');
  let token = env.MDLOGIC_TOKEN;
  if (!token) {
    if (!env.MDLOGIC_CLIENT_ID || !env.MDLOGIC_CLIENT_SECRET) {
      throw new Error('Set MDLOGIC_TOKEN or server-side client credentials.');
    }
    const issuer = origin(env.MDLOGIC_OAUTH_ISSUER || 'https://auth.markdownlogic.com');
    const form = new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: env.MDLOGIC_CLIENT_ID,
      client_secret: env.MDLOGIC_CLIENT_SECRET,
      scope,
    });
    const { response, bytes } = await send(`${issuer}/oauth/token`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: form,
    });
    const body = parseJson(bytes);
    if (!response.ok || typeof body.access_token !== 'string') {
      throw new Error('Token exchange refused. Check the credential and granted scopes; reconnect if revoked.');
    }
    token = body.access_token;
  }

  /** GET throttling has three attempts; every mutation has exactly one. */
  return async function request(method, path, body, binary = false) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const headers = { authorization: `Bearer ${token}` };
      const init = { method, headers };
      if (body !== undefined) {
        headers['content-type'] = 'application/json';
        init.body = JSON.stringify(body);
      }
      const { response, bytes } = await send(base + path, init);
      const data = !binary || !response.ok ? parseJson(bytes) : {};
      if (response.ok) {
        return binary ? bytes : data;
      }

      const error = new ApiError(response.status, data, response.headers.get('x-request-id'));
      if (method !== 'GET' || response.status !== 429 || attempt === 2) {
        throw error;
      }
      const delay = retryDelay(response.headers.get('retry-after'), attempt);
      if (delay === null) {
        throw error;
      }
      await sleep(delay);
    }
  };
}
