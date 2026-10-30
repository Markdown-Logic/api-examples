import { connect } from './api.mjs';
import { openState, prepareDirectory } from './state.mjs';
import { receive } from './webhook.mjs';
import { run as project } from './scenarios/01-project.mjs';
import { run as storeReport } from './scenarios/02-store-report.mjs';
import { run as updateReport } from './scenarios/03-update-report.mjs';
import { run as historyExport } from './scenarios/04-history-export.mjs';
import { run as shareReport } from './scenarios/05-share-report.mjs';
import { run as registerWebhook } from './scenarios/06-register-webhook.mjs';

const scenarios = {
  '01': project,
  '02': storeReport,
  '03': updateReport,
  '04': historyExport,
  '05': shareReport,
  '06': registerWebhook,
};

async function main() {
  const scenario = process.argv[2];
  if (scenario !== 'webhook' && !Object.hasOwn(scenarios, scenario)) {
    throw new Error('Use 01..06 or webhook; run from repository root.');
  }

  if (scenario === 'webhook') {
    return receive(await prepareDirectory());
  }
  const state = await openState();
  if (scenario === '01' && state.mapping.projectId) {
    throw new Error('Project already mapped. Reuse its stable ID.');
  }
  if (scenario === '02' && state.mapping.documentId) {
    throw new Error('Report already mapped. Use 03 to update.');
  }

  const request = await connect();
  return scenarios[scenario](request, state, process.env);
}

/** Print actionable errors without leaking response bodies or file exceptions. */
function reportError(error) {
  let message = error.message;
  if (error.code === 'EEXIST') {
    message = 'A pending create exists. Reconcile server state before clearing the marker.';
  } else if (error.code && !error.status) {
    message = 'Local file operation failed. Keep files and review pending operations.';
  }
  console.error(JSON.stringify({
    status: error.status,
    code: error.code,
    reason: error.reason,
    requestId: error.requestId,
    message,
  }));
  process.exitCode = 1;
}

main().then(result => {
  if (result) {
    console.log(JSON.stringify(result));
  }
}).catch(reportError);
