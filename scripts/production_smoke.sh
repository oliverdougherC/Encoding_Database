#!/usr/bin/env bash
set -Eeuo pipefail

API_BASE_URL="${API_BASE_URL:-}"
APP_URL="${APP_URL:-}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-20}"

usage() {
  cat <<'EOF'
Usage: ./scripts/production_smoke.sh [--api-base-url URL] [--app-url URL]

Environment:
  API_BASE_URL      Base URL for the API, for example https://encodingdb.platinumlabs.dev
  APP_URL           Base URL for the frontend, for example https://encodingdb.platinumlabs.dev
  TIMEOUT_SECONDS   Curl timeout in seconds (default: 20)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-base-url)
      API_BASE_URL="${2:-}"
      shift 2
      ;;
    --app-url)
      APP_URL="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[production-smoke] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  echo "[production-smoke] $*"
}

die() {
  echo "[production-smoke] ERROR: $*" >&2
  exit 1
}

fetch_status() {
  local url="$1"
  curl -fsSL --connect-timeout "$TIMEOUT_SECONDS" --max-time "$TIMEOUT_SECONDS" "$url"
}

assert_json_array() {
  python3 -c '
import json, sys
payload = json.load(sys.stdin)
if not isinstance(payload, list):
    raise SystemExit("response is not a JSON array")
'
}

assert_json_object() {
  python3 -c '
import json, sys
payload = json.load(sys.stdin)
if not isinstance(payload, dict):
    raise SystemExit("response is not a JSON object")
'
}

[[ -n "$API_BASE_URL" ]] || die "API_BASE_URL is required"

api_base="${API_BASE_URL%/}"
log "Checking non-mutating production API surfaces at $api_base"
fetch_status "$api_base/health/live" | assert_json_object
fetch_status "$api_base/health/ready" | assert_json_object
fetch_status "$api_base/health/v7-evidence" | assert_json_object
fetch_status "$api_base/query" | assert_json_array
fetch_status "$api_base/corpus?limit=5" | assert_json_array
fetch_status "$api_base/test-videos" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
if not isinstance(payload, list) or len(payload) != 7:
    raise SystemExit("test-video catalog must contain exactly seven entries")
'

if [[ -n "$APP_URL" ]]; then
  app_base="${APP_URL%/}"
  log "Checking frontend at $app_base"
  homepage="$(curl -fsSL --connect-timeout "$TIMEOUT_SECONDS" --max-time "$TIMEOUT_SECONDS" "$app_base/")"
  grep -qi "Encoding Database" <<<"$homepage" || die "frontend homepage did not contain Encoding Database"
  fetch_status "$app_base/api/corpus?limit=5" | assert_json_array
  methodology="$(curl -fsSL --connect-timeout "$TIMEOUT_SECONDS" --max-time "$TIMEOUT_SECONDS" "$app_base/methodology")"
  grep -qi "methodology" <<<"$methodology" || die "frontend methodology page did not contain methodology"
fi

log "Production smoke checks passed"
