import { access, chmod, mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { connect, origin } from './api.mjs';
import { receive } from './webhook.mjs';

const env = process.env;
const directory = env.MDLOGIC_STATE_DIR || '.local/node';
const enc = encodeURIComponent;
async function save(name, value, exclusive = false) {
  const data = Buffer.isBuffer(value) ? value : JSON.stringify(value, null, 2) + '\n';
  if (exclusive) return writeFile(join(directory, name), data, { mode: 0o600, flag: 'wx' });
  const temporary = join(directory, name + '.tmp');
  await writeFile(temporary, data, { mode: 0o600 });
  await chmod(temporary, 0o600);
  await rename(temporary, join(directory, name));
}
async function refuseExisting(name) {
  try { await access(join(directory, name)); } catch (error) { if (error.code === 'ENOENT') return; throw error; }
  throw new Error('A saved result already exists. Review it before requesting another link or destination.');
}
async function load() {
  try { return JSON.parse(await readFile(join(directory, 'state.json'), 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return {}; throw new Error('State file is invalid; review it before continuing.'); }
}
async function input(path) {
  try { return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(await readFile(path)); }
  catch { throw new Error('Input must be readable UTF-8 text; no mutation was sent.'); }
}
function required(value, name) { if (typeof value !== 'string' || !value) throw new Error(`Set or create ${name} first.`); return value; }
async function main() {
  const scenario = process.argv[2];
  await mkdir(directory, { recursive: true, mode: 0o700 }); await chmod(directory, 0o700);
  if (scenario === 'webhook') return receive(directory);
  if (!['01','02','03','04','05','06'].includes(scenario)) throw new Error('Use 01..06 or webhook; run from repository root.');
  const state = await load();
  if (scenario === '01' && state.projectId) throw new Error('Project already mapped. Reuse its stable ID.');
  if (scenario === '02' && state.documentId) throw new Error('Report already mapped. Use 03 to update.');
  const request = await connect();
  const team = () => enc(required(env.MDLOGIC_TEAM, 'MDLOGIC_TEAM'));
  const project = () => `/api/v1/projects/${enc(required(state.projectId, 'projectId (01)'))}`;
  const doc = () => `${project()}/documents/${enc(required(state.documentId, 'documentId (02)'))}`;
  if (scenario === '01') {
    const body = { name: 'Report integration example', mode: 'document' };
    await save('pending-01.json', { apiOrigin: origin(env.MDLOGIC_API_ORIGIN || 'https://api.markdownlogic.com'), method: 'POST', path: `/api/v1/teams/${team()}/projects`, body }, true);
    const { project: created } = await request('POST', `/api/v1/teams/${team()}/projects`, body);
    state.projectId = required(created?.id, 'valid project response'); await save('state.json', state);
    await unlink(join(directory, 'pending-01.json'));
    const page = await request('GET', `/api/v1/teams/${team()}/projects?limit=50&offset=0`);
    await request('PATCH', project(), { name: 'Report integration example' });
    return { scenario, projectId: state.projectId, listed: page.items.length, hasMore: page.hasMore };
  }
  if (scenario === '02') {
    const body = { name: 'report.md', content: await input(env.MDLOGIC_INPUT || 'fixtures/report.md'), format: 'markdown', ifNotExists: true };
    await save('pending-02.json', { apiOrigin: origin(env.MDLOGIC_API_ORIGIN || 'https://api.markdownlogic.com'), method: 'POST', path: `${project()}/artifacts`, body }, true);
    const result = await request('POST', `${project()}/artifacts`, body);
    state.documentId = required(result.artifact?.id, 'valid document ID'); state.revision = required(result.artifact?.revision, 'valid revision');
    await save('state.json', state); await unlink(join(directory, 'pending-02.json'));
    return { scenario, documentId: state.documentId, decision: result.decision };
  }
  if (scenario === '03') {
    const content = await input(env.MDLOGIC_INPUT || 'fixtures/report-updated.md');
    const { document: current } = await request('GET', doc());
    // In an application, review/merge the read content before authorizing replacement.
    const result = await request('PUT', doc(), { content, expectedRevision: required(current?.revision, 'live revision'), changeNote: 'Refresh generated report' });
    state.revision = required(result.document?.revision, 'updated revision'); await save('state.json', state);
    return { scenario, documentId: state.documentId, decision: result.decision };
  }
  if (scenario === '04') {
    const page = await request('GET', `${doc()}/versions?limit=20&offset=0`);
    if (!Array.isArray(page.items) || typeof page.hasMore !== 'boolean') throw new Error('Malformed history page; export stopped.');
    if (page.items.length) await request('GET', `${doc()}/versions/${enc(page.items[0].id)}`);
    await save('report.html', await request('GET', `${doc()}/renders/html`, undefined, true));
    return { scenario, versions: page.items.length, hasMore: page.hasMore, exportFile: join(directory, 'report.html') };
  }
  if (scenario === '05') {
    await refuseExisting('share.json');
    const path = `${doc()}/shares`, body = { expiresInDays: 30 };
    await save('pending-05.json', { apiOrigin: origin(env.MDLOGIC_API_ORIGIN || 'https://api.markdownlogic.com'), method: 'POST', path, body }, true);
    const result = await request('POST', path, body);
    await save('share.json', result);
    required(result.share?.url, 'valid share URL; retain response and reconcile');
    const id = required(result.share?.id, 'valid share ID; retain response and reconcile');
    await unlink(join(directory, 'pending-05.json'));
    return { scenario, shareId: id, shareFile: join(directory, 'share.json') };
  }
  if (scenario === '06') {
    await refuseExisting('webhook.json');
    const url = new URL(required(env.MDLOGIC_WEBHOOK_URL, 'MDLOGIC_WEBHOOK_URL'));
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Use a public HTTPS webhook receiver URL.');
    const events = ['document.created','document.updated','project.created','project.updated','share.created'];
    const catalogue = await request('GET', '/api/v1/webhooks/events');
    if (!events.every(event => catalogue.events.includes(event))) throw new Error('This deployment does not publish all requested events.');
    const path = `/api/v1/teams/${team()}/webhooks`, body = { url: url.href, events, description: 'Generated report lifecycle' };
    await save('pending-06.json', { apiOrigin: origin(env.MDLOGIC_API_ORIGIN || 'https://api.markdownlogic.com'), method: 'POST', path, body }, true);
    const result = await request('POST', path, body);
    await save('webhook.json', result);
    required(result.secret, 'valid signing secret; retain response and reconcile');
    const id = required(result.webhook?.id, 'valid webhook ID; retain response and reconcile');
    await unlink(join(directory, 'pending-06.json'));
    return { scenario, webhookId: id, secretFile: join(directory, 'webhook.json') };
  }
}
main().then(result => { if (result) console.log(JSON.stringify(result)); }).catch(error => {
  console.error(JSON.stringify({ status: error.status, code: error.code, reason: error.reason, requestId: error.requestId,
    message: error.code === 'EEXIST' ? 'A pending create exists. Reconcile server state before clearing the marker.' : error.code && !error.status ? 'Local file operation failed. Keep files and review pending operations.' : error.message }));
  process.exitCode = 1;
});
