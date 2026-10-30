# API reference and OpenAPI

Use the [live API index](https://api.markdownlogic.com/) and [production OpenAPI](https://api.markdownlogic.com/api/v1/openapi.json) for the current platform contract. The [general introduction](../docs/api-introduction.md) explains authentication, resources and update safety before you inspect endpoint details.

[openapi.json](openapi.json) is a **verbatim download from the unauthenticated production specification endpoint**, with its source URL, retrieval time, byte count and SHA-256 in [provenance.json](provenance.json). It advertises OpenAPI 3.0.3 and API `info.version` 1.1.0. That semantic version is not a deployed Git commit: the endpoint does not provide one, so production commit provenance is explicitly unknown. No paths, descriptions or schemas were edited, reformatted, filtered or synthesized from candidate source.

The bundled public reference supports offline use. It includes the production document's gated administration routes; their presence does not grant authority or make them part of the report workflow. This repository introduces no private/staging route catalog. The repository license is recorded in [LICENSE](../LICENSE). The reference retains its upstream content and provenance.

## Find the matching example

| Reference topic | Scenario / guide | Language implementation |
| --- | --- | --- |
| OAuth and current authorization | [Introduction](../docs/api-introduction.md#authentication-and-account-boundaries), [user connection](../docs/report-workflow.md#connect-the-right-account) | [Node transport](../node/api.mjs), [Java](../java/ReportExamples.java), [C#](../csharp/MdlApi.cs), [Go](../go/main.go), [Python](../python/run.py), [shell](../shell/run.sh) |
| Teams/projects; create/read/update | [01](../docs/report-workflow.md#01--prepare-a-project) | [Node](../node/run.mjs), [Java](../java/ReportExamples.java), [C#](../csharp/Program.cs), [Go](../go/main.go), [Python](../python/run.py), [shell](../shell/run.sh), entry 01 |
| Document publish and stable IDs | [02](../docs/report-workflow.md#02--generate-and-save-once) | Same files, entry 02 |
| Concurrency and complete-source replacement | [03](../docs/report-workflow.md#03--refresh-with-concurrency-safety) | Same files, entry 03 |
| Versions and render bytes | [04](../docs/report-workflow.md#04--inspect-history-and-export-on-request) | Same files, entry 04 |
| Document share creation and policy | [05](../docs/report-workflow.md#05--share-explicitly) | Same files, entry 05 |
| Event catalogue, destination registration, signing | [06 / webhooks](../docs/webhooks.md) | Same files, entry 06; [receivers](../docs/webhooks.md#compare-implementations) |
| Refusals, request IDs and rate limits | [Error guide](../docs/errors.md), [uncertain writes](../docs/report-workflow.md#recover-an-uncertain-write) | Each language's request helper |

Inspect each OpenAPI operation's `x-required-scope`, parameters, schemas and responses. Some operations publish more detailed schemas than others; the specification is not a guarantee that every success/error body is exhaustively typed. The examples explicitly check the response fields needed for each operation. Do not treat a generic 200 description as a response-envelope example.

## Keep the snapshot current

1. Run `python3 tools/update-openapi.py`. It downloads only the fixed public production URL, compares raw bytes and reports drift without changing files.
2. Review the live contract and any source release evidence. To accept a newer snapshot, run `python3 tools/update-openapi.py --update`.
3. Review `git diff -- reference/`. The raw response must stay unmodified; provenance records the download, not an inferred release commit.
4. Run `python3 tests/reference_check.py` and the affected language contract tests. Update scenario explanations when behavior changes. Run `python3 tools/check-public-links.py` to refresh the public-link evidence separately.

Do not update this file from a staging endpoint or generate it from unreleased source and label it production. Snapshot verification is offline; update/link checks are explicit read-only public network operations.

## Compatibility

The examples use the published routes and response shapes in the bundled reference. Defensive HTTP 423 handling preserves source when a deployment temporarily refuses content changes; the snapshot does not establish availability of that response or a protection feature. No example changes protection or security settings.

CLI commands target published `mdlogic` 1.1.0. They do not assume behavior from unreleased versions. See the [shell guide](../shell/README.md) for the commands and their scope.

Public API, authorization metadata and help links are collected in the [introduction](../docs/api-introduction.md) and [link-check.json](link-check.json), which records their HTTP status and check date.
