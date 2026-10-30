# C# tests

The numbered scenarios are separate classes; the shared harness still exercises the public command interface rather than calling private helpers. This keeps the checks useful if implementation details change.

The shared localhost contract harness covers these behaviors when run against `dotnet run --project csharp -- <scenario>`:

1. Scenarios 01–06 issue the same routes/bodies as the other languages; create persists stable mappings and a private original-target/payload marker until success, update sends the just-read opaque revision, history is bounded, export writes bytes, share and webhook registration require explicit commands.
2. A GET receiving 429 respects integer/date Retry-After, stops after three attempts and refuses waits over five seconds. A write receiving 429 has one attempt.
3. HTTP 423 preserves the generated input; 401 does not refresh/replay; 409 does not reread/retry. No redirect forwards credentials.
4. A signed webhook is recorded once, including after restart; invalid, stale/future, altered and mismatched-id deliveries never enter the inbox; a valid second `v1` signature is accepted.
5. State, share URLs and once-only webhook secrets use private files; tokens, raw API errors and document text never appear in logs.

The Mac has no host .NET SDK/compiler. The isolated Microsoft .NET 8 SDK container compiled this project with zero warnings/errors and executed the shared scenario, security and response-validation tests on Linux arm64. SDK 8.0.427 / runtime 8.0.33 were observed. Native macOS/Windows remain unqualified.

```sh
bash containers/run.sh csharp setup
python3 tests/verify.py csharp-docker
python3 tests/response_validation.py csharp-docker
```

The test adapter uses explicit host networking for the host-side synthetic fixtures. Ordinary quick starts use bridge networking; see [container networking](../containers/README.md#container-localhost-is-its-own-machine). No host SDK was installed.
