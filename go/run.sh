#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
umask 077
mkdir -p "$repo/.local/bin" "$repo/.local/go-build-cache"
export GOCACHE=${GOCACHE:-"$repo/.local/go-build-cache"}
(cd "$repo/go" && go build -o "$repo/.local/bin/go-example" .)
cd "$repo"
exec "$repo/.local/bin/go-example" "$@"
