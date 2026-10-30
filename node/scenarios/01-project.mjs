import { required } from '../state.mjs';

/** Create a project once, save its stable ID, then list and rename it. */
export async function run(request, state) {
  const path = `${state.teamPath()}/projects`;
  const body = { name: 'Report integration example', mode: 'document' };
  await state.beginCreate('01', path, body);
  const { project } = await request('POST', path, body);

  state.mapping.projectId = required(project?.id, 'valid project response');
  // Save the mapping before subsequent requests: their failure must not lose it.
  await state.saveMapping();
  await state.finishCreate('01');

  const page = await request('GET', `${path}?limit=50&offset=0`);
  await request('PATCH', state.projectPath(), { name: 'Report integration example' });
  return {
    scenario: '01',
    projectId: state.mapping.projectId,
    listed: page.items.length,
    hasMore: page.hasMore,
  };
}
