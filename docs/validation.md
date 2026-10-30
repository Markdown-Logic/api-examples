# Validation evidence

Checked on 2026-10-30 using synthetic API/OAuth fixtures and signed webhook deliveries. Tests create no live tenants, credentials or provider operations. Public reference downloads occurred during the initial preparation; the bundled specification is unchanged. Container setup downloads only official images and language/OS dependencies.

| Implementation | Host runtime executed | Official container runtime executed |
| --- | --- | --- |
| Node | Node 26.12.1, macOS arm64 | Node 22.23.4, Linux arm64 |
| Java | Corretto 24.0.2; `javac --release 17` | Temurin 17.0.20.1, Linux arm64; Gson 2.13.2 |
| C# | No host SDK installed | .NET SDK 8.0.427 / runtime 8.0.33, Debian 12 Linux arm64; zero build warnings/errors |
| Go | Go 1.27.3, macOS arm64 | Go 1.27.3, Linux arm64 |
| Python | Python 3.15.1, macOS arm64 | Python 3.11.18, Linux arm64 |
| Shell | Bash 3.2, system curl/jq and Python 3.15.1 | Bash 5.2.15, Debian curl/jq and Python 3.11.18, Linux arm64 |

[Container image IDs/digests](../reference/container-images.json) record exact tested artifacts. Go 1.22 remains a declared/source-reviewed floor, not an executed runtime qualification. Native C# on macOS/Windows, x64 and Windows host scripts are not qualified here. CLI 1.1.0 equivalents were checked for compatibility; installed CLI execution is not part of this matrix.

The shared matrix covers all six numbered scenarios, actual response envelopes and revision guards, private output, exact UTF-8 input, bounded 429 retries/date/fallback/long waits, 401/409/423, refused redirects, mutation connection-loss ambiguity and complete-body timeout. Unknown project/report/share/webhook creates retain their original intent and block repeats. Malformed mutation responses remain private evidence and do not clear pending state.

[Response validation regressions](response-validation-results.txt) cover wrong field types, empty create/live/update revisions, malformed history, safe malformed-error logs, enormous Retry-After, exact CRLF preservation and curl configuration isolation. Focused suites additionally passed Java 5 tests, shell 3 tests, Python 5 tests and Go 8 tests with race detection/static checks. Cancellation checks confirmed that Java retains interruption state and Python does not reconnect after a timed-out write.

Receivers were tested for valid/invalid/stale/future/tampered signatures, multiple v1 values, signed event identity/type checks, concurrent duplicate acceptance and persistence across restart. [Bridge-port checks](container-receiver-results.txt) exercise all six container receivers through loopback-only host ports. Complete queued JSON is checked; power-loss durability and production transactional business effects are outside this file-inbox demonstration.

The final six-container matrix passed all three groups in 231.938 seconds. The five host-runtime matrix passed three groups in 154.580 seconds; all-six container response-validation checks passed in 43.305 seconds, and bridge receiver checks passed in 10.041 seconds.

Captured results:

- [Full six-container scenario/failure/webhook matrix](test-results.txt).
- [Five host-runtime matrix](native-test-results.txt); C# uses the container route.
- [All six container response-validation checks](response-validation-results.txt).
- [All six bridge receiver checks](container-receiver-results.txt).

`tests/reference_check.py` passed three offline checks: snapshot integrity/version/origin, published scenario routes and local documentation links. The production OpenAPI snapshot still has SHA-256 `19f1d879979a53d77e957ca6572b8fc28529c92b56c030fadba5dc6a935259f1`; no private/candidate paths were added.

The host-runtime matrix ran on macOS arm64. Container checks ran on Linux arm64 using OrbStack. No host .NET SDK was used. Native C# on macOS/Windows, x64 and other host/container combinations remain outside the tested matrix.
