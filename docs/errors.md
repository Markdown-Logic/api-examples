# Error handling and recovery

Every implementation demonstrates these decisions with the same scenarios. The language helpers intentionally have a small, fixed policy so the recovery behavior is easy to see.

| Result | Example behavior | Application action |
| --- | --- | --- |
| 401 authentication/revocation | Stop; no refresh or replay | Reconnect the same user's account or correct the authorized credential |
| 403 permissions/plan/policy | Stop | Explain the missing authority/capability; do not escalate the token or change settings automatically |
| 409 stale revision | Stop with input intact | Compare current source and resolve changes; never silently replace the guard |
| 423 temporary ADP refusal | Stop with input/pending marker intact | Wait for conversion, review the live state, deliberately resume |
| GET 429 | At most three total attempts | Honor Retry-After seconds/date plus jitter if within the five-second per-wait budget |
| Mutation 429 | Single attempt | Keep intent and pause; review before any new attempt |
| 5xx or malformed/unexpected response | Stop | Inspect safe status/request ID and reconcile mutations before retry |
| Network timeout/cancellation/drop | Stop; a mutation can have committed | Reconcile the original target and payload; do not create a duplicate |
| Redirect | Refuse | Configure the canonical origin directly |

Missing Retry-After uses 1 then 2 seconds plus small jitter. A supplied wait larger than the budget stops; it is never truncated to an earlier retry. A malformed Retry-After may stop or use bounded fallback depending on the language's standard parser; no implementation increases its attempt budget. These are example client limits, not a statement of the MDL service's rate quotas. The real response controls timing.

Each request has a 15-second deadline that includes response consumption. Reads retry only 429; this repository does not retry network failures, 5xx or authorization failures automatically. Total command time can include multiple requests and bounded waits. Cancellation does not roll back a server mutation. Keep operation journals and source durable before sending so process termination is recoverable.

Errors expose HTTP status and bounded machine fields when available, including `x-request-id` / `requestId`. Raw server error text is untrusted and may contain private data, so it is not echoed. Log request IDs for support, plus the operation type and result; avoid document bodies, tokens, OAuth secrets, share URLs, webhook bodies and actor email. Treat local output and pending files as sensitive data with a retention policy.

The `CONTENT_TEMPORARILY_READ_ONLY` branch handles temporary content-write refusals defensively. Its `details.retryable=true` indicates a temporary condition, not permission to loop. ADP deployment/availability is not asserted by this repository. No example bypasses a refusal or alters protection/security settings.

[Recovery examples](report-workflow.md#recover-an-uncertain-write) explain why local mapping, revision checks and application transactions are still required even when the HTTP method is a PUT. [The test matrix](validation.md) records exactly what was exercised.
