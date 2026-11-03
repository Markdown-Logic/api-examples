# API introduction

Markdown Logic stores text and structured documents inside team projects. Your application's backend can create content, keep it current, render a downloadable file, and create a revocable share link. An optional webhook example demonstrates the event contract; confirm delivery availability before depending on it. Published routes and successful setup do not establish that outbound delivery is enabled.

The canonical authenticated API origin is `https://api.markdownlogic.com`. Resource paths begin `/api/v1`. Send JSON as `Content-Type: application/json` and an OAuth access token as `Authorization: Bearer …`. Renders return file bytes instead of JSON. The [live API index](https://api.markdownlogic.com/) and [published OpenAPI document](https://api.markdownlogic.com/api/v1/openapi.json) are the reference; this repository includes a historical [unchanged pinned snapshot](../reference/openapi.json).

## Authentication and account boundaries

The issuer is `https://auth.markdownlogic.com`. Its [authorization-server metadata](https://auth.markdownlogic.com/.well-known/oauth-authorization-server) advertises supported OAuth endpoints and flows. Legacy `mdl_` keys and app session tokens are not accepted by the platform API. App-created API credentials are OAuth client credentials.

For your own account's backend automation, exchange client ID and secret at `/oauth/token` with `grant_type=client_credentials`. Each language shows that exchange, or accepts an already obtained `MDLOGIC_TOKEN`. For another person's account, use an authorized OAuth client and authorization code with **PKCE S256** and verified state; keep the token exchange, refresh tokens and client secret on your server. [The workflow guide](report-workflow.md#connect-the-right-account) describes the supported distinction and callback responsibilities.

Request only the scopes needed by the operation: `projects:read` to see teams/projects, `documents:read` for content/history/renders, and `documents:write` for report/project/share changes. Scope alone does not grant membership, role, plan capabilities or access to another team. A team-bound credential remains bound to that team. Webhook setup separately needs `projects:read` for its catalogue read, plus `access-keys:manage` and owner/admin permission for registration. Third-party user consent grants do not receive that administrative scope.

JavaScript here runs in **Node on the server**. A browser bundle, localStorage or publicly served configuration cannot protect a long-lived token or client secret. Keep those credentials behind an authenticated application backend that checks its own user-to-MDL connection mapping.

## Resource identity and updates

A team owns projects; a project contains documents. Documents have stable IDs and mutable logical names. Store the returned `projectId` and document `id` against your application's user and report key. Address subsequent operations through stable IDs; a path can be renamed or reused for another document.

Creating through the established `/artifacts` publishing route returns `{artifact, decision}`. A stable-ID read returns `{document}`; a stable-ID update returns `{document, decision}`. These envelopes differ deliberately. The API examples check the actual envelope rather than guessing from the route name.

A live read's `revision` is an opaque equality token. Send that token as `expectedRevision` with a complete-source `PUT`. If someone changed the document after the read, the API refuses the stale write with 409 `CONFLICT` / `details.reason=document-changed`. Read, compare and resolve the edit; never silently refresh the guard and overwrite. `version` is a display/release label, while a history snapshot has a separate version ID. Neither substitutes for a revision. Project name updates have no document-style revision guard.

[Scenarios 01–03](report-workflow.md) show those operations. [Scenario 04](../README.md#same-scenarios-same-results) shows bounded history reads and HTML export; 05 creates an explicit 30-day share. The example reads one page and reports `hasMore`; it does not imply the first page is complete or stable under concurrent writes.

## Errors and service limits

Errors include a machine `code`, optional `details` and `requestId`; the response also carries `x-request-id`. Log bounded identifiers and statuses, with static actionable guidance. Do not log bearer headers, OAuth form bodies, document text, share URLs, signing secrets or actor email. Renders and malformed responses must still produce a safe error rather than being treated as JSON blindly.

Only GET 429 responses are automatically retried here: three total attempts, Retry-After seconds or HTTP date, bounded wait and jitter. A longer server wait stops the example; no wait is shortened to force a retry. Writes, network ambiguity, other statuses and authorization failures are single-attempt. Each API/OAuth attempt has a 15-second deadline including its body. See the [error guide](errors.md) for the recovery decision table and limits.

A deployment can temporarily refuse content writes with HTTP 423 `CONTENT_TEMPORARILY_READ_ONLY`, `details.reason=data-protection-conversion`, and `details.retryable=true`. Preserve the generated report. Wait for conversion to finish, review current state, then decide to retry. That flag does not authorize an immediate replay. This is defensive compatibility handling; the bundled production OpenAPI snapshot does not establish deployment or availability of that response or feature. No example enables, disables or changes protection settings.

## Webhooks complete the workflow

[Scenario 06 and the receivers](webhooks.md) use actual `document.created`, `document.updated`, `project.created`, `project.updated` and `share.created` events, checked against the server's event catalogue. They verify HMAC-SHA256 over timestamp plus raw bytes, check clock tolerance, and deduplicate the stable event ID into a durable inbox before acknowledgment. A delivery ID identifies delivery of an event to one destination and stays stable across retries; each attempt refreshes its timestamp and signature.

For the broader product guides, see [using REST](https://markdownlogic.com/help/en/use-the-rest-api), [receiving webhooks](https://markdownlogic.com/help/en/receive-webhooks), [CLI installation](https://markdownlogic.com/help/en/install-the-cli), [CLI exports](https://markdownlogic.com/help/en/export-from-the-cli), [sharing](https://markdownlogic.com/help/en/share-a-document), and [team automation](https://markdownlogic.com/help/en/automate-team-documents). These URLs were checked against the public site; [verification evidence](../reference/link-check.json) records the check.
