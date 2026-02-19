#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_PORT="${SERVER_PORT:-3001}"
LOCAL_BASE_URL="${BASE_URL:-http://127.0.0.1:${SERVER_PORT}}"

cd "$ROOT_DIR"

if command -v python3 >/dev/null 2>&1; then
  exec env BACKEND_BASE_URL="$LOCAL_BASE_URL" python3 -m client --base-url "$LOCAL_BASE_URL" "$@"
fi

if command -v python >/dev/null 2>&1; then
  exec env BACKEND_BASE_URL="$LOCAL_BASE_URL" python -m client --base-url "$LOCAL_BASE_URL" "$@"
fi

echo "[client_test] ERROR: Python not found in PATH." >&2
exit 1
