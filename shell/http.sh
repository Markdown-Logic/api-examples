#!/usr/bin/env bash
# Bounded curl transport and credential setup. Source from run.sh.

config_escape() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '%s' "$value"
}

# One complete request, including its response body, has a 15-second deadline.
# Config on stdin keeps bearer credentials out of process arguments. --disable
# must be first: a user's .curlrc must not enable redirects or unsafe retries.
perform() {
  local method=$1 url=$2 body=${3:-} auth=${4:-yes} kind=${5:-application/json}
  local arguments=(--silent --show-error --request "$method" --max-time 15 --connect-timeout 5
    --proto '=https,http' --max-redirs 0 --dump-header "$HEADERS" --output "$RESPONSE"
    --header "Content-Type: $kind" --write-out '%{http_code}')

  if [[ -n $body ]]; then
    arguments+=(--data-binary "@$body")
  fi

  {
    printf 'url = "%s"\n' "$(config_escape "$url")"
    if [[ $auth == yes ]]; then
      printf 'header = "Authorization: Bearer %s"\n' "$(config_escape "$TOKEN")"
    fi
  } | curl --disable --config - "${arguments[@]}" 2>"$WORK/curl-error"
}

# curl may record more than one response header block; use the final value.
response_header() {
  local name=$1
  awk -v name="$name" '
    tolower($0) ~ "^" name ":" {
      sub(/^[^:]*:[[:space:]]*/, "")
      sub(/\r$/, "")
      value = $0
    }
    END { print value }
  ' "$HEADERS"
}

# Validate the fields a task needs without printing raw response diagnostics.
# A malformed success body does not prove a mutation failed; keep its journal.
response_text() {
  local filter=$1 label=$2 file=${3:-$RESPONSE} value
  if ! value=$(jq -er "$filter | select(type==\"string\" and length>0)" "$file" 2>/dev/null); then
    echo "Response is missing a valid $label. Keep pending files and reconcile any uncertain write." >&2
    exit 1
  fi
  printf '%s' "$value"
}

# Emit bounded identifiers for support, never raw server text or document input.
fail_response() {
  local status=$1 code reason request_id
  code=$(jq -r '
    (.code // "HTTP_ERROR") |
    if type=="string" and test("^[A-Z0-9_]{1,80}$") then . else "HTTP_ERROR" end
  ' "$RESPONSE" 2>/dev/null) || code=HTTP_ERROR
  reason=$(jq -r '
    (.details.reason // "") |
    if type=="string" and test("^[a-zA-Z0-9_-]{1,100}$") then . else "" end
  ' "$RESPONSE" 2>/dev/null) || reason=''
  request_id=$(response_header x-request-id)

  if [[ -z $request_id ]]; then
    request_id=$(jq -r '.requestId // empty' "$RESPONSE" 2>/dev/null) || request_id=''
  fi
  if [[ $request_id =~ ^[A-Za-z0-9_-]{1,128}$ ]]; then
    printf 'requestId=%s\n' "$request_id" >&2
  fi
  printf 'HTTP %s %s %s\n' "$status" "$code" "$reason" >&2

  case "$status" in
    423)
      echo 'Keep the generated input. Wait for conversion, review current document state, then deliberately retry.' >&2
      ;;
    401)
      echo 'Authentication refused. Reconnect with current authorized credentials; no automatic refresh or replay.' >&2
      ;;
    409)
      echo 'Conflict: review current content and revision before deciding on a new write.' >&2
      ;;
    429)
      echo 'Rate limit reached. Stop and retry deliberately later; writes are never automatically repeated.' >&2
      ;;
  esac
  exit 1
}

# Only reads may retry, and only after 429. Mutations have no automatic replay:
# neither a connection loss nor a timeout tells us whether the server committed.
request() {
  local method=$1 path=$2 body=${3:-} status attempt=1 wait retry_after
  while :; do
    if ! status=$(perform "$method" "$API$path" "$body"); then
      echo 'Transport failed; a write outcome may be uncertain. Reconcile the saved mapping before repeating.' >&2
      exit 1
    fi
    if [[ $status =~ ^2[0-9][0-9]$ ]]; then
      return
    fi
    if [[ $method != GET || $status != 429 || $attempt -ge 3 ]]; then
      fail_response "$status"
    fi

    retry_after=$(response_header retry-after)
    if ! wait=$(python3 "$HERE/helpers.py" wait "$retry_after" "$attempt"); then
      echo 'Rate limit wait exceeds this example’s budget; try later.' >&2
      exit 1
    fi
    sleep "$wait"
    attempt=$((attempt + 1))
  done
}

authenticate() {
  TOKEN=${MDLOGIC_TOKEN:-}
  if [[ -z $TOKEN ]]; then
    : "${MDLOGIC_CLIENT_ID:?Set MDLOGIC_TOKEN or MDLOGIC_CLIENT_ID and MDLOGIC_CLIENT_SECRET}"
    : "${MDLOGIC_CLIENT_SECRET:?Set MDLOGIC_CLIENT_SECRET}"
    local issuer status
    issuer=$(python3 "$HERE/helpers.py" origin "${MDLOGIC_OAUTH_ISSUER:-https://auth.markdownlogic.com}")
    python3 "$HERE/helpers.py" form > "$WORK/form"

    if ! status=$(perform POST "$issuer/oauth/token" "$WORK/form" no application/x-www-form-urlencoded); then
      echo 'Token exchange transport failure; no retry.' >&2
      exit 1
    fi
    if [[ ! $status =~ ^2[0-9][0-9]$ ]]; then
      echo "Token exchange refused (HTTP $status). Check authorized credentials." >&2
      exit 1
    fi
    TOKEN=$(response_text '.access_token' 'access token')
  fi

  if [[ $TOKEN == *$'\r'* || $TOKEN == *$'\n'* ]]; then
    echo 'Invalid token.' >&2
    exit 2
  fi
}
