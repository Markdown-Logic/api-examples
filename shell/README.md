# Shell: generate, store and refresh a report

Requirements: Bash, curl, jq and Python 3. Python handles origin validation,
HTTP-date parsing and the webhook receiver using its standard library. Every
API call uses curl; there is no MDL SDK dependency. Bash 3.2 or newer is supported.

Read [`scenarios.sh`](scenarios.sh) first: each named function implements one
numbered task, in the same order as the other languages. [`run.sh`](run.sh) is
the entry point. [`http.sh`](http.sh) handles authentication and bounded curl
requests; [`state.sh`](state.sh) manages private mappings and pending-create
markers. [`helpers.py`](helpers.py) contains the small standard-library adapters
for origin validation, retry delays and form encoding.
[`webhook.py`](webhook.py) is the separate webhook listener. The shell helper
files are sourced by the entry point, rather than run independently.

Run from the repository root. Obtain authorized credentials and a team ID using
the [common getting-started guide](../README.md); keep credentials server-side.
The environment names match the other languages:

```bash
export MDLOGIC_TEAM='your-team-id'
# Supply MDLOGIC_TOKEN through your secret manager, or use both
# MDLOGIC_CLIENT_ID and MDLOGIC_CLIENT_SECRET. Never commit their values.
bash shell/run.sh 01  # Create a project, read its first page and update its name.
bash shell/run.sh 02  # Create report.md from fixtures/report.md; save stable ID.
bash shell/run.sh 03  # Read current revision, then store the corrected report.
bash shell/run.sh 04  # Read one history page/snapshot and export report.html.
bash shell/run.sh 05  # Explicitly create a 30-day share link.
```

`MDLOGIC_INPUT` can name your own generated UTF-8 report for 02 or 03.
Local input is never overwritten or removed. Outputs default to `.local/shell/`,
with private directory/file permissions. `MDLOGIC_STATE_DIR` selects another
private location. `state.json` records stable project/document IDs and revision;
`share.json` holds the private share URL. Only IDs and file paths are printed.
Do not put the output directory in a web server's document root. The entry point
validates the mapping before authentication; malformed state is preserved for
inspection. Response helpers check required IDs and revisions before a task can
use them, without echoing raw response diagnostics.

01, 02, 05 and 06 save `pending-<number>.json` before attempting creation.
The marker records the original API origin, method, exact path and request body,
so changing the environment cannot lose the original target. They retain the
marker on refusal or uncertain outcome, preventing another
creation on rerun. Reconcile with the team project list or project's document
list and the generated source before saving a recovered mapping or deliberately
removing a marker. A name alone is insufficient proof of ownership. See the
[application workflow guide](../docs/report-workflow.md) for production locking,
unique local mappings and uncertain-result handling. This single-process demo
is not a replacement for a transactional application database.

GET requests retry only HTTP 429, up to three total attempts, using Retry-After
seconds or HTTP dates and small positive jitter. A wait over five seconds stops
immediately; it is not shortened. Writes, network failures, 401, 409 and 423 are
not automatically repeated. The complete curl request, including response body,
has a 15-second timeout. Redirects are refused. A 423 preserves the source;
wait for conversion, review the current state and deliberately resume. Error
output contains bounded codes, reasons and request IDs, never server error text,
input, share links or credentials. Bearer headers are passed on curl's config
stdin rather than its command line; OAuth credentials travel in a private
short-lived form file. Disable shell tracing (`set -x`) around all secret setup.

## Receive corresponding webhooks

Configure a separate owner/admin credential with `projects:read` and `access-keys:manage` for setup;
the ordinary report application's scopes do not manage destinations. A
third-party user's consent grant cannot acquire that administrative scope.
Registration checks the event catalogue before subscribing to document/project
creation and update plus share creation:

```bash
export MDLOGIC_WEBHOOK_URL='https://your-public-receiver.example/webhook'
bash shell/run.sh 06
# Securely load the once-only secret from .local/shell/webhook.json into
# MDLOGIC_WEBHOOK_SECRET, then start the receiver behind your HTTPS ingress:
bash shell/run.sh webhook
```

The receiver binds `127.0.0.1:8080`; `PORT` overrides the port. Do not register
localhost against live MDL. Use a public HTTPS ingress to the receiver. The
stored `webhook.json` is the only copy of the creation response; protect it.

The receiver authenticates **raw bytes** with the actual MDL HMAC-SHA256 contract,
checks timestamps within 300 seconds in either direction, supports multiple
`v1` values during rotation and compares digests with `hmac.compare_digest`.
It checks signed body identity/type against delivery headers before accepting.
A 1 MiB limit bounds input. Atomic durable inbox files deduplicate the stable
`MDL-Event-Id` across restarts. First acceptance is 202; duplicate is 200; invalid
signature is 401. This example accepts work into an inbox and performs no
business side effect. A production worker needs a transactional queue and
idempotent processing; do not equate inbox acceptance with completed processing.
Body/actor details are never logged. Store inbox data with your application's
normal retention and access policy.

## Equivalent mdlogic CLI commands

These commands target published **mdlogic 1.1.1**. Behavior from unreleased
versions is not assumed.
The curl scripts above implement their own deliberately narrower retry policy;
CLI internal transport behavior is not a promise of this repository.
Use an already installed `mdlogic` 1.1.1; no install is needed for curl examples.

```bash
# Install the verified release; requires Node 22, 24 or 26.
npm install -g mdlogic@1.1.1
umask 077
mdlogic --version
# READ: check the authorized target before creating anything.
mdlogic project list --team "$MDLOGIC_TEAM" --json
# WRITE: explicitly create a separate example project when wanted.
mdlogic project create 'Report integration example' --team "$MDLOGIC_TEAM" --json
mdlogic project list --team "$MDLOGIC_TEAM" --json
# Copy the chosen stable project ID to MDLOGIC_PROJECT through your environment.
# WRITE: creates report.md and refuses an existing destination.
mdlogic doc create fixtures/report.md --name report.md --json > created.json
DOCUMENT_ID=$(jq -er '.artifact.id | select(type=="string" and length>0)' created.json)
mdlogic doc list --json
# READ: fetch the stable document identity and current revision.
mdlogic doc get "$DOCUMENT_ID" --json > observed.json
# Review observed.json against the correction before submitting this exact guard.
REVISION=$(jq -er '.document.revision | select(type=="string" and length>0)' observed.json)
# WRITE: submit the correction only after reviewing the current source.
mdlogic doc update "$DOCUMENT_ID" fixtures/report-updated.md \
  --expected-revision "$REVISION" --json
mdlogic versions list "$DOCUMENT_ID" --json
# Use a real version ID returned above:
mdlogic versions show "$DOCUMENT_ID" "$VERSION_ID" --json
mdlogic render "$DOCUMENT_ID" --format html --out report.html
# Only when sharing is explicitly requested:
mdlogic share create "$DOCUMENT_ID" --expires-in 30 --json > share.json
```

The block sets `umask 077` before writing private CLI output. The CLI has no project
metadata update or webhook management command, so the corresponding REST calls
remain in 01 and 06. Feature/plan/role checks still apply. The CLI JSON create
result uses `artifact`, live reads use `document`, and revision is an opaque
state token, not the display version or a timestamp.

## Local checks

```bash
python3 shell/test_shell.py
python3 tests/verify.py shell
```

Only ephemeral localhost endpoints and synthetic credentials are used. The
shared suite covers all six scenarios, bounded 429 retries (seconds/date/missing
header), exhausted/long waits, revoked auth, revision conflict, temporary refusal,
uncertain write, redirects, private outputs, authentic webhook handling and
persistent duplicate suppression.

Webhook examples are optional contract/setup demonstrations. Confirm delivery availability first; catalogue/registration availability alone does not establish active outbound sending. See the [webhook availability and setup notes](../docs/webhooks.md).
