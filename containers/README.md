# Run without a host language installation

Install Docker separately if you do not already use it. These optional adapters use official Node, Maven/Eclipse Temurin, Go, Python and Microsoft .NET images. Shell uses a small image based on official Python with Debian curl/jq packages. They do not install language SDKs on the host. Docker setup downloads images/dependencies explicitly; running examples never pulls implicitly.

From the repository root, choose one language:

```sh
bash containers/run.sh node setup
# Inject MDLOGIC_TOKEN or client credentials through your secret manager/environment.
export MDLOGIC_TEAM='your-authorized-team-id'
bash containers/run.sh node 01
bash containers/run.sh node 02
bash containers/run.sh node 03
```

Replace `node` with `java`, `csharp`, `go`, `python` or `shell`. The setup step prepares only that language. Java resolves its one pinned Gson dependency into `.local/containers/java/`; C# setup compiles with networking disabled after its SDK image is downloaded. All other commands use the same numbered scenarios as the native quick starts. Real credentials cause real authorized content changes: use the [synthetic test harness](../README.md#test-locally) to validate locally.

Source is mounted read-only. State and build/dependency caches are separate ignored directories under `.local/`; `MDLOGIC_STATE_DIR` selects another private state directory. Each language uses separate mappings. Credentials pass through environment variables at runtime, never Dockerfile instructions or build arguments. Do not enable shell tracing or commit generated state. The runtime runs as the calling user's UID/GID so private output remains accessible on Linux. C# compilation runs as container root and assigns only its generated build output back to that UID/GID.

| Language | Image |
| --- | --- |
| Node | `node:22-bookworm-slim` |
| Java | `maven:3.9-eclipse-temurin-17` |
| C# | Official `mcr.microsoft.com/dotnet/sdk:8.0`, digest pinned in its adapter |
| Go | `golang:1-bookworm` |
| Python | `python:3.11-slim-bookworm` |
| Shell | `containers/Dockerfile.shell`, based on official Python |

[Validation](../docs/validation.md) records the exact tested versions and image identities. Tags can move on later setup; inspect/review image updates as part of your normal dependency maintenance.

## Container localhost is its own machine

For ordinary HTTPS MDL API calls, the default Docker bridge network works across Linux, macOS and Windows Docker hosts. `http://127.0.0.1` **inside a container points to that container**, not to a mock server on your laptop.

The host-side fixture tests use `MDLOGIC_CONTAINER_NETWORK=host` explicitly. This was exercised with OrbStack on macOS and its host loopback forwarding. Linux host networking normally shares the host namespace. Docker Desktop's host-network support depends on its platform/configuration; it is not assumed or enabled by these scripts. Do not replace the origin with an arbitrary HTTP hostname to bypass the examples' HTTPS checks. On an unsupported host, run the native fixture tests or run the mocks in the same isolated network namespace as the examples.

On a supported local host-network setup:

```sh
python3 tests/verify.py node-docker java-docker csharp-docker go-docker python-docker shell-docker
python3 tests/response_validation.py node-docker java-docker csharp-docker go-docker python-docker shell-docker
```

Java and .NET container adapters prefer IPv4 for the tested OrbStack host-loopback behavior; native example defaults are unchanged.

Those commands require Python on the host only for the test harness, use synthetic credentials, and select the host-network test mode themselves. Runtime quick starts above need only Docker.

## Receive a webhook locally

Bridge mode publishes only host loopback and explicitly binds all interfaces **inside the container**:

```sh
# Inject the destination's once-only signing secret into MDLOGIC_WEBHOOK_SECRET.
PORT=8080 bash containers/run.sh python webhook
```

The receiver is then reachable from the host at `http://127.0.0.1:8080/webhook`. The container adapter sets `MDLOGIC_WEBHOOK_BIND=0.0.0.0`; native programs remain loopback-only by default. This environment setting accepts only `127.0.0.1` or `0.0.0.0`. A live MDL destination still needs an authorized public HTTPS ingress; never register a private localhost test URL with MDL. Use your deployment's TLS, request limits and durable storage controls when deploying the example receiver.

These are small optional adapters, not a deployment framework. Windows users need a Bash-compatible environment (such as WSL) for the scripts and must select an appropriate private mounted directory; Windows/native runtime behavior has not been qualified by the Mac/container tests.
