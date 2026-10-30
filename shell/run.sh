#!/usr/bin/env bash
# Run from the repository root. The dispatcher keeps each report task discoverable.
set -euo pipefail
umask 077

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
scenario=${1:-}

if [[ $scenario == webhook ]]; then
  exec python3 "$HERE/webhook.py"
fi

case "$scenario" in
  01|02|03|04|05|06) ;;
  *)
    echo 'Usage: bash shell/run.sh 01|02|03|04|05|06|webhook' >&2
    exit 2
    ;;
esac

for tool in curl jq python3; do
  if ! command -v "$tool" >/dev/null; then
    echo "Required: $tool" >&2
    exit 2
  fi
done

# Keep transport and recovery rules in helpers shared by the six tasks.
source "$HERE/state.sh"
source "$HERE/http.sh"
source "$HERE/scenarios.sh"

initialize_state
API=$(python3 "$HERE/helpers.py" origin "${MDLOGIC_API_ORIGIN:-https://api.markdownlogic.com}")
authenticate

case "$scenario" in
  01)
    create_project
    ;;
  02)
    create_report
    ;;
  03)
    refresh_report
    ;;
  04)
    export_report
    ;;
  05)
    share_report
    ;;
  06)
    register_webhook
    ;;
esac
