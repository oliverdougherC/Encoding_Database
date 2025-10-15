#!/bin/sh

set -e

# Simple helper to run the frontend against mock data for quick UI testing.
# Usage: scripts/dev_frontend.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo "[dev] Starting frontend in mock-data mode..."
echo "[dev] Tip: Unset INTERNAL_API_BASE_URL to force Next.js to use /api/query mock endpoint."

cd "$FRONTEND_DIR"

if [ ! -d node_modules ]; then
  echo "[dev] Installing dependencies..."
  npm ci
fi

PORT=${PORT:-3000}
echo "[dev] Running next dev on http://localhost:$PORT"
echo "[dev] Opening browser..."

# Open the browser in the background (macOS/darwin)
if command -v open >/dev/null 2>&1; then
  open "http://localhost:$PORT" || true
fi

npm run dev -- --port "$PORT"


