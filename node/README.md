# JavaScript / Node

Use Node 22 or later, with no packages to install. Run from the repository root:

```sh
node node/run.mjs 01   # Create/list/update a project
node node/run.mjs 02   # Store the synthetic generated report
node node/run.mjs 03   # Read and submit a guarded correction
node node/run.mjs 04   # Read history and explicitly export HTML
node node/run.mjs 05   # Explicitly create a 30-day share
node node/run.mjs 06   # Owner/admin webhook setup, using authorized setup token
node node/run.mjs webhook
```

Configure the common [environment variables](../README.md#configure-once). State and private output default to `.local/node/`; override `MDLOGIC_STATE_DIR` for another isolated connection. `MDLOGIC_INPUT` selects your generated UTF-8 source. These programs never alter it. `state.json` records stable IDs/revision; `share.json` contains a private URL, and `webhook.json` contains the once-only signing secret. The code prints IDs/paths and safe error metadata.

Start with the task you want to learn. Each scenario exports one `run(request, state, env)` function. `request` comes from the common HTTP helper, `state` holds the local connection mapping, and `env` supplies configuration. The small [dispatcher](run.mjs) selects a scenario and prints its result.

| Task | Source |
| --- | --- |
| 01: Create, list and update a project | [01-project.mjs](scenarios/01-project.mjs) |
| 02: Store a generated report | [02-store-report.mjs](scenarios/02-store-report.mjs) |
| 03: Update with a revision precondition | [03-update-report.mjs](scenarios/03-update-report.mjs) |
| 04: Inspect history and export HTML | [04-history-export.mjs](scenarios/04-history-export.mjs) |
| 05: Create a 30-day share | [05-share-report.mjs](scenarios/05-share-report.mjs) |
| 06: Register a webhook destination | [06-register-webhook.mjs](scenarios/06-register-webhook.mjs) |

[api.mjs](api.mjs) explains OAuth, complete-request deadlines, bounded GET throttling retries with jitter, and single-attempt writes. [state.mjs](state.mjs) keeps private files, stable mappings and create journals together. Read those helpers after following a scenario's request and response flow. A pending create record retains the original path/body if a create fails; reconcile before removing it. Repeated saved shares/webhook destinations are refused locally. These local files assume one process; use application transactions and unique mappings in a product.

This is **server-side JavaScript**. Never ship client credentials, long-lived access tokens or webhook signing secrets in browser bundles or localStorage. Use the [user connection guide](../docs/report-workflow.md#connect-the-right-account) to authorize a person's account through your backend.

[webhook.mjs](webhook.mjs) authenticates raw request bytes with MDL's HMAC-SHA256 contract, checks the timestamp and signed event identity, and atomically queues a complete inbox entry before acknowledgment. Duplicate IDs survive restarts. Run behind your public HTTPS ingress; the local listener must not be registered with live MDL. See [webhooks](../docs/webhooks.md) for production processing responsibilities.

```sh
node --test node/test.mjs
python3 tests/verify.py node
```

The Node unit tests check malformed local mappings and response fields. The shared contract suite uses synthetic localhost services only. No SDK, live tenant or provider is involved.
