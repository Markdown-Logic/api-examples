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

[run.mjs](run.mjs) contains the six short scenario branches; [api.mjs](api.mjs) shows OAuth, complete-request deadlines, bounded GET throttling retries with jitter, and single-attempt writes. A pending create record retains the original path/body if a create fails; reconcile before removing it. Repeated saved shares/webhook destinations are refused locally. These local files assume one process; use application transactions and unique mappings in a product.

This is **server-side JavaScript**. Never ship client credentials, long-lived access tokens or webhook signing secrets in browser bundles or localStorage. Use the [user connection guide](../docs/report-workflow.md#connect-the-right-account) to authorize a person's account through your backend.

[webhook.mjs](webhook.mjs) authenticates raw request bytes with MDL's HMAC-SHA256 contract, checks the timestamp and signed event identity, and atomically queues a complete inbox entry before acknowledgment. Duplicate IDs survive restarts. Run behind your public HTTPS ingress; the local listener must not be registered with live MDL. See [webhooks](../docs/webhooks.md) for production processing responsibilities.

```sh
python3 tests/verify.py node
```

The test suite uses synthetic localhost services only. No SDK, live tenant or provider is involved.
