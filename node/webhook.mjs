import { createHmac, createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdir, open, chmod, link, unlink } from 'node:fs/promises';
import { join } from 'node:path';

export function verifySignature(header, raw, secret, now = Math.floor(Date.now() / 1000)) {
  const fields = String(header || '').split(',').map(v => v.trim());
  const timestamp = fields.find(v => v.startsWith('t='))?.slice(2);
  if (!/^\d+$/.test(timestamp || '')) return false;
  const t = Number(timestamp);
  if (!Number.isSafeInteger(t) || t <= 0 || Math.abs(now - t) > 300) return false;
  const expected = createHmac('sha256', secret).update(`${t}.`).update(raw).digest();
  return fields.filter(v => /^v1=[0-9a-f]{64}$/.test(v)).some(v => timingSafeEqual(Buffer.from(v.slice(3), 'hex'), expected));
}

export async function receive(directory) {
  const secret = process.env.MDLOGIC_WEBHOOK_SECRET;
  if (!secret) throw new Error('Set MDLOGIC_WEBHOOK_SECRET from the once-only registration response.');
  const bind = process.env.MDLOGIC_WEBHOOK_BIND || '127.0.0.1';
  if (!['127.0.0.1','0.0.0.0'].includes(bind)) throw new Error('Invalid webhook bind address.');
  const inbox = join(directory, 'inbox');
  await mkdir(inbox, { recursive: true, mode: 0o700 }); await chmod(inbox, 0o700);
  const server = createServer(async (req, res) => {
    const reply = status => { res.writeHead(status); res.end(); };
    if (req.method !== 'POST' || req.url !== '/webhook') return reply(404);
    try {
      let size = 0; const chunks = [];
      for await (const chunk of req) { size += chunk.length; if (size > 1024 * 1024) return reply(413); chunks.push(chunk); }
      const raw = Buffer.concat(chunks);
      if (!verifySignature(req.headers['mdl-signature'], raw, secret)) return reply(401);
      let event; try { event = JSON.parse(raw); } catch { return reply(400); }
      if (typeof event?.id !== 'string' || !event.id || event.id !== req.headers['mdl-event-id'] ||
          typeof event.type !== 'string' || !event.type || (req.headers['mdl-event-type'] && req.headers['mdl-event-type'] !== event.type)) return reply(400);
      // This file IS the accepted work item. Production: use a transactional inbox + worker.
      const name = createHash('sha256').update(event.id).digest('hex') + '.json';
      const temporary = join(inbox, `.${randomUUID()}.tmp`);
      const file = await open(temporary, 'wx', 0o600);
      try {
        try { await file.writeFile(raw); await file.sync(); } finally { await file.close(); }
        // Atomic no-replace publication: duplicates only see complete inbox entries.
        try { await link(temporary, join(inbox, name)); }
        catch (error) { if (error.code === 'EEXIST') return reply(200); throw error; }
        reply(202);
      } finally { await unlink(temporary); }
    } catch { reply(500); }
  });
  server.requestTimeout = 15_000; server.headersTimeout = 15_000;
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(Number(process.env.PORT || 8080), bind, resolve); });
  console.log(JSON.stringify({ receiver: 'ready', port: server.address().port }));
}
