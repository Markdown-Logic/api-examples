#!/usr/bin/env bash
# Optional test adapter for an existing local Docker engine; never installs a host SDK.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
image='mcr.microsoft.com/dotnet/sdk:8.0@sha256:6ba9644da07bb5b560a402acec9ca38711a0762969f1b61da261df5c9f6f85da'
# Pulling the image is an explicit setup action; no implicit pull occurs here.
docker image inspect "$image" >/dev/null 2>&1 || { echo 'Obtain the pinned Microsoft .NET 8 SDK image before using this optional adapter.' >&2; exit 1; }
if [[ ${1:-} == build ]]; then
  mkdir -p "$repo/.local/csharp-docker"
  exec docker run --rm --pull never --network none -e DOTNET_CLI_TELEMETRY_OPTOUT=1 -e DOTNET_NOLOGO=1 \
    -e DOTNET_CLI_HOME=/tmp/dotnet -e NUGET_PACKAGES=/tmp/nuget \
    -v "$repo:/src:ro" -v "$repo/.local/csharp-docker:/out" -w /src "$image" \
    bash -c 'set -e; dotnet build csharp -c Release -o /out/bin -p:BaseIntermediateOutputPath=/out/obj/ --ignore-failed-sources --disable-build-servers; chown -R "$1:$2" /out' -- "$(id -u)" "$(id -g)"
fi
[[ -f $repo/.local/csharp-docker/bin/Examples.dll ]] || { echo 'Build first: bash csharp/docker.sh build' >&2; exit 1; }
state=${MDLOGIC_STATE_DIR:-$repo/.local/csharp}
mkdir -p "$state"; state=$(cd -- "$state" && pwd)
network=${MDLOGIC_CONTAINER_NETWORK:-bridge}
[[ $network == bridge || $network == host ]] || { echo 'Container network must be bridge or host.' >&2; exit 2; }
args=(run --rm --init --label markdownlogic.examples=local --pull never --user "$(id -u):$(id -g)" --network "$network" -w /src -v "$repo:/src:ro" -v "$state:$state"
  -e "MDLOGIC_STATE_DIR=$state" -e DOTNET_SYSTEM_NET_DISABLEIPV6=1 -e DOTNET_CLI_TELEMETRY_OPTOUT=1 -e DOTNET_NOLOGO=1)
if [[ ${1:-} == webhook && $network == bridge ]]; then args+=(-e MDLOGIC_WEBHOOK_BIND=0.0.0.0 -p "127.0.0.1:${PORT:-8080}:${PORT:-8080}"); fi
for name in MDLOGIC_API_ORIGIN MDLOGIC_OAUTH_ISSUER MDLOGIC_TOKEN MDLOGIC_CLIENT_ID MDLOGIC_CLIENT_SECRET MDLOGIC_TEAM MDLOGIC_WEBHOOK_URL MDLOGIC_WEBHOOK_SECRET PORT; do
  args+=(-e "$name")
done
if [[ -n ${MDLOGIC_INPUT:-} ]]; then
  input=$(cd -- "$(dirname -- "$MDLOGIC_INPUT")" && pwd)/$(basename -- "$MDLOGIC_INPUT")
  args+=(-v "$input:$input:ro" -e "MDLOGIC_INPUT=$input")
fi
# IPv4 avoids OrbStack host-loopback refusal for .NET dual-stack sockets in this adapter.
# Host networking is only for the local test fixture/receiver; real API calls still require HTTPS.
exec docker "${args[@]}" "$image" dotnet /src/.local/csharp-docker/bin/Examples.dll "$@"
