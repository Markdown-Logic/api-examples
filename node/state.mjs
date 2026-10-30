import { access, chmod, mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { origin } from './api.mjs';

/** Validate IDs and revisions before they become paths or saved mappings. */
export function required(value, name) {
  if (typeof value !== 'string' || !value) {
    throw new Error(`Set or create ${name} first.`);
  }
  return value;
}

/** Read source without newline conversion or replacement of invalid UTF-8. */
export async function readInput(path) {
  try {
    const bytes = await readFile(path);
    return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new Error('Input must be readable UTF-8 text; no mutation was sent.');
  }
}

/** Create a private output directory shared by scenarios and the listener. */
export async function prepareDirectory(env = process.env) {
  const directory = env.MDLOGIC_STATE_DIR || '.local/node';
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await chmod(directory, 0o700);
  return directory;
}

/** Local state for one connection. Run one scenario process at a time. */
export async function openState(env = process.env) {
  const directory = await prepareDirectory(env);
  let mapping;
  try {
    mapping = JSON.parse(await readFile(join(directory, 'state.json'), 'utf8'));
    if (!mapping || typeof mapping !== 'object' || Array.isArray(mapping)) {
      throw new Error('Expected a JSON object for the connection mapping.');
    }
  } catch (error) {
    if (error.code !== 'ENOENT') {
      throw new Error('State file is invalid; review it before continuing.');
    }
    mapping = {};
  }

  /** Replace an output atomically; exclusive intent files must never be replaced. */
  async function save(name, value, exclusive = false) {
    const data = Buffer.isBuffer(value) ? value : JSON.stringify(value, null, 2) + '\n';
    if (exclusive) {
      return writeFile(join(directory, name), data, { mode: 0o600, flag: 'wx' });
    }

    const temporary = join(directory, name + '.tmp');
    await writeFile(temporary, data, { mode: 0o600 });
    await chmod(temporary, 0o600);
    await rename(temporary, join(directory, name));
  }

  async function refuseExisting(name) {
    try {
      await access(join(directory, name));
    } catch (error) {
      if (error.code === 'ENOENT') {
        return;
      }
      throw error;
    }
    throw new Error('A saved result already exists. Review it before requesting another link or destination.');
  }

  /**
   * Record the exact target and input before a create. A timeout cannot prove
   * whether the server committed it, so only a validated result clears this file.
   * This is an application journal, not an API idempotency key.
   */
  async function beginCreate(scenario, path, body) {
    await save(`pending-${scenario}.json`, {
      apiOrigin: origin(env.MDLOGIC_API_ORIGIN || 'https://api.markdownlogic.com'),
      method: 'POST',
      path,
      body,
    }, true);
  }

  async function finishCreate(scenario) {
    await unlink(join(directory, `pending-${scenario}.json`));
  }

  function projectPath() {
    return `/api/v1/projects/${encodeURIComponent(required(mapping.projectId, 'projectId (01)'))}`;
  }

  function documentPath() {
    const documentId = encodeURIComponent(required(mapping.documentId, 'documentId (02)'));
    return `${projectPath()}/documents/${documentId}`;
  }

  function teamPath() {
    return `/api/v1/teams/${encodeURIComponent(required(env.MDLOGIC_TEAM, 'MDLOGIC_TEAM'))}`;
  }

  return {
    directory, mapping, save, refuseExisting, beginCreate, finishCreate,
    projectPath, documentPath, teamPath,
    saveMapping: () => save('state.json', mapping),
    outputPath: name => join(directory, name),
  };
}
