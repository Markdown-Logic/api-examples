# Java report integration

Use Java 17 or later. The HTTP client, server and cryptography come from the JDK. Gson **2.13.2** is the only dependency. Run commands from the repository root.

If Gson is not cached, install that pinned dependency once (requires Maven and access to Maven Central):

```sh
mvn -f java/pom.xml dependency:resolve
```

`java/run.sh` compiles directly with the cached jar. Set `GSON_JAR` if your dependency cache is elsewhere. No dependency is downloaded by the run script.

Configure a short-lived token in your server environment, or set `MDLOGIC_CLIENT_ID` and `MDLOGIC_CLIENT_SECRET` for your own account's automation. The program exchanges those at the OAuth server and keeps the access token only in memory. Do not put either credential in a browser or commit it to source control. See the common guides for user authorization with PKCE and least privilege.

```sh
export MDLOGIC_TEAM='YOUR_TEAM_ID'
# Supply MDLOGIC_TOKEN through your secret manager/environment, not shell history.
bash java/run.sh 01   # Create, list and update a project once
bash java/run.sh 02   # Create report.md from fixtures/report.md
bash java/run.sh 03   # Read once and update with the captured revision
bash java/run.sh 04   # Read one history page and export private report.html
bash java/run.sh 05   # Explicitly create a 30-day share; private share.json
```

Each numbered method is directly visible in [ReportExamples.java](ReportExamples.java). Set `MDLOGIC_INPUT` to another generated UTF-8 report for 02 or 03. The program never edits that source. Scenario 03 replaces the synthetic report deliberately; a real application must compare the current source, apply its edit policy and let a person resolve conflicting edits. The server's `revision` is an opaque equality token; display versions and history snapshot IDs are different concepts.

The default private state is `.local/java/`. Set `MDLOGIC_STATE_DIR` for another isolated run or user. The mapping stores stable IDs and the last successful revision; it never stores API credentials. Scenarios 01, 02, 05 and 06 save a private `pending-<number>.json` before sending a create, retaining the original API origin, method, path and complete payload without credentials. A failed/lost response retains that marker and refuses another create. Reconcile the matching project/document on the server, recover its ID into `state.json`, and only then remove the marker. If the server definitively refused the request, review its cause and remove the marker before a deliberate retry. This is a single-process demonstration; production systems need a unique local-user/report mapping and transactional operation journal, with concurrent workers coordinated.

GET requests retry only HTTP 429, with at most three attempts. They honor numeric or HTTP-date `Retry-After`, add small jitter where the five-second per-wait budget permits, and stop if the server asks for longer. Writes, token requests, network failures, redirects and other statuses never retry automatically. A 401 requires reconnecting; a 409 requires reviewing current state; a 423 keeps generated input for a deliberate retry after the protection conversion completes. A timeout/disconnect during a write has an **uncertain outcome**: read and reconcile before another write. Error logs include only bounded status/code/reason and a sanitized server request ID, without response text or credentials.

## Corresponding webhooks

An owner/admin with `access-keys:manage` must perform registration separately from a third-party user's document grant. Supply that administrative token explicitly; the ordinary client-credentials exchange requests only document/project scopes. Registration uses the live event catalogue and stores the once-only signing secret privately in `.local/java/webhook.json`.

```sh
export MDLOGIC_WEBHOOK_URL='https://your-public-receiver.example/webhook'
bash java/run.sh 06
# Read secret from the private webhook.json using your secret manager.
# Set MDLOGIC_WEBHOOK_SECRET in the receiver's server environment.
PORT=8080 bash java/run.sh webhook
```

The receiver binds `127.0.0.1`, accepts `POST /webhook`, caps bodies at 1 MiB and verifies HMAC-SHA256 over the timestamp plus the exact raw body. It checks ±300 seconds, accepts any valid `v1` signature during rotation and checks signed event identity against delivery headers. A complete authenticated envelope is written and forced to a temporary file, then published with an exclusive hard link under the SHA-256 event-ID key. It returns 202 after acceptance, 200 for duplicates, and survives process restarts. No business effect occurs in the HTTP handler. Use a real database transaction for deduplication plus durable job enqueue in production; add a supervised worker, retention policy and ingress timeouts. Do not log event bodies, actor email or share URLs.

This file-inbox demonstration requires hard-link support and a user-private state directory. POSIX permissions are set on macOS/Linux; on Windows configure user-only ACLs before running. Behind a production reverse proxy, terminate TLS and bound connection/body timeouts; MDL will not register a private localhost destination. The local test server is synthetic and never registers a destination with MDL.

## Local checks

```sh
python3 java/test_java.py
python3 tests/verify.py java
```

Both use isolated localhost services and synthetic secrets. No live account is modified.
