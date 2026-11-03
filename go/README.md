# Go report integration

These are small server-side examples using only the Go standard library. Go 1.22 or later is required. Run commands from the repository root; the wrapper builds locally and keeps build output under ignored `.local/`.

## Reading the examples

Start with [scenario 03](scenario_03_update_report.go) to see a complete read, revision check and update. Each numbered file contains one task, in the same order as the command table below. The scenarios return errors to the command entry point; they do not hide a failed call or retry a mutation.

| File | Responsibility |
| --- | --- |
| [main.go](main.go) | Command selection and Ctrl-C cancellation |
| [scenarios.go](scenarios.go) | Prerequisite checks and scenario dispatch |
| [scenario_01_project.go](scenario_01_project.go) | Create, list and rename a project |
| [scenario_02_create_report.go](scenario_02_create_report.go) | Create a report without replacing existing content |
| [scenario_03_update_report.go](scenario_03_update_report.go) | Update using the current opaque revision |
| [scenario_04_export_report.go](scenario_04_export_report.go) | Read history and export HTML |
| [scenario_05_share_report.go](scenario_05_share_report.go) | Create an explicitly requested share |
| [scenario_06_register_webhook.go](scenario_06_register_webhook.go) | Register report lifecycle events |
| [api.go](api.go) | Authentication, HTTP deadlines, safe errors and bounded GET retries |
| [state.go](state.go) | Private mappings, atomic saves and pending-create journals |
| [config.go](config.go) | Environment settings and service-origin validation |
| [webhook.go](webhook.go) | Signature checks, duplicate suppression and listener lifecycle |

The Go files form one `main` package. `go/run.sh` builds that package, so a scenario can use the documented common helpers without copying authentication or recovery logic. No additional Go modules are required.

## Running a scenario

Configure an existing access token and team through environment variables, following the root getting-started guide. With no `MDLOGIC_TOKEN`, the program instead exchanges `MDLOGIC_CLIENT_ID` and `MDLOGIC_CLIENT_SECRET` server-side for `projects:read documents:read documents:write`. Tokens are kept in memory. A token obtained through supported user authorization can also be supplied; client credentials do not impersonate another account.

| Command | Report scenario |
| --- | --- |
| `bash go/run.sh 01` | Create a project, list one bounded page, update its name |
| `bash go/run.sh 02` | Store `fixtures/report.md` as a new document |
| `bash go/run.sh 03` | Read the current document and update with its exact revision |
| `bash go/run.sh 04` | Read one history page and one snapshot; export current HTML |
| `bash go/run.sh 05` | Explicitly create a 30-day document share |
| `bash go/run.sh 06` | Register the matching lifecycle webhook destination |
| `bash go/run.sh webhook` | Receive signed events into a private durable local inbox |

`MDLOGIC_INPUT` selects your generated UTF-8 report without altering it. `MDLOGIC_STATE_DIR` defaults to `.local/go`; it contains the stable project/document mapping, opaque revision, HTML export, and private share/webhook responses. The last two may contain a share URL or once-only signing secret, so they are saved with mode `0600` and never printed. Scenarios 05/06 refuse to overwrite an existing private response; inspect it before deliberately registering another destination or creating another share. Team and project permissions, plan limits, and sharing policy still apply.

Scenario 03 treats the synthetic fixture as an already-reviewed generated correction. In a real integration, compare the live source with your application's last accepted version before sending the replacement. A fresh GET is not user approval to overwrite their changes. The server atomically checks `expectedRevision`; never remove or silently refresh that guard after a conflict.

Create operations first write `pending-<number>.json` for 01, 02, 05 and 06 containing the exact original path and JSON body. Another invocation refuses while that marker exists. Successful creation saves IDs before clearing the marker. After any failure, inspect the server state and retain your generated input; only remove the marker once you have established whether the create committed and repaired the mapping. A marker is not an API idempotency key. For multiple workers, use a database unique key such as `(account, applicationReportId)` and a transaction/lock, rather than the single-process JSON files in this example.

API/auth origins require HTTPS, with literal loopback HTTP accepted for local testing. Redirects are refused. Every request has a 15-second budget covering headers and the body. Only GET `429` responses are retried, for at most three total attempts. `Retry-After` seconds or HTTP dates are honored with small positive jitter; a wait over five seconds stops rather than being shortened. Without usable timing, waits start at one and two seconds. Oversized responses stop without saving partial exports.

Mutations are single-attempt, including `429`, network failures, timeouts and cancellation. `401` asks you to reconnect; `409` asks you to review current state; `423 CONTENT_TEMPORARILY_READ_ONLY` asks you to preserve input, wait for ADP conversion, and review before a deliberate retry. Unknown write outcomes require reconciliation before another write. Error output includes a bounded, sanitized `x-request-id` (or JSON `requestId`) when available and never prints the server's arbitrary error text, credentials or report content. Ctrl-C cancels active requests and retry waits.

## Webhooks

For registration, set `MDLOGIC_WEBHOOK_URL` to an explicit public HTTPS receiver. Scenario 06 checks the live catalogue before subscribing to `document.created`, `document.updated`, `project.created`, `project.updated` and `share.created`. Configure this once as an owner/admin with a separately authorized token carrying `projects:read` and `access-keys:manage`. The default client-credentials exchange requests only report scopes. Third-party user grants cannot acquire the administration scope; have the account's administrator register the destination instead. Keep the once-only secret from the private `webhook.json` response in your server's secret store.

Set `MDLOGIC_WEBHOOK_SECRET` and optionally `PORT` (default `8080`) before starting the receiver. It binds `127.0.0.1`; use an HTTPS ingress for an actual public deployment. No local test registers that loopback receiver against a live MDL service.

The receiver verifies HMAC-SHA256 over the timestamp, a dot, and the exact raw request body. It accepts any valid `v1` signature during rotation and rejects timestamps more than 300 seconds in either direction. It parses JSON only after authentication, requires the signed event ID to match `MDL-Event-Id`, and checks `MDL-Event-Type` if present. It writes a complete, synced event file before atomic inbox acceptance, returns `202` for a new event, and `200` for a duplicate, including after restart. It never treats `MDL-Delivery-Id` as the deduplication key.

The receiver demonstrates durable acceptance only. A production worker must transactionally track processing and side effects, and handle events arriving out of order. The saved envelopes may contain document metadata and actor email, so protect and expire them according to your application's retention policy. The example prints neither envelope nor actor data.

## Local checks

From this directory:

```sh
GOCACHE=/tmp/mdlogic-api-examples-go-cache go test -race ./...
GOCACHE=/tmp/mdlogic-api-examples-go-cache go vet ./...
```

From repository root, `python3 tests/verify.py go` runs the same synthetic localhost contract checks as the other languages. Tests call no live tenant or provider. Localhost binding may require the execution environment's test approval.

Webhook examples are optional contract/setup demonstrations. Confirm delivery availability first; catalogue/registration availability alone does not establish active outbound sending. See the [webhook availability and setup notes](../docs/webhooks.md).
