import { required } from '../state.mjs';

/** Create a share only when explicitly invoked; keep its private URL off stdout. */
export async function run(request, state) {
  await state.refuseExisting('share.json');
  const path = `${state.documentPath()}/shares`;
  const body = { expiresInDays: 30 };
  await state.beginCreate('05', path, body);
  const result = await request('POST', path, body);

  // Save even a malformed success response as private reconciliation evidence.
  await state.save('share.json', result);
  required(result.share?.url, 'valid share URL; retain response and reconcile');
  const shareId = required(result.share?.id, 'valid share ID; retain response and reconcile');
  await state.finishCreate('05');
  return { scenario: '05', shareId, shareFile: state.outputPath('share.json') };
}
