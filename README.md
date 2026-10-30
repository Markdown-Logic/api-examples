# Markdown Logic API examples

An application generates a report, stores it in its user's Markdown Logic project, refreshes it safely, and exports or shares it when asked. Six small scenarios show the same workflow in **JavaScript/Node, Java, C#, Go, Python and shell**. These are readable integration examples, with direct HTTP calls and small local helpers.

Start with the [API introduction](docs/api-introduction.md), [report integration guide](docs/report-workflow.md) and [API reference / OpenAPI](reference/README.md). The [error guide](docs/errors.md) explains refusals and uncertain results; the [webhook guide](docs/webhooks.md) connects the request workflow to events.

## Pick a language

| Language | Setup | Run one scenario from this directory |
| --- | --- | --- |
| JavaScript / Node | [Node guide](node/README.md), Node 22+ | `node node/run.mjs 01` |
| Java | [Java guide](java/README.md), Java 17+, Gson 2.13.2 | `bash java/run.sh 01` |
| C# | [C# guide](csharp/README.md), .NET 8 SDK | `dotnet run --project csharp -- 01` |
| Go | [Go guide](go/README.md), Go 1.22+ | `bash go/run.sh 01` |
| Python | [Python guide](python/README.md), Python 3.11+, standard library only | `python3 python/run.py 01` |
| Shell | [Shell and mdlogic CLI guide](shell/README.md), Bash/curl/jq/Python 3 | `bash shell/run.sh 01` |

Node, Java, Go, Python and shell have been exercised against synthetic localhost services. C# compiles and runs in an isolated official .NET 8 container; no host .NET SDK is required for that route. See [validation evidence](docs/validation.md) for the precise matrix.

Prefer Docker? See the [container quick starts](containers/README.md) for all six languages, including the localhost networking distinction.

## Configure once

Supply credentials through your server's environment or secret manager. Obtain an authorized account/team and an existing credential; these examples never provision accounts or credentials.

```sh
export MDLOGIC_TEAM='your-team-id'
# Inject MDLOGIC_TOKEN securely, or both MDLOGIC_CLIENT_ID and
# MDLOGIC_CLIENT_SECRET for your own account's automation.
# Never paste a real secret into this README, a committed .env or browser code.
node node/run.mjs 01
node node/run.mjs 02
node node/run.mjs 03
```

`MDLOGIC_TOKEN` takes precedence. Without it, the programs exchange client credentials once at the authorization server and keep the resulting token in memory. They do not refresh or replay refused authorization. [Connecting another user's account](docs/report-workflow.md#connect-the-right-account) uses authorization code with PKCE through your server; your application's own credential does not impersonate that user.

| Variable | Purpose / default |
| --- | --- |
| `MDLOGIC_API_ORIGIN` | Canonical API origin: `https://api.markdownlogic.com` |
| `MDLOGIC_OAUTH_ISSUER` | Authorization server: `https://auth.markdownlogic.com` |
| `MDLOGIC_TOKEN` | Server-held OAuth access token |
| `MDLOGIC_CLIENT_ID`, `MDLOGIC_CLIENT_SECRET` | Alternative for an account's own server automation |
| `MDLOGIC_TEAM` | Selected authorized team; required for 01 and 06 |
| `MDLOGIC_STATE_DIR` | Private local output/mapping directory; `.local/<language>` |
| `MDLOGIC_INPUT` | Generated UTF-8 report; defaults to the matching synthetic fixture |
| `MDLOGIC_WEBHOOK_URL` | Your public HTTPS receiver, used only by explicit scenario 06 |
| `MDLOGIC_WEBHOOK_SECRET` | Once-only signing secret, held by the receiver |
| `MDLOGIC_WEBHOOK_BIND` | Receiver binding; native default loopback; container adapter selects `0.0.0.0` internally |
| `PORT` | Receiver loopback port; 8080 |

HTTPS origins are required; HTTP is allowed only on literal loopback hosts for tests. Redirects are refused. Run each language with a separate state directory. Files contain private reports, share links and signing secrets: do not serve or commit `.local/`, and configure user-only ACLs on Windows. The examples assume one process per state directory; production needs database coordination.

## Same scenarios, same results

| # | Scenario | Corresponding outbound event | Code |
| --- | --- | --- | --- |
| 01 | Create a project, read one list page, update its name | `project.created`, `project.updated` | [Node](node/run.mjs) · [Java](java/ReportExamples.java) · [C#](csharp/Program.cs) · [Go](go/main.go) · [Python](python/run.py) · [shell](shell/run.sh) |
| 02 | Store a generated report; persist stable document ID | `document.created` | Same numbered entry in each file above |
| 03 | Read current source/revision; submit a guarded correction | `document.updated` when changed | Same numbered entry |
| 04 | Read one history page/snapshot and export HTML | No event for reads or export | Same numbered entry |
| 05 | Explicitly create a 30-day share; save its URL privately | `share.created` | Same numbered entry |
| 06 | Register a destination using the event catalogue | Then receive the events above | Same numbered entry + each language's receiver |

01–03 create or change remote content when you run them with real credentials. 04 and 05 are separate commands so exporting and sharing are explicit. History/export/sharing remain subject to the account's plan, role, credential and sharing policy. Scenario 03 is an intentional correction to a synthetic report; adapt its read/review step to your product's edit policy before using it on user-edited content.

01, 02, 05 and 06 retain private pending-operation files if a create fails or its result is uncertain. Re-running cannot silently create another project, report, share or destination. Reconcile the captured target and payload first. Later writes also remain single-attempt; [read the recovery guide](docs/report-workflow.md#recover-an-uncertain-write).

For webhooks, start a receiver and register 06 **before** making changes you want to observe. Registration requires a separate authorized owner/admin setup credential with `access-keys:manage`; ordinary report-app user grants cannot manage destinations. Never register the local test server with live MDL. See [webhook setup and durable inboxes](docs/webhooks.md).

## Test locally

```sh
python3 tests/verify.py                  # Host runtimes; C# skips if dotnet is unavailable
python3 tests/verify.py node java shell go python
python3 tests/response_validation.py node java shell go python
python3 python/test_python.py
python3 java/test_java.py
python3 shell/test_shell.py
(cd go && go test -race ./...)
python3 tests/reference_check.py         # Offline snapshot integrity / scenario route parity
```

The contract harness uses ephemeral localhost HTTP servers, synthetic credentials and signed synthetic webhook fixtures. It performs no live tenant changes or provider calls. Runtime floors beyond the versions in the [evidence](docs/validation.md) are declared requirements, not a broad platform qualification.

Source: [Markdown-Logic/api-examples](https://github.com/Markdown-Logic/api-examples). Licensed under the [MIT License](LICENSE). External dependencies retain their [upstream notices](THIRD_PARTY_NOTICES.md).
