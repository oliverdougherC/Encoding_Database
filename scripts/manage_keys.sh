#!/usr/bin/env bash
# Usage:
#   ADMIN_TOKEN=... BASE_URL=https://encodingdb.platinumlabs.dev ./scripts/manage_keys.sh create "beta-001" tester@example.com
#   ADMIN_TOKEN=... BASE_URL=https://encodingdb.platinumlabs.dev ./scripts/manage_keys.sh list
#   ADMIN_TOKEN=... BASE_URL=https://encodingdb.platinumlabs.dev ./scripts/manage_keys.sh revoke <id>
#   ADMIN_TOKEN=... BASE_URL=https://encodingdb.platinumlabs.dev ./scripts/manage_keys.sh ban <id>
set -euo pipefail

BASE_URL="${BASE_URL:-https://encodingdb.platinumlabs.dev}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
if [[ -z "$ADMIN_TOKEN" ]]; then
  echo "ADMIN_TOKEN env var required" >&2
  exit 2
fi

cmd="${1:-}"
case "$cmd" in
  create)
    name="${2:-beta}"
    email="${3:-}"
    body="{ \"name\": \"$name\""
    if [[ -n "$email" ]]; then
      body+=" , \"userEmail\": \"$email\""
    fi
    body+=" }"
    curl -sS -X POST "$BASE_URL/admin/api-keys" \
      -H "X-Admin-Token: $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      --data "$body" | jq -r '.'
    ;;
  list)
    curl -sS "$BASE_URL/admin/api-keys" -H "X-Admin-Token: $ADMIN_TOKEN" | jq -r '.'
    ;;
  revoke)
    id="${2:-}"
    if [[ -z "$id" ]]; then echo "id required" >&2; exit 2; fi
    curl -sS -X POST "$BASE_URL/admin/api-keys/$id/revoke" -H "X-Admin-Token: $ADMIN_TOKEN" | jq -r '.'
    ;;
  ban)
    id="${2:-}"
    if [[ -z "$id" ]]; then echo "id required" >&2; exit 2; fi
    curl -sS -X POST "$BASE_URL/admin/api-keys/$id/ban" -H "X-Admin-Token: $ADMIN_TOKEN" | jq -r '.'
    ;;
  *)
    echo "Commands: create <name> [email] | list | revoke <id> | ban <id>" >&2
    exit 2
    ;;
esac
