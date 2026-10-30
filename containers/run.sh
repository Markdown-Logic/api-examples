#!/usr/bin/env bash
# Small optional adapter; source is read-only, state/build caches stay under .local.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
language=${1:-}; shift || true
case "$language" in
  node) image=node:22-bookworm-slim;;
  java) image=maven:3.9-eclipse-temurin-17;;
  go) image=golang:1-bookworm;;
  python) image=python:3.11-slim-bookworm;;
  shell) image=api-examples-shell:local;;
  csharp)
    if [[ ${1:-} == setup ]]; then docker pull 'mcr.microsoft.com/dotnet/sdk:8.0@sha256:6ba9644da07bb5b560a402acec9ca38711a0762969f1b61da261df5c9f6f85da'; exec bash "$repo/csharp/docker.sh" build; fi
    exec bash "$repo/csharp/docker.sh" "$@";;
  *) echo 'Use node, java, csharp, go, python or shell, then setup or a scenario.' >&2; exit 2;;
esac
cache="$repo/.local/containers/$language"; mkdir -p "$cache"
if [[ ${1:-} == setup ]]; then
  if [[ $language == shell ]]; then docker build -f "$repo/containers/Dockerfile.shell" -t "$image" "$repo/containers";
  else docker pull "$image"; fi
  if [[ $language == java ]]; then
    docker run --rm --pull never -v "$repo:/src:ro" -v "$cache:/cache" -w /src "$image" \
      mvn -q -f java/pom.xml -Dmaven.repo.local=/cache/maven dependency:resolve
  fi
  exit
fi
docker image inspect "$image" >/dev/null 2>&1 || { echo "Run bash containers/run.sh $language setup first." >&2; exit 1; }
state=${MDLOGIC_STATE_DIR:-$repo/.local/$language-container}; mkdir -p "$state"; state=$(cd -- "$state" && pwd)
network=${MDLOGIC_CONTAINER_NETWORK:-bridge}
[[ $network == bridge || $network == host ]] || { echo 'Container network must be bridge or host.' >&2; exit 2; }
args=(run --rm --init --label markdownlogic.examples=local --pull never --user "$(id -u):$(id -g)" --network "$network" -w /src -v "$repo:/src:ro" -v "$state:$state" -v "$cache:/cache"
  -e "MDLOGIC_STATE_DIR=$state" -e PYTHONDONTWRITEBYTECODE=1)
for name in MDLOGIC_API_ORIGIN MDLOGIC_OAUTH_ISSUER MDLOGIC_TOKEN MDLOGIC_CLIENT_ID MDLOGIC_CLIENT_SECRET MDLOGIC_TEAM MDLOGIC_WEBHOOK_URL MDLOGIC_WEBHOOK_SECRET PORT; do args+=(-e "$name"); done
if [[ -n ${MDLOGIC_INPUT:-} ]]; then
  input=$(cd -- "$(dirname -- "$MDLOGIC_INPUT")" && pwd)/$(basename -- "$MDLOGIC_INPUT")
  args+=(-v "$input:$input:ro" -e "MDLOGIC_INPUT=$input")
fi
if [[ ${1:-} == webhook ]]; then
  if [[ $network == bridge ]]; then
    # Bind all interfaces INSIDE the container, expose only host loopback.
    args+=(-e MDLOGIC_WEBHOOK_BIND=0.0.0.0 -p "127.0.0.1:${PORT:-8080}:${PORT:-8080}")
  fi
fi
if [[ $language == java ]]; then args+=(--entrypoint ""); fi
case "$language" in
  node) command=(node node/run.mjs "$@");;
  python) command=(python3 python/run.py "$@");;
  shell) command=(bash shell/run.sh "$@");;
  go) command=(bash -c 'set -euo pipefail; cd go; export GOCACHE=/cache/build GOMODCACHE=/cache/modules; go build -o /tmp/example .; cd /src; exec /tmp/example "$@"' -- "$@");;
  java) command=(bash -c 'set -euo pipefail; jar=/cache/maven/com/google/code/gson/gson/2.13.2/gson-2.13.2.jar; mkdir -p /tmp/classes; javac --release 17 --add-modules jdk.httpserver -cp "$jar" -d /tmp/classes java/ReportExamples.java; exec java -Djava.net.preferIPv4Stack=true --add-modules jdk.httpserver -cp "/tmp/classes:$jar" ReportExamples "$@"' -- "$@");;
esac
exec docker "${args[@]}" "$image" "${command[@]}"
