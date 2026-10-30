#!/usr/bin/env bash
# Private local files connect separate runs. Source from run.sh; do not execute.

initialize_state() {
  STATE_DIR=${MDLOGIC_STATE_DIR:-.local/shell}
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"

  # A per-run directory isolates transient bodies and OAuth form data.
  WORK=$(mktemp -d "$STATE_DIR/.request.XXXXXX")
  trap 'rm -rf "$WORK"' EXIT
  RESPONSE="$WORK/response"
  HEADERS="$WORK/headers"
  STATE="$STATE_DIR/state.json"

  if [[ -f $STATE ]]; then
    chmod 600 "$STATE"
  else
    printf '{}\n' > "$STATE"
  fi

  # Reject corrupt mappings before authentication or any remote request.
  if ! jq -e -s 'length == 1 and (.[0] | type == "object")' "$STATE" >/dev/null 2>&1; then
    echo 'State file must contain one JSON object. Keep it and review the mapping before continuing.' >&2
    exit 1
  fi
}

# Encode a stable resource ID as one path segment, never as a whole URL.
segment() {
  jq -rn --arg value "$1" '$value|@uri'
}

required_state() {
  if ! jq -er --arg key "$1" '.[$key] | select(type=="string" and length>0)' "$STATE" 2>/dev/null; then
    echo "Run the earlier scenario to save $1 first." >&2
    exit 1
  fi
}

# Replace the mapping only after a complete JSON value has been written.
save_state() {
  jq "$@" "$STATE" > "$WORK/state"
  mv "$WORK/state" "$STATE"
}

project_path() {
  local project
  project=$(required_state projectId) || return 1
  printf '/api/v1/projects/%s' "$(segment "$project")"
}

document_path() {
  local base document
  base=$(project_path) || return 1
  document=$(required_state documentId) || return 1
  printf '%s/documents/%s' "$base" "$(segment "$document")"
}

# Preserve the exact create intent before sending it. A lost response cannot
# prove failure, so a repeat run must reconcile this marker rather than resend.
mark_pending() {
  local filename=$1 path=$2
  jq -n --arg origin "$API" --arg path "$path" --slurpfile body "$WORK/body" \
    '{apiOrigin:$origin,method:"POST",path:$path,body:$body[0]}' > "$WORK/pending"

  # noclobber makes competing local runs refuse an existing marker atomically.
  if ! (
    set -o noclobber
    cat "$WORK/pending" > "$STATE_DIR/$filename"
  ) 2>/dev/null; then
    echo "Pending creation: reconcile the original target and outcome before removing $filename." >&2
    exit 1
  fi
}
