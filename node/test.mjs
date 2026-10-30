import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { openState } from './state.mjs';
import { verifySignature } from './webhook.mjs';
import { run as exportReport } from './scenarios/04-history-export.mjs';
import { run as registerWebhook } from './scenarios/06-register-webhook.mjs';

test('local mappings must be JSON objects', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'report-mapping-'));
  try {
    for (const value of [null, [], 'invalid']) {
      await writeFile(join(directory, 'state.json'), JSON.stringify(value));
      await assert.rejects(
        openState({ MDLOGIC_STATE_DIR: directory }),
        /State file is invalid/,
      );
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('history stops before requesting a malformed snapshot ID', async () => {
  const calls = [];
  const request = async (method, path) => {
    calls.push([method, path]);
    return { items: [{ id: 42 }], hasMore: false };
  };
  const state = { documentPath: () => '/documents/document-1' };

  await assert.rejects(exportReport(request, state), /valid history snapshot ID/);
  assert.deepEqual(calls, [['GET', '/documents/document-1/versions?limit=20&offset=0']]);
});

test('webhook registration requires an event catalogue array', async () => {
  const calls = [];
  const request = async (method, path) => {
    calls.push([method, path]);
    return { events: 'document.created' };
  };
  const state = { refuseExisting: async () => {} };
  const env = { MDLOGIC_WEBHOOK_URL: 'https://receiver.example/webhook' };

  await assert.rejects(registerWebhook(request, state, env), /does not publish/);
  assert.deepEqual(calls, [['GET', '/api/v1/webhooks/events']]);
});


test('webhook signatures cover timestamp header text without normalization', () => {
  const now = 1_800_000_000;
  const timestamp = `00${now}`;
  const raw = Buffer.from('{"id":"event-1","type":"document.updated"}');
  const secret = 'whsec_synthetic_only';
  const sign = value => createHmac('sha256', secret)
    .update(`${value}.`)
    .update(raw)
    .digest('hex');

  assert.equal(verifySignature(`t=${timestamp},v1=${sign(timestamp)}`, raw, secret, now), true);
  assert.equal(verifySignature(`t=${timestamp},v1=${sign(now)}`, raw, secret, now), false);
});
