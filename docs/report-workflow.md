# Integrate a generated report into a user's account

Imagine a reporting application with a “Save to Markdown Logic” connection. A user authorizes the connection and chooses a team/project. Your server generates a monthly report, stores it once, and later submits a correction. The user can separately request an export or share. Webhooks update your application's “saved” status when someone changes the document in MDL.

The runnable examples use synthetic report fixtures and create a demonstration project in 01. A production product would usually let the person select an existing project. Nothing about a generated report makes it safe to choose somebody else's team or publish a share automatically.

## Connect the right account

| Connection | Supported flow | Ownership and storage |
| --- | --- | --- |
| An account automates its own reports | OAuth `client_credentials` at `/oauth/token` | Account-created credentials stay server-side; token acts within their owner's current authority |
| Your application connects an individual user | OAuth `authorization_code` with PKCE S256; optional `refresh_token` grant for an authorized registered client | Server stores the user's connection separately; validate state, exact redirect and callback binding |

Use an existing registered REST OAuth client that supports `authorization_code`, requested scopes and your exact redirect URI. Authorized account administration can create such a client through `POST /api/v1/oauth/clients` with `grantTypes`, `scopes` and `redirectUris` as documented in the OpenAPI. This is setup, not something these examples execute. Do not substitute `/register` dynamic registration: that surface is bound to the MCP resource, so it is not a generic REST-client setup shortcut.

For a user connection, your backend creates unpredictable state and a PKCE verifier, saves them against the signed-in app session, and redirects the browser to the metadata-advertised authorization endpoint (`/oauth/authorize`). The supported request uses `response_type=code`, `client_id`, exact `redirect_uri`, `scope`, `state`, `code_challenge`, and `code_challenge_method=S256`. On callback, reject state/session mismatch and authorization errors before exchanging the one-time code. At `/oauth/token`, send `grant_type=authorization_code`, `code`, identical `redirect_uri`, `client_id` and `code_verifier`, plus the registered client's authentication method. Retain the original resource binding if one was specified; do not guess an audience or switch resources between grants.

Access and refresh tokens belong in encrypted server storage keyed to the application user/connection. Rotate refresh tokens according to the actual token response and never replay a used authorization code or stale refresh token. A 401 requires reconnect/revocation handling, not trying another user's credential. These examples accept that connection's short-lived access token via `MDLOGIC_TOKEN`; they deliberately omit a web login/callback framework.

A server-owned client credential always acts within its owner's authority. It is not an impersonation mechanism. The backend must validate its own authenticated user, chosen connection, authorized team/project and report mapping before calling MDL. Share/export endpoints on your backend need the same checks.

## 01 — Prepare a project

Create a document-mode project explicitly, save its ID immediately, read one bounded team project page and update the project name. Project metadata updates do not support the document revision mechanism; coordinate concurrent settings writers in your application. Owner/admin setup and plan limits may refuse creation.

In a real product, persist `(appUserId, connectionId, reportKey) -> (teamId, projectId, documentId)` with a database uniqueness constraint and lock/lease the report job. A shared mutable name is not that mapping. The local examples use private `state.json` and one process per state directory so the teaching code stays small.

## 02 — Generate and save once

Generate UTF-8 Markdown to a durable local job record or file before contacting MDL. POST a create-only publish with `name=report.md`, `content`, `format=markdown` and `ifNotExists=true`. Store the response's **`artifact.id`** and opaque `artifact.revision`. A collision is a review task; do not remove create-only behavior or add replacement guards automatically.

The examples persist the original target and payload in `pending-02.json` before sending. They retain that private record on a refused or uncertain create and block another create until reviewed. 01 does the same for a project. Keep the journal and input out of logs and public storage. Production transactions must coordinate the pending operation and mapping, including process crashes and concurrent workers.

## 03 — Refresh with concurrency safety

Read by stable document ID and compare the current source with your generated correction. The synthetic scenario deliberately replaces its own sample; a product should decide whether it owns the whole document, owns one section or must ask the person to merge changes. Only after that decision should it send the read revision as `expectedRevision` with the new complete content.

A concurrent edit produces a conflict; stop and preserve both the current and proposed source. Do not swap the guard for a newer token inside a retry loop. Identical content may return `decision=no-op` and does not imply a fresh change event. A success response's revision is worth saving for display/reconciliation, but the next deliberate update needs its own current read and review.

## 04 — Inspect history and export on request

Read one versions page, then a snapshot by its actual version ID. Export HTML bytes to a private file only when the user requests it. `hasMore=true` means more history exists; later pages are a live view and may shift. History and rendering capability checks can refuse an operation. Historical version IDs, release labels and live revision tokens serve different purposes.

## 05 — Share explicitly

Create a 30-day document link after the user requests sharing and your application confirms its policy. Save the returned share record privately; the URL is a bearer-like access link. Do not automatically set `acknowledgeSensitive`, disable a policy, or change a team setting after a refusal. The examples refuse a second saved share/destination result to prevent accidental repeats. Revocation is available in the API reference; this first scenario does not revoke user-created links automatically.

## 06 — React to changes

After delivery availability is confirmed, an owner/admin separately configures a public HTTPS receiver using an authorized setup token with `projects:read` and `access-keys:manage`. Setup endpoints alone do not establish that outbound sending is active. The report application's ordinary user consent token cannot manage that configuration. Start the receiver and subscribe before the report changes: registering a destination does not replay earlier events. [The webhook guide](webhooks.md) explains raw-byte authentication, inbox acceptance and processing after acknowledgment.

## Recover an uncertain write

A network timeout or connection drop can happen after MDL committed a write. Never infer that “no success response” means “nothing happened.” The ordinary project/document/share creation routes do not offer a universal exactly-once guarantee in this example. Use an idempotency key only when the specific operation documents one.

Keep the original payload, connection, team/project and pending marker. Inspect the authorized project's bounded document list or team project list, and read the candidate resource and content using stable IDs where known. Match the original intent and verify ownership/content; a matching name alone is insufficient. Recover the committed ID into your local mapping only after that review. If no candidate can be established, leave the job pending for deliberate resolution. Remove a pending marker only after recovering a committed mapping or confirming the request did not commit and authorizing a new attempt.

For a lost guarded-update response, read the same stable document and compare its actual source/hash to the proposed source and prior state. The fact that a revision changed does not identify your write. Do not re-create the document. Shares and webhook registration retain their own pending markers and need reconciliation; list existing shares or destinations before another create. A lost webhook creation response loses access to its once-only secret: an authorized admin must rotate it and deploy the replacement safely rather than assuming it can be read again.

A temporary 423 preserves the report and pending state. Resume the job deliberately after conversion and a new review. [The error guide](errors.md) shows the same decision for every implementation.
