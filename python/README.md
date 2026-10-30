# Python report integration

Use Python **3.11 or later**. All HTTP, JSON, cryptography and receiver code uses the standard library; there are no packages to install. Run from the repository root:

```sh
python3 python/run.py 01   # Create/list/update a project
python3 python/run.py 02   # Store the generated report once
python3 python/run.py 03   # Read the live revision and submit a guarded correction
python3 python/run.py 04   # Read one history page/snapshot and explicitly export HTML
python3 python/run.py 05   # Explicitly create a 30-day share
python3 python/run.py 06   # Authorized owner/admin webhook setup
python3 python/run.py webhook
```

Set the common [environment variables](../README.md#configure-once). Prefer a short-lived `MDLOGIC_TOKEN` from your server's authorized user connection. For your own account's automation, alternatively inject `MDLOGIC_CLIENT_ID` and `MDLOGIC_CLIENT_SECRET`; the program exchanges them once and holds the token in memory. Never place credentials in a browser bundle, committed file or shell history. [Connecting an individual user's account](../docs/report-workflow.md#connect-the-right-account) requires the actual supported authorization flow through your backend.

[run.py](run.py) contains the six scenario branches. Local state defaults to `.local/python/`; override `MDLOGIC_STATE_DIR` for another isolated user/run. Files have private permissions on POSIX systems; configure user-only ACLs on Windows. `state.json` stores stable IDs and the last successful revision. `share.json` contains a private access URL; `webhook.json` contains the once-only signing secret. The program prints IDs/paths rather than those secrets.

Before 01, 02, 05 or 06 sends a create, a private `pending-<number>.json` captures the original origin, path and exact payload. Failure or an unknown response keeps it and blocks another create. A malformed share/webhook success response is retained privately and does not clear the marker. Reconcile the original operation before retrying. These small local files assume one process; production needs transactional unique mappings and job coordination.

Set `MDLOGIC_INPUT` to your generated UTF-8 source for 02/03. Invalid UTF-8 is rejected before mutation, and the program never edits or deletes the input. Scenario 03 deliberately replaces the synthetic fixture; a real application must compare/review current content before approving a full-source replacement. The opaque `revision` guard must never be silently refreshed after a conflict.

[api.py](api.py) shows bounded HTTP attempts, a 15-second complete-request deadline, safe request-ID errors and GET-only 429 retries. It honors numeric or HTTP-date Retry-After with small jitter, permits at most three total attempts and stops if the requested wait exceeds five seconds. Writes, token exchanges, redirects, network failures, 401, 409 and 423 never automatically replay. The deadline helper uses one daemon worker per attempt so DNS or a slow body cannot hold the command indefinitely; cancellation prevents a late connection from starting a new mutation. A write can already have committed when its response becomes unavailable: retain its original input and reconcile.

## Receive corresponding webhooks

Scenario 06 needs a separate owner/admin setup token with `access-keys:manage`. The ordinary reporting scopes and third-party user's consent token cannot manage destinations. Register your public HTTPS ingress before generating events, then inject its once-only secret into the receiver:

```sh
export MDLOGIC_WEBHOOK_URL='https://your-public-receiver.example/webhook'
python3 python/run.py 06
# Securely inject MDLOGIC_WEBHOOK_SECRET from the private webhook.json.
PORT=8080 python3 python/run.py webhook
```

[receiver.py](receiver.py) binds `127.0.0.1`, accepts `POST /webhook` with a 1 MiB maximum, verifies MDL's HMAC-SHA256 over timestamp plus the exact raw body, accepts rotation signatures within ±300 seconds, and checks signed event identity/type against headers. It atomically publishes a complete synced inbox file, returns 202 for acceptance and 200 for duplicates, including after restart. It performs no business effect. Use a transactional durable inbox/queue and idempotent worker in production; see the [webhook guide](../docs/webhooks.md). The default listener is loopback-only. For a container only, `MDLOGIC_WEBHOOK_BIND=0.0.0.0` permits the container port to be published on the host's loopback address; only these two bind values are accepted. No event body, actor email or signing secret is logged. Do not register this local listener with live MDL; use a public HTTPS ingress with request/connection limits.

## Local checks

```sh
python3 python/test_python.py
python3 -m py_compile python/*.py
python3 tests/verify.py python
```

The shared suite uses ephemeral localhost endpoints, synthetic credentials and signed synthetic webhook deliveries. It makes no live tenant changes.
