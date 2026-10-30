#!/usr/bin/env bash
# Six comparable report tasks. HTTP and private-file details live in helpers.

# 01: Map a newly created project before doing any later reads or updates.
create_project() {
  : "${MDLOGIC_TEAM:?Set MDLOGIC_TEAM to a team you may manage}"
  if jq -e '.projectId' "$STATE" >/dev/null; then
    echo 'Project already mapped. Reuse it; do not create a duplicate.' >&2
    exit 1
  fi

  local team project
  team=$(segment "$MDLOGIC_TEAM")
  printf '{"name":"Report integration example","mode":"document"}' > "$WORK/body"
  mark_pending pending-01.json "/api/v1/teams/$team/projects"
  request POST "/api/v1/teams/$team/projects" "$WORK/body"
  project=$(response_text '.project.id' 'project ID')
  save_state --arg id "$project" '.projectId=$id'
  rm "$STATE_DIR/pending-01.json"

  request GET "/api/v1/teams/$team/projects?limit=50&offset=0"
  printf '{"name":"Report integration example"}' > "$WORK/body"
  request PATCH "/api/v1/projects/$(segment "$project")" "$WORK/body"
  jq -n --arg id "$project" '{scenario:"01",projectId:$id}'
}

# 02: Create once and save the stable document ID. A name is not a mapping.
create_report() {
  local base input document revision
  base=$(project_path)
  if jq -e '.documentId' "$STATE" >/dev/null; then
    echo 'Document already mapped. Use scenario 03.' >&2
    exit 1
  fi

  input=${MDLOGIC_INPUT:-fixtures/report.md}
  python3 "$HERE/helpers.py" input "$input"
  # --rawfile preserves the complete UTF-8 content, including trailing newlines.
  jq -n --rawfile content "$input" \
    '{name:"report.md",content:$content,format:"markdown",ifNotExists:true}' > "$WORK/body"
  mark_pending pending-02.json "$base/artifacts"
  request POST "$base/artifacts" "$WORK/body"

  document=$(response_text '.artifact.id' 'document ID')
  revision=$(response_text '.artifact.revision' 'document revision')
  save_state --arg id "$document" --arg revision "$revision" '.documentId=$id|.revision=$revision'
  rm "$STATE_DIR/pending-02.json"
  jq -n --arg id "$document" '{scenario:"02",documentId:$id}'
}

# 03: Read the live revision and submit that exact guard with the replacement.
# An application should review/merge current content before authorizing this PUT.
refresh_report() {
  local doc document input revision
  doc=$(document_path)
  document=$(required_state documentId)
  input=${MDLOGIC_INPUT:-fixtures/report-updated.md}
  python3 "$HERE/helpers.py" input "$input"

  request GET "$doc"
  revision=$(response_text '.document.revision' 'document revision')
  jq -n --rawfile content "$input" --arg revision "$revision" \
    '{content:$content,expectedRevision:$revision,changeNote:"Refresh generated report"}' > "$WORK/body"
  request PUT "$doc" "$WORK/body"

  revision=$(response_text '.document.revision' 'document revision')
  save_state --arg revision "$revision" '.revision=$revision'
  jq -n --arg id "$document" '{scenario:"03",documentId:$id}'
}

# 04: Inspect one bounded history page, then explicitly export the live report.
export_report() {
  local doc has_more version
  doc=$(document_path)
  request GET "$doc/versions?limit=20&offset=0"
  if ! jq -e '(.items | type=="array") and (.hasMore | type=="boolean")' "$RESPONSE" >/dev/null 2>&1; then
    echo 'Malformed history page; export stopped.' >&2
    exit 1
  fi

  has_more=$(jq '.hasMore // false' "$RESPONSE")
  if jq -e '.items | length > 0' "$RESPONSE" >/dev/null 2>&1; then
    version=$(response_text '.items[0].id' 'history snapshot ID')
    request GET "$doc/versions/$(segment "$version")"
  fi
  request GET "$doc/renders/html"
  mv "$RESPONSE" "$STATE_DIR/report.html"
  jq -n --arg file "$STATE_DIR/report.html" --argjson more "$has_more" \
    '{scenario:"04",exportFile:$file,hasMore:$more}'
}

# 05: Sharing is a separate explicit task. The response contains a private URL.
share_report() {
  local doc id
  doc=$(document_path)
  if [[ -f $STATE_DIR/share.json ]]; then
    echo 'Share already saved; review it before creating another.' >&2
    exit 1
  fi

  printf '{"expiresInDays":30}' > "$WORK/body"
  mark_pending pending-05.json "$doc/shares"
  request POST "$doc/shares" "$WORK/body"
  # Retain even a malformed response for reconciliation before clearing intent.
  mv "$RESPONSE" "$STATE_DIR/share.json"
  id=$(response_text '.share.id' 'share ID' "$STATE_DIR/share.json")
  response_text '.share.url' 'share URL' "$STATE_DIR/share.json" >/dev/null
  rm "$STATE_DIR/pending-05.json"
  jq -n --arg id "$id" --arg file "$STATE_DIR/share.json" \
    '{scenario:"05",shareId:$id,shareFile:$file}'
}

# 06: Owner/admin setup subscribes only to events published by this deployment.
register_webhook() {
  : "${MDLOGIC_TEAM:?Set MDLOGIC_TEAM}"
  : "${MDLOGIC_WEBHOOK_URL:?Set MDLOGIC_WEBHOOK_URL to your public HTTPS receiver}"
  if [[ $MDLOGIC_WEBHOOK_URL != https://* || $MDLOGIC_WEBHOOK_URL == *$'\n'* || $MDLOGIC_WEBHOOK_URL == *$'\r'* ]]; then
    echo 'Webhook destination must use HTTPS.' >&2
    exit 2
  fi
  if [[ -f $STATE_DIR/webhook.json ]]; then
    echo 'Webhook already saved. Reuse or explicitly rotate it.' >&2
    exit 1
  fi

  local events path id
  events='["document.created","document.updated","project.created","project.updated","share.created"]'
  request GET /api/v1/webhooks/events
  if ! jq -e --argjson wanted "$events" '(.events | type=="array") and (($wanted - .events) | length==0)' "$RESPONSE" >/dev/null 2>&1; then
    echo 'Server event catalogue does not support the expected lifecycle events.' >&2
    exit 1
  fi

  jq -n --arg url "$MDLOGIC_WEBHOOK_URL" --argjson events "$events" \
    '{url:$url,events:$events,description:"Generated report lifecycle"}' > "$WORK/body"
  path="/api/v1/teams/$(segment "$MDLOGIC_TEAM")/webhooks"
  mark_pending pending-06.json "$path"
  request POST "$path" "$WORK/body"
  mv "$RESPONSE" "$STATE_DIR/webhook.json"
  id=$(response_text '.webhook.id' 'webhook ID' "$STATE_DIR/webhook.json")
  response_text '.secret' 'signing secret' "$STATE_DIR/webhook.json" >/dev/null
  rm "$STATE_DIR/pending-06.json"
  jq -n --arg id "$id" --arg file "$STATE_DIR/webhook.json" \
    '{scenario:"06",webhookId:$id,secretFile:$file}'
}
