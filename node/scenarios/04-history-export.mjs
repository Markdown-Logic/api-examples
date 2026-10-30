import { required } from '../state.mjs';

/** Inspect one bounded history page and explicitly export the current HTML. */
export async function run(request, state) {
  const path = state.documentPath();
  const page = await request('GET', `${path}/versions?limit=20&offset=0`);
  if (!Array.isArray(page.items) || typeof page.hasMore !== 'boolean') {
    throw new Error('Malformed history page; export stopped.');
  }
  if (page.items.length) {
    const versionId = encodeURIComponent(required(page.items[0]?.id, 'valid history snapshot ID'));
    await request('GET', `${path}/versions/${versionId}`);
  }

  // Keep bytes intact: this endpoint returns HTML rather than a JSON envelope.
  const html = await request('GET', `${path}/renders/html`, undefined, true);
  await state.save('report.html', html);
  return {
    scenario: '04',
    versions: page.items.length,
    hasMore: page.hasMore,
    exportFile: state.outputPath('report.html'),
  };
}
