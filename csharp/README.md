# C# report integration

Requires the **.NET 8 SDK**. No NuGet libraries. Run every command from the repository root. These files are small runnable examples; choose the scenario you need and keep your application's authorization, approval and persistence around it.

Set the common environment variables in the root getting-started guide. Use an existing short-lived `MDLOGIC_TOKEN`, or keep `MDLOGIC_CLIENT_ID` and `MDLOGIC_CLIENT_SECRET` on your server for client credentials. No credential is written to the state file. A user-consent token should come from your server's supported authorization-code + PKCE flow, described in the root auth guide; client credentials do not connect an arbitrary user's account.

```sh
dotnet run --project csharp -- 01  # Create/list/update the report project
dotnet run --project csharp -- 02  # Store the generated synthetic report
dotnet run --project csharp -- 03  # Read, then update with its revision guard
dotnet run --project csharp -- 04  # Explicitly inspect history and export HTML
dotnet run --project csharp -- 05  # Explicitly create a 30-day share link
```

The first scenario persists the project ID before listing or updating it. Scenario 02 persists the stable document ID and revision. Mapping files default to `.local/csharp/`; they are deliberately separate from the other implementations. An already mapped create is refused. Before each create, a private `pending-<number>.json` marker for 01, 02, 05 and 06 is written exclusively, retaining the original API origin, request path and exact payload (including generated source). Success persists the returned mapping and removes the marker; any failure leaves it in place. After an uncertain result, reconcile the intended project/document in MDL and save the verified mapping before removing the marker. A marker is a local stop sign, not server-side idempotency. Don't delete this state to recover a timeout: check MDL first and reconcile the original operation. Project creation has no API idempotency guarantee, and metadata updates have no document-style revision guard.

`03` uses synthetic approved report content. In a real application, compare the returned document with your application's last accepted source and review/merge user changes before replacing the complete document. The guard catches changes after the read; it does not decide whether replacing already existing edits is acceptable.

The source file is never edited or removed. Writes are sent once. A 423 conversion pause, 409 revision conflict, 401 revoked token or network failure exits nonzero with safe static guidance. Only GET 429 is retried, at most three attempts; Retry-After seconds and HTTP dates are respected, with 25–50 milliseconds of positive jitter. A wait that exceeds five seconds including jitter is refused rather than shortened. Safe bounded request IDs are included in errors for support. Each API/OAuth request has a 15-second budget including body consumption. Redirects are refused.

## Receive matching events

An MDL team owner/admin must register a publicly reachable HTTPS destination. Registration requires `access-keys:manage`, so the normal report credential and third-party user grant cannot do this. Use a separately authorized admin token for this explicit setup command:

```sh
export MDLOGIC_WEBHOOK_URL='https://hooks.example.com/webhook'
dotnet run --project csharp -- 06
```

Store the once-only signing secret from the private `.local/csharp/webhook.json` in your server's secret manager, then supply it to the receiver through `MDLOGIC_WEBHOOK_SECRET`. Never paste it into source or logs.

```sh
# MDLOGIC_WEBHOOK_SECRET must already be set securely.
PORT=8080 dotnet run --project csharp -- webhook
```

The listener binds `127.0.0.1` for local testing. Live MDL cannot register a private or loopback URL; use a proper HTTPS ingress for a deployed receiver. A signature is HMAC-SHA256 over `timestamp + "." + raw bytes`, with a 300-second clock window and any matching `v1` signature accepted during rotation. Authentication happens before JSON parsing or inbox creation. `MDL-Event-Id` must match the signed body ID; `MDL-Delivery-Id` is never the deduplication key.

The receiver atomically publishes a complete private inbox file keyed by SHA256(event ID), replies 202 for its first acceptance and 200 for duplicates, including after restart. It does no business work and writes no payload logs. A real service should transactionally deduplicate and enqueue, authorize the team/resource mapping, then process asynchronously with its own retention policy. On Unix, created files are mode 0600 and directories 0700. On Windows, preconfigure a private state directory with appropriate account ACLs before running; these examples do not configure ACLs.

Share URLs live in private `share.json`, not stdout. Treat the exported HTML as user content; don't inject it into an application page without a deliberate sanitization policy.

## Verification status

See [TESTING.md](TESTING.md). The host has no .NET SDK, but this implementation was compiled and executed in the official .NET 8 SDK container (Linux arm64). Use `bash containers/run.sh csharp setup`, then `bash containers/run.sh csharp 01` from the repository root. [Container quick starts](../containers/README.md) explain secret injection, state and localhost networking. No live account requests are needed for the test suite.
