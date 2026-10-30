import { createHmac, createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdir, open, chmod, link, unlink } from 'node:fs/promises';
import { join } from 'node:path';

/**
 * Verify the original bytes before parsing JSON. MDL signs timestamp + '.' + body.
 * Any matching v1 signature is accepted to allow signing-key rotation.
 */
export function verifySignature(header, raw, secret, now = Math.floor(Date.now() / 1000)) {
  const fields = String(header || '').split(',').map(value => value.trim());
  const timestamp = fields.find(value => value.startsWith('t='))?.slice(2);
  if (!/^\d+$/.test(timestamp || '')) {
    return false;
  }
  const seconds = Number(timestamp);
  if (!Number.isSafeInteger(seconds) || seconds <= 0 || Math.abs(now - seconds) > 300) {
    return false;
  }

  // Freshness uses numeric seconds; the signature covers the exact header text.
  const expected = createHmac('sha256', secret).update(`${timestamp}.`).update(raw).digest();
  return fields.filter(value => /^v1=[0-9a-f]{64}$/.test(value)).some(value => {
    const signature = Buffer.from(value.slice(3), 'hex');
    return timingSafeEqual(signature, expected);
  });
}

/** Queue complete bytes once per signed event ID, including across restarts. */
async function enqueue(inbox, eventId, raw) {
  const name = createHash('sha256').update(eventId).digest('hex') + '.json';
  const temporary = join(inbox, `.${randomUUID()}.tmp`);
  const file = await open(temporary, 'wx', 0o600);
  try {
    try {
      await file.writeFile(raw);
      await file.sync();
    } finally {
      await file.close();
    }

    // A hard link publishes a complete entry without replacing an existing one.
    // The inbox file is the work item; production needs a transactional worker.
    try {
      await link(temporary, join(inbox, name));
      return true;
    } catch (error) {
      if (error.code === 'EEXIST') {
        return false;
      }
      throw error;
    }
  } finally {
    await unlink(temporary);
  }
}

function validEvent(event, headers) {
  return typeof event?.id === 'string' && event.id && event.id === headers['mdl-event-id'] &&
    typeof event.type === 'string' && event.type &&
    (!headers['mdl-event-type'] || headers['mdl-event-type'] === event.type);
}

/** Start a local listener; public HTTPS termination belongs to your ingress. */
export async function receive(directory) {
  const secret = process.env.MDLOGIC_WEBHOOK_SECRET;
  if (!secret) {
    throw new Error('Set MDLOGIC_WEBHOOK_SECRET from the once-only registration response.');
  }
  const bind = process.env.MDLOGIC_WEBHOOK_BIND || '127.0.0.1';
  if (!['127.0.0.1', '0.0.0.0'].includes(bind)) {
    throw new Error('Invalid webhook bind address.');
  }
  const inbox = join(directory, 'inbox');
  await mkdir(inbox, { recursive: true, mode: 0o700 });
  await chmod(inbox, 0o700);

  const server = createServer(async (req, res) => {
    function reply(status) {
      res.writeHead(status);
      res.end();
    }
    if (req.method !== 'POST' || req.url !== '/webhook') {
      return reply(404);
    }
    try {
      let size = 0;
      const chunks = [];
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 1024 * 1024) {
          return reply(413);
        }
        chunks.push(chunk);
      }
      const raw = Buffer.concat(chunks);
      if (!verifySignature(req.headers['mdl-signature'], raw, secret)) {
        return reply(401);
      }

      let event;
      try {
        event = JSON.parse(raw);
      } catch {
        return reply(400);
      }
      if (!validEvent(event, req.headers)) {
        return reply(400);
      }

      const accepted = await enqueue(inbox, event.id, raw);
      reply(accepted ? 202 : 200);
    } catch {
      // Returning failure allows delivery retries without exposing secret inputs.
      reply(500);
    }
  });
  server.requestTimeout = 15_000;
  server.headersTimeout = 15_000;
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(Number(process.env.PORT || 8080), bind, resolve);
  });
  console.log(JSON.stringify({ receiver: 'ready', port: server.address().port }));
}
