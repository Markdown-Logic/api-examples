#!/usr/bin/env bash
# Run from the repository root. curl makes HTTP calls; jq builds JSON safely.
set -euo pipefail
umask 077
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
scenario=${1:-}
if [[ $scenario == webhook ]]; then exec python3 "$HERE/webhook.py"; fi
case "$scenario" in 01|02|03|04|05|06) ;; *) echo 'Usage: bash shell/run.sh 01|02|03|04|05|06|webhook' >&2; exit 2;; esac
for tool in curl jq python3; do command -v "$tool" >/dev/null || { echo "Required: $tool" >&2; exit 2; }; done
STATE_DIR=${MDLOGIC_STATE_DIR:-.local/shell}
mkdir -p "$STATE_DIR"; chmod 700 "$STATE_DIR"
WORK=$(mktemp -d "$STATE_DIR/.request.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
STATE="$STATE_DIR/state.json"
if [[ -f $STATE ]]; then chmod 600 "$STATE"; else printf '{}\n' > "$STATE"; fi
API=$(python3 "$HERE/helpers.py" origin "${MDLOGIC_API_ORIGIN:-https://api.markdownlogic.com}")
TOKEN=${MDLOGIC_TOKEN:-}
RESPONSE="$WORK/response"; HEADERS="$WORK/headers"
# curl config on stdin keeps the bearer token out of process arguments.
config_escape() { local v=$1; v=${v//\\/\\\\}; v=${v//\"/\\\"}; printf '%s' "$v"; }
perform() {
  local method=$1 url=$2 body=${3:-} auth=${4:-yes} kind=${5:-application/json}
  {
    printf 'url = "%s"\n' "$(config_escape "$url")"
    if [[ $auth == yes ]]; then printf 'header = "Authorization: Bearer %s"\n' "$(config_escape "$TOKEN")"; fi
  } | curl --disable --config - --silent --show-error --request "$method" --max-time 15 --connect-timeout 5 \
      --proto '=https,http' --max-redirs 0 --dump-header "$HEADERS" --output "$RESPONSE" \
      --header "Content-Type: $kind" ${body:+--data-binary "@$body"} --write-out '%{http_code}' 2>"$WORK/curl-error"
}
fail_response() {
  local status=$1 code reason request_id
  code=$(jq -r '(.code // "HTTP_ERROR") | if type=="string" and test("^[A-Z0-9_]{1,80}$") then . else "HTTP_ERROR" end' "$RESPONSE" 2>/dev/null) || code=HTTP_ERROR
  reason=$(jq -r '(.details.reason // "") | if type=="string" and test("^[a-zA-Z0-9_-]{1,100}$") then . else "" end' "$RESPONSE" 2>/dev/null) || reason=''
  request_id=$(awk 'tolower($0) ~ /^x-request-id:/ {sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); value=$0} END {print value}' "$HEADERS")
  if [[ -z $request_id ]]; then request_id=$(jq -r '.requestId // empty' "$RESPONSE" 2>/dev/null) || request_id=''; fi
  if [[ $request_id =~ ^[A-Za-z0-9_-]{1,128}$ ]]; then printf 'requestId=%s\n' "$request_id" >&2; fi
  printf 'HTTP %s %s %s\n' "$status" "$code" "$reason" >&2
  case "$status" in
    423) echo 'Keep the generated input. Wait for conversion, review current document state, then deliberately retry.' >&2;;
    401) echo 'Authentication refused. Reconnect with current authorized credentials; no automatic refresh or replay.' >&2;;
    409) echo 'Conflict: review current content and revision before deciding on a new write.' >&2;;
    429) echo 'Rate limit reached. Stop and retry deliberately later; writes are never automatically repeated.' >&2;;
  esac
  exit 1
}
request() {
  local method=$1 path=$2 body=${3:-} status attempt=1 wait retry_after
  while :; do
    if ! status=$(perform "$method" "$API$path" "$body"); then
      echo 'Transport failed; a write outcome may be uncertain. Reconcile the saved mapping before repeating.' >&2; exit 1
    fi
    if [[ $status =~ ^2[0-9][0-9]$ ]]; then return; fi
    if [[ $method != GET || $status != 429 || $attempt -ge 3 ]]; then fail_response "$status"; fi
    retry_after=$(awk 'tolower($0) ~ /^retry-after:/ {sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); value=$0} END {print value}' "$HEADERS")
    wait=$(python3 "$HERE/helpers.py" wait "$retry_after" "$attempt") || { echo 'Rate limit wait exceeds this example’s budget; try later.' >&2; exit 1; }
    sleep "$wait"; attempt=$((attempt+1))
  done
}
if [[ -z $TOKEN ]]; then
  : "${MDLOGIC_CLIENT_ID:?Set MDLOGIC_TOKEN or MDLOGIC_CLIENT_ID and MDLOGIC_CLIENT_SECRET}"
  : "${MDLOGIC_CLIENT_SECRET:?Set MDLOGIC_CLIENT_SECRET}"
  ISSUER=$(python3 "$HERE/helpers.py" origin "${MDLOGIC_OAUTH_ISSUER:-https://auth.markdownlogic.com}")
  python3 "$HERE/helpers.py" form > "$WORK/form"
  if ! status=$(perform POST "$ISSUER/oauth/token" "$WORK/form" no application/x-www-form-urlencoded); then echo 'Token exchange transport failure; no retry.' >&2; exit 1; fi
  [[ $status =~ ^2[0-9][0-9]$ ]] || { echo "Token exchange refused (HTTP $status). Check authorized credentials." >&2; exit 1; }
  TOKEN=$(jq -er '.access_token | select(type=="string" and length>0)' "$RESPONSE")
fi
[[ $TOKEN != *$'\r'* && $TOKEN != *$'\n'* ]] || { echo 'Invalid token.' >&2; exit 2; }
segment() { jq -rn --arg value "$1" '$value|@uri'; }
required_state() { jq -er --arg k "$1" '.[$k] | select(type=="string" and length>0)' "$STATE" || { echo "Run the earlier scenario to save $1 first." >&2; exit 1; }; }
save_state() { jq "$@" "$STATE" > "$WORK/state"; mv "$WORK/state" "$STATE"; }
mark_pending() {
  local filename=$1 path=$2
  jq -n --arg origin "$API" --arg path "$path" --slurpfile body "$WORK/body" \
    '{apiOrigin:$origin,method:"POST",path:$path,body:$body[0]}' > "$WORK/pending"
  if ! (set -o noclobber; cat "$WORK/pending" > "$STATE_DIR/$filename") 2>/dev/null; then
    echo "Pending creation: reconcile the original target and outcome before removing $filename." >&2; exit 1
  fi
}
if [[ $scenario != 01 && $scenario != 06 ]]; then
  project=$(required_state projectId); base="/api/v1/projects/$(segment "$project")"
  if [[ $scenario != 02 ]]; then document=$(required_state documentId); doc="$base/documents/$(segment "$document")"; fi
fi
case "$scenario" in
01)
  : "${MDLOGIC_TEAM:?Set MDLOGIC_TEAM to a team you may manage}"
  if jq -e '.projectId' "$STATE" >/dev/null; then echo 'Project already mapped. Reuse it; do not create a duplicate.' >&2; exit 1; fi
  printf '{"name":"Report integration example","mode":"document"}' > "$WORK/body"
  team=$(segment "$MDLOGIC_TEAM")
  mark_pending pending-01.json "/api/v1/teams/$team/projects"
  request POST "/api/v1/teams/$team/projects" "$WORK/body"
  project=$(jq -er '.project.id | select(type=="string" and length>0)' "$RESPONSE"); save_state --arg id "$project" '.projectId=$id'
  rm "$STATE_DIR/pending-01.json"
  request GET "/api/v1/teams/$team/projects?limit=50&offset=0"
  printf '{"name":"Report integration example"}' > "$WORK/body"
  request PATCH "/api/v1/projects/$(segment "$project")" "$WORK/body"
  jq -n --arg id "$project" '{scenario:"01",projectId:$id}'
  ;;
02)
  if jq -e '.documentId' "$STATE" >/dev/null; then echo 'Document already mapped. Use scenario03.' >&2; exit 1; fi
  INPUT=${MDLOGIC_INPUT:-fixtures/report.md}
  python3 "$HERE/helpers.py" input "$INPUT"
  jq -n --rawfile content "$INPUT" '{name:"report.md",content:$content,format:"markdown",ifNotExists:true}' > "$WORK/body"
  mark_pending pending-02.json "$base/artifacts"
  request POST "$base/artifacts" "$WORK/body"
  document=$(jq -er '.artifact.id | select(type=="string" and length>0)' "$RESPONSE"); revision=$(jq -er '.artifact.revision | select(type=="string" and length>0)' "$RESPONSE")
  save_state --arg id "$document" --arg revision "$revision" '.documentId=$id|.revision=$revision'
  rm "$STATE_DIR/pending-02.json"
  jq -n --arg id "$document" '{scenario:"02",documentId:$id}'
  ;;
03)
  INPUT=${MDLOGIC_INPUT:-fixtures/report-updated.md}
  python3 "$HERE/helpers.py" input "$INPUT"
  request GET "$doc"
  revision=$(jq -er '.document.revision | select(type=="string" and length>0)' "$RESPONSE")
  jq -n --rawfile content "$INPUT" --arg revision "$revision" '{content:$content,expectedRevision:$revision,changeNote:"Refresh generated report"}' > "$WORK/body"
  request PUT "$doc" "$WORK/body"
  revision=$(jq -er '.document.revision | select(type=="string" and length>0)' "$RESPONSE"); save_state --arg revision "$revision" '.revision=$revision'
  jq -n --arg id "$document" '{scenario:"03",documentId:$id}'
  ;;
04)
  request GET "$doc/versions?limit=20&offset=0"
  jq -e '(.items | type=="array") and (.hasMore | type=="boolean")' "$RESPONSE" >/dev/null || { echo 'Malformed history page; export stopped.' >&2; exit 1; }
  has_more=$(jq '.hasMore // false' "$RESPONSE"); version=$(jq -r '.items[0].id // empty' "$RESPONSE")
  if [[ -n $version ]]; then request GET "$doc/versions/$(segment "$version")"; fi
  request GET "$doc/renders/html"
  mv "$RESPONSE" "$STATE_DIR/report.html"
  jq -n --arg file "$STATE_DIR/report.html" --argjson more "$has_more" '{scenario:"04",exportFile:$file,hasMore:$more}'
  ;;
05)
  if [[ -f $STATE_DIR/share.json ]]; then echo 'Share already saved; review it before creating another.' >&2; exit 1; fi
  printf '{"expiresInDays":30}' > "$WORK/body"
  mark_pending pending-05.json "$doc/shares"
  request POST "$doc/shares" "$WORK/body"
  mv "$RESPONSE" "$STATE_DIR/share.json"
  id=$(jq -er '.share.id | select(type=="string" and length>0)' "$STATE_DIR/share.json")
  jq -e '.share.url | type=="string" and length>0' "$STATE_DIR/share.json" >/dev/null
  rm "$STATE_DIR/pending-05.json"
  jq -n --arg id "$id" --arg file "$STATE_DIR/share.json" '{scenario:"05",shareId:$id,shareFile:$file}'
  ;;
06)
  : "${MDLOGIC_TEAM:?Set MDLOGIC_TEAM}"; : "${MDLOGIC_WEBHOOK_URL:?Set MDLOGIC_WEBHOOK_URL to your public HTTPS receiver}"
  [[ $MDLOGIC_WEBHOOK_URL == https://* && $MDLOGIC_WEBHOOK_URL != *$'\n'* && $MDLOGIC_WEBHOOK_URL != *$'\r'* ]] || { echo 'Webhook destination must use HTTPS.' >&2; exit 2; }
  if [[ -f $STATE_DIR/webhook.json ]]; then echo 'Webhook already saved. Reuse or explicitly rotate it.' >&2; exit 1; fi
  events='["document.created","document.updated","project.created","project.updated","share.created"]'
  request GET /api/v1/webhooks/events
  jq -e --argjson wanted "$events" '(.events | type=="array") and (($wanted - .events) | length==0)' "$RESPONSE" >/dev/null || { echo 'Server event catalogue does not support the expected lifecycle events.' >&2; exit 1; }
  jq -n --arg url "$MDLOGIC_WEBHOOK_URL" --argjson events "$events" '{url:$url,events:$events,description:"Generated report lifecycle"}' > "$WORK/body"
  path="/api/v1/teams/$(segment "$MDLOGIC_TEAM")/webhooks"
  mark_pending pending-06.json "$path"
  request POST "$path" "$WORK/body"
  mv "$RESPONSE" "$STATE_DIR/webhook.json"
  id=$(jq -er '.webhook.id | select(type=="string" and length>0)' "$STATE_DIR/webhook.json"); jq -e '.secret | type=="string" and length>0' "$STATE_DIR/webhook.json" >/dev/null
  rm "$STATE_DIR/pending-06.json"
  jq -n --arg id "$id" --arg file "$STATE_DIR/webhook.json" '{scenario:"06",webhookId:$id,secretFile:$file}'
  ;;
esac
