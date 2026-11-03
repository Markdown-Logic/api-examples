import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { connect } from './api.mjs';

/** Read one authorized project page before choosing any write scenario. */
export async function readProjects(request, teamId) {
  if (typeof teamId !== 'string' || !teamId.trim()) throw new Error('Set MDLOGIC_TEAM to your authorized team ID.');
  const page = await request('GET', `/api/v1/teams/${encodeURIComponent(teamId)}/projects?limit=50&offset=0`);
  if (!Array.isArray(page?.items) || typeof page.hasMore !== 'boolean' ||
      page.items.some(project => typeof project?.id !== 'string' || !project.id.trim())) {
    throw new Error('Malformed project page; stop before choosing a project.');
  }
  return { teamId, projectIds: page.items.map(project => project.id), hasMore: page.hasMore };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (!process.env.MDLOGIC_TEAM?.trim()) throw new Error('Set MDLOGIC_TEAM to your authorized team ID.');
    // This example needs projects:read only; report scenarios retain their defaults.
    const request = await connect(process.env, { scope: 'projects:read' });
    console.log(JSON.stringify(await readProjects(request, process.env.MDLOGIC_TEAM)));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
