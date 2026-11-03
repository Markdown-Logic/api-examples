import { readInput, required } from '../state.mjs';

/** Read the live revision and use it as the precondition for one update. */
export async function run(request, state, env) {
  const content = await readInput(env.MDLOGIC_INPUT || 'fixtures/report-updated.md');
  // docs:begin guarded-update
  const path = state.documentPath();
  const { document } = await request('GET', path);

  // In an application, review or merge the read content before replacing it.
  // A conflict must return to that decision; never fetch a new revision and loop.
  const result = await request('PUT', path, {
    content,
    expectedRevision: required(document?.revision, 'live revision'),
    changeNote: 'Refresh generated report',
  });
  state.mapping.revision = required(result.document?.revision, 'updated revision');
  // docs:end guarded-update
  await state.saveMapping();
  return { scenario: '03', documentId: state.mapping.documentId, decision: result.decision };
}
