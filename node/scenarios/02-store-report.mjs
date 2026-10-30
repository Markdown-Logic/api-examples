import { readInput, required } from '../state.mjs';

/** Store generated Markdown without replacing an existing logical document. */
export async function run(request, state, env) {
  const body = {
    name: 'report.md',
    content: await readInput(env.MDLOGIC_INPUT || 'fixtures/report.md'),
    format: 'markdown',
    ifNotExists: true,
  };
  const path = `${state.projectPath()}/artifacts`;
  await state.beginCreate('02', path, body);
  const result = await request('POST', path, body);

  state.mapping.documentId = required(result.artifact?.id, 'valid document ID');
  state.mapping.revision = required(result.artifact?.revision, 'valid revision');
  await state.saveMapping();
  await state.finishCreate('02');
  return { scenario: '02', documentId: state.mapping.documentId, decision: result.decision };
}
