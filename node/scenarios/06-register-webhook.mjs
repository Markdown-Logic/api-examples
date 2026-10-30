import { required } from '../state.mjs';

/** Register an authorized HTTPS destination for this report's lifecycle events. */
export async function run(request, state, env) {
  await state.refuseExisting('webhook.json');
  const url = new URL(required(env.MDLOGIC_WEBHOOK_URL, 'MDLOGIC_WEBHOOK_URL'));
  if (url.protocol !== 'https:' || url.username || url.password) {
    throw new Error('Use a public HTTPS webhook receiver URL.');
  }

  const events = [
    'document.created', 'document.updated', 'project.created',
    'project.updated', 'share.created',
  ];
  const catalogue = await request('GET', '/api/v1/webhooks/events');
  if (!Array.isArray(catalogue?.events) ||
      !events.every(event => catalogue.events.includes(event))) {
    throw new Error('This deployment does not publish all requested events.');
  }

  const path = `${state.teamPath()}/webhooks`;
  const body = { url: url.href, events, description: 'Generated report lifecycle' };
  await state.beginCreate('06', path, body);
  const result = await request('POST', path, body);

  // The signing secret is shown once; retain it privately before validating.
  await state.save('webhook.json', result);
  required(result.secret, 'valid signing secret; retain response and reconcile');
  const webhookId = required(result.webhook?.id, 'valid webhook ID; retain response and reconcile');
  await state.finishCreate('06');
  return { scenario: '06', webhookId, secretFile: state.outputPath('webhook.json') };
}
