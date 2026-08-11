#!/usr/bin/env bash
# Start the development Docker stack. Unlike deploy.sh, this never pulls from git
# and only uses the local docker-compose.yml configuration.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${TEST_COMPOSE_FILE:-docker-compose.yml}"
SKIP_BUILD=0
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
FRONTEND_LOG="${TEST_FRONTEND_LOG:-$SCRIPT_DIR/.test_frontend.log}"
FRONTEND_PID=""
CLEANING_UP=0

usage() {
  cat <<'EOF'
Usage: ./test.sh [--no-build] [--help]

Starts the local development database, API, and frontend.
It does not fetch code, require production secrets, or touch the production stack.
All services run in the background; press Ctrl+C to stop them.

Options:
  --no-build  Start using existing images without rebuilding.
  --help      Show this help text.

Environment overrides:
  TEST_COMPOSE_FILE=docker-compose.yml
  POSTGRES_PORT=5432
  FRONTEND_PORT=3000
  TEST_FRONTEND_LOG=./.test_frontend.log
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)
      SKIP_BUILD=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[test] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  echo "[test] $*"
}

die() {
  echo "[test] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

wait_for_ready() {
  local elapsed=0
  local timeout=60

  while (( elapsed < timeout )); do
    if curl --silent --fail --max-time 3 \
      "http://127.0.0.1:3001/health/ready" >/dev/null; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  return 1
}

wait_for_frontend() {
  local elapsed=0
  local timeout=60

  while (( elapsed < timeout )); do
    if curl --silent --fail --max-time 3 \
      "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null; then
      return 0
    fi
    if [[ -n "$FRONTEND_PID" ]] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      return 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  return 1
}

cleanup() {
  [[ "$CLEANING_UP" -eq 0 ]] || return
  CLEANING_UP=1

  log "Stopping development services..."
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  docker compose -f "$COMPOSE_FILE" down --remove-orphans || true
}

handle_signal() {
  exit 0
}

cd "$SCRIPT_DIR"

require_cmd docker
require_cmd curl
require_cmd npm
[[ -f "$COMPOSE_FILE" ]] || die "Compose file not found: $COMPOSE_FILE"
[[ -f "frontend/package.json" ]] || die "Frontend package not found."

trap cleanup EXIT
trap handle_signal INT TERM

log "Validating development compose configuration..."
docker compose -f "$COMPOSE_FILE" config -q

if [[ "$SKIP_BUILD" -eq 1 ]]; then
  log "Starting development stack without rebuilding..."
  docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
else
  log "Building and starting development stack..."
  docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans
fi

log "Waiting for the API readiness check..."
if ! wait_for_ready; then
  docker compose -f "$COMPOSE_FILE" logs --tail=120 server || true
  die "API did not become ready within 60 seconds."
fi

if [[ ! -d "frontend/node_modules" ]]; then
  log "Installing frontend dependencies..."
  (cd frontend && npm ci)
fi

log "Starting frontend (logs: $FRONTEND_LOG)..."
(
  cd frontend
  INTERNAL_API_BASE_URL="http://127.0.0.1:3001" \
    APP_URL="http://127.0.0.1:${FRONTEND_PORT}" \
    PORT="$FRONTEND_PORT" \
    exec npm run dev
) >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

log "Waiting for the frontend..."
if ! wait_for_frontend; then
  tail -n 120 "$FRONTEND_LOG" >&2 || true
  die "Frontend did not become ready within 60 seconds."
fi

log "Development stack is ready. Press Ctrl+C to stop it."
log "API: http://127.0.0.1:3001"
log "Frontend: http://127.0.0.1:${FRONTEND_PORT}"
docker compose -f "$COMPOSE_FILE" ps

wait "$FRONTEND_PID"
