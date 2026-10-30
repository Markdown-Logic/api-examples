# Webhooks for the report workflow

Report creation/update emits `document.created` / `document.updated`; project setup emits `project.created` / `project.updated`; explicit sharing emits `share.created`. Reads, history inspection and exports emit none of those change events. The server's authenticated `GET /api/v1/webhooks/events` catalogue is authoritative; scenario 06 verifies its requested names before registering.

Use an authorized owner/admin setup credential with `access-keys:manage`. This is a separate administration task from a user's reporting connection; third-party user consent grants cannot get this scope. POST `/api/v1/teams/{teamId}/webhooks` with a public HTTPS `url`, selected `events` and a description. The response contains `secret` **once**. Each example saves that response privately as `webhook.json` and prints only an ID and path. Its normal client-credentials exchange requests reporting scopes only, so use an appropriately authorized `MDLOGIC_TOKEN` for 06.

Run any implementation's `webhook` command with `MDLOGIC_WEBHOOK_SECRET` injected into its environment. It listens on `127.0.0.1:8080` (`PORT` overrides). A real deployment needs a public HTTPS ingress; never register the local test server against live MDL. The server also rejects undeliverable private-address destinations. Register before the changes you want to receive; this example does not replay history.

## Authenticate before accepting work

MDL sends `MDL-Signature: t=<unix-seconds>,v1=<hex-hmac>`. Compute HMAC-SHA256 using the literal signing secret over the decimal timestamp, a dot, and the **exact raw body bytes**. Do not parse and reserialize JSON before verification, strip the `whsec_` prefix or substitute a different algorithm. Check both stale and future timestamps within 300 seconds. Accept any matching `v1` during secret rotation and compare digests securely.

The signed JSON envelope carries `id`, `type`, `created`, `teamId`, `actor` and `data.object`. The receivers validate the signature first and require the signed body's `id` to match `MDL-Event-Id`; they also check a supplied `MDL-Event-Type`. `MDL-Delivery-Id` identifies delivery to one destination and stays stable across retries. Each attempt refreshes its timestamp/signature; deduplicate using the authenticated event ID. Route by stable document ID and authorized team/project mapping, not by mutable path or email. An event about a deleted resource can contain its last known state.

The local handlers cap bodies at 1 MiB and durably publish a complete private inbox record under the SHA-256 of the authenticated event ID, with exclusive atomic publication. They return 202 for new acceptance and 200 for duplicates, including after restart; invalid signatures return 401 and malformed identity returns 400. The file is the queued work item. No report/business action runs inside the request handler.

A production implementation should use a database transaction with a unique event ID plus durable job enqueue, then process asynchronously with idempotent business effects. Inbox acceptance and completed processing are separate states. Coordinate concurrent workers, record processing failures and retention, and tolerate late/repeated events by reading/reconciling current state rather than assuming arrival order. Do not mark an event processed and then perform an unprotected side effect.

MDL treats non-2xx responses, redirects and timeouts as unsuccessful. Its delivery timeout is 10 seconds; documented retries are 1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours, 12 hours and 24 hours. Inspect the authorized webhook deliveries endpoint when diagnosing failures. No receiver logs raw envelopes, actor email or secrets.

## Compare implementations

[Node receiver](../node/webhook.mjs) · [Java receiver](../java/ReportExamples.java) · [C# receiver](../csharp/WebhookReceiver.cs) · [Go receiver](../go/main.go) · [Python receiver](../python/receiver.py) · [shell/Python receiver](../shell/webhook.py)

The shared tests send valid, duplicate, concurrent, stale, future, tampered, mismatched-identity and multi-signature deliveries using a synthetic secret. See [validation](validation.md). The public [webhook guide](https://markdownlogic.com/help/en/receive-webhooks) is the product reference.
