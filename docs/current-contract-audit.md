# Current public-contract audit

Checked 2026-11-03. This update keeps the six-language reporting workflow and original MIT notices, adds a small read-first Node example, and corrects command/setup guidance. No live account, project, document, share, destination or conversion was created during the audit.

## What changed

- `node/read-projects.mjs` reads one authorized project page and reports stable IDs plus `hasMore`. It requests only `projects:read` when exchanging its own client credential. Numbered write examples retain their existing reporting scopes and safeguards.
- The shell CLI walkthrough now pins verified `mdlogic@1.1.1` with Node22/24/26, lists projects before explicit writes, extracts the stable document ID from the real `artifact` envelope, and sets private output permissions before redirecting any content.
- Webhook setup requires **both** `projects:read` for catalogue discovery and `access-keys:manage` for registration, plus owner/admin authorization. Setup/catalogue availability does not prove outbound delivery is active. These optional examples do not activate delivery or providers.
- Node report snippets now have explicit `docs:begin` / `docs:end` boundaries. The implementations remain canonical here; developer-site extraction can follow marked regions instead of fragile fixed line numbers. The markers change no request or mutation behavior.
- The new CI workflow uses read-only repository permissions and synthetic fixtures, without live credentials or conversion calls. Its official checkout/setup-node actions are pinned to release commits verified through GitHub's public release/tag API.

## Contract evidence and limits

[The audit record](../reference/current-contract-audit.json) records the current public OpenAPI hash/byte count, selected reporting routes, required scopes, revision shape and share lifetimes. It was derived only from the unauthenticated published specification. The report routes still match the examples. Its schemas are not exhaustive SDK-ready contracts; each example validates the response fields it actually needs.

The complete bundled OpenAPI remains the unchanged historical 2026-10-29 snapshot. Unrelated new notification/mobile operations were not copied into this focused examples update. Use the live API reference for the current full document.

The npm1.1.1 tarball was verified against its published integrity digest. The actual package's `--version` and create/update/share help confirm the documented flags, environment names and revision guard. These local help checks perform no API calls. The CLI's existing runtime dependency was supplied locally; it is not vendored in this MIT repository.

OAuth metadata was fetched read-only. The public MCP `initialize` probe returned HTTP403 and was not retried, rerouted or bypassed. There was no `tools/call`, conversion or private sign-in. [MCP notes](mcp.md) distinguish connection guidance from runtime acceptance and REST programs from MCP tools.

The developer-domain backlink is conditional on a verified live hub. Its initial audit lookup did not resolve, so a future URL is not published merely because routing code or a package exists.

## Checks

The original five-host-language scenario/failure/receiver suite passed before changes. Post-change validation passed the four reference checks, seven Node checks, five-language malformed-response suite, Python9/shell7/Java7 focused checks and Go race/static checks. CI runs the complete five-language scenario/failure/receiver matrix as well. Commands:

```sh
python3 tests/reference_check.py
node --test node/test.mjs node/read-projects.test.mjs
python3 tests/verify.py node java shell go python
python3 tests/response_validation.py node java shell go python
python3 python/test_python.py
python3 shell/test_shell.py
python3 java/test_java.py
(cd go && go test -race ./... && go vet ./...)
```

The new Node checks cover the read-only request path, project-page validation and exact minimal OAuth scope. Shared synthetic checks preserve revision conflicts, private files, uncertain-write refusal and no blind mutation retries. Existing .NET container evidence remains in [validation](validation.md); the new host/CI job does not claim a fresh .NET run.
