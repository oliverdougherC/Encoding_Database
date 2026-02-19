#!/usr/bin/env bash
# Local testing script: spin up DB, server, and frontend with verbose logging.
# Similar to redploy.sh but for local development (no git pull, no prod compose).
# Usage: ./scripts/local_test.sh [--no-frontend] [--no-client-check] [--keep]
# Env: LOCAL_TEST_DATABASE defaults to benchmarks_test so migrations run against a
#      clean DB (avoids "failed migration" state in your main benchmarks DB).
#      Set LOCAL_TEST_DATABASE=benchmarks to use the main DB instead.
#      SEED_DUMMY_BENCHMARKS defaults to 1 here so local testing has sample data.
#      SEED_DUMMY_BENCHMARKS_COUNT controls row count (default: 480).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR}"
SERVER_LOG="$LOG_DIR/.local_test_server.log"
FRONTEND_LOG="$LOG_DIR/.local_test_frontend.log"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
SERVER_PORT="${PORT:-3001}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
PG_USER="${POSTGRES_USER:-app}"
PG_PASS="${POSTGRES_PASSWORD:-app}"
# Default to a separate DB so we never touch a production/failed-migration state
DB_NAME="${LOCAL_TEST_DATABASE:-benchmarks_test}"
DATABASE_URL_LOCAL="postgresql://${PG_USER}:${PG_PASS}@127.0.0.1:5432/${DB_NAME}?schema=public"
SEED_DUMMY_BENCHMARKS="${SEED_DUMMY_BENCHMARKS:-1}"
SEED_DUMMY_BENCHMARKS_COUNT="${SEED_DUMMY_BENCHMARKS_COUNT:-480}"

# --- Options ---
NO_FRONTEND=0
NO_CLIENT_CHECK=0
KEEP_DB=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-frontend) NO_FRONTEND=1; shift ;;
    --no-client-check) NO_CLIENT_CHECK=1; shift ;;
    --keep) KEEP_DB=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--no-frontend] [--no-client-check] [--keep]"
      echo "  --no-frontend     Only start DB and server (no Next.js frontend)."
      echo "  --no-client-check Skip final health/query checks."
      echo "  --keep            Do not stop DB on exit (docker compose down skipped)."
      echo ""
      echo "Env: LOCAL_TEST_DATABASE  Database name (default: benchmarks_test). Use a separate"
      echo "     DB so migrations always run clean. Set to 'benchmarks' to use the main DB."
      echo "     SEED_DUMMY_BENCHMARKS       Seed synthetic benchmark rows after migration"
      echo "                                 (default: 1 for local test only)."
      echo "     SEED_DUMMY_BENCHMARKS_COUNT Number of synthetic rows to insert (default: 480)."
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

# --- Logging helpers ---
log()   { echo "[local_test] $*"; }
logerr() { echo "[local_test] ERROR: $*" >&2; echo "[local_test] ERROR: $*" >> "$SERVER_LOG" 2>/dev/null; }
die()   { logerr "$1"; exit "${2:-1}"; }
run()   { log "Running: $*"; "$@" || die "Command failed: $*"; }

# --- Cleanup on exit ---
SERVER_PID=""
FRONTEND_PID=""
cleanup() {
  log "Shutting down..."
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    log "Stopping server (PID $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    log "Stopping frontend (PID $FRONTEND_PID)"
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ "$KEEP_DB" -ne 1 ]]; then
    log "Stopping database (docker compose down)"
    (cd "$ROOT_DIR" && docker compose -f "$COMPOSE_FILE" down) 2>/dev/null || true
  else
    log "Keeping database up (--keep). Stop with: cd $ROOT_DIR && docker compose down"
  fi
  log "Done."
}
trap cleanup EXIT

# --- Ensure we're in repo root and have required tools ---
cd "$ROOT_DIR"
log "Repo root: $ROOT_DIR"
log "Logs: server=$SERVER_LOG frontend=$FRONTEND_LOG"

for cmd in docker node npm; do
  command -v "$cmd" >/dev/null 2>&1 || die "Missing required command: $cmd"
done

# --- Ensure server .env for local run ---
SERVER_ENV="$ROOT_DIR/server/.env"
mkdir -p "$(dirname "$SERVER_ENV")"
if [[ ! -f "$SERVER_ENV" ]] || ! grep -q "DATABASE_URL" "$SERVER_ENV" 2>/dev/null; then
  log "Writing server/.env for local testing (DATABASE_URL, NODE_ENV, CORS_ORIGIN)"
  cat > "$SERVER_ENV" <<EOF
# Auto-generated for local_test.sh — do not commit secrets
DATABASE_URL=$DATABASE_URL_LOCAL
NODE_ENV=development
PORT=$SERVER_PORT
CORS_ORIGIN=*
BODY_LIMIT=1mb
RATE_LIMIT_WINDOW_MS=60000
RATE_LIMIT_MAX=300
SUBMIT_RATE_WINDOW_MS=60000
SUBMIT_RATE_MAX=30
EOF
else
  log "Using existing server/.env (ensure DATABASE_URL points to local Postgres for this script)"
  export DATABASE_URL="${DATABASE_URL:-$DATABASE_URL_LOCAL}"
fi

# --- Start Postgres (no warnings: orphan/docker output suppressed) ---
log "Starting database..."
docker compose -f "$COMPOSE_FILE" up -d db >/dev/null 2>&1 || die "docker compose up -d db failed"

log "Waiting for Postgres..."
for i in {1..40}; do
  if docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U "$PG_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    log "Postgres is ready."
    break
  fi
  if [[ $i -eq 40 ]]; then
    logerr "Postgres did not become ready. Last 30 lines of db logs:"
    docker compose -f "$COMPOSE_FILE" logs --tail=30 db >&2
    die "Postgres did not become ready in time."
  fi
  sleep 2
done

# --- Create DB if using non-default name (benchmarks_test for clean migrations) ---
if [[ "$DB_NAME" != "benchmarks" ]]; then
  log "Using database: $DB_NAME (creating if missing)..."
  docker compose -f "$COMPOSE_FILE" exec -T db psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$DB_NAME\";" 2>/dev/null || true
fi

# --- Server: install, build, migrate (quiet: no npm/prisma warnings) ---
STEP_LOG="$LOG_DIR/.local_test_step.log"
log "Installing server dependencies..."
(cd "$ROOT_DIR/server" && npm ci --no-fund --loglevel=error >"$STEP_LOG" 2>&1) || { cat "$STEP_LOG" >&2; die "server: npm ci failed"; }
log "Building server..."
(cd "$ROOT_DIR/server" && npm run build >"$STEP_LOG" 2>&1) || { cat "$STEP_LOG" >&2; die "server: npm run build failed"; }
log "Generating Prisma client..."
(cd "$ROOT_DIR/server" && PRISMA_TELEMETRY_DISABLED=1 npx prisma generate >"$STEP_LOG" 2>&1) || { cat "$STEP_LOG" >&2; die "server: prisma generate failed"; }
log "Applying migrations..."
(cd "$ROOT_DIR/server" && PRISMA_TELEMETRY_DISABLED=1 DATABASE_URL="$DATABASE_URL_LOCAL" npx prisma migrate deploy >"$STEP_LOG" 2>&1) || { cat "$STEP_LOG" >&2; die "server: prisma migrate deploy failed"; }
if [[ "$SEED_DUMMY_BENCHMARKS" == "1" ]]; then
  log "Seeding dummy benchmark data (${SEED_DUMMY_BENCHMARKS_COUNT} rows target)..."
  (cd "$ROOT_DIR/server" && DATABASE_URL="$DATABASE_URL_LOCAL" SEED_DUMMY_BENCHMARKS=1 SEED_DUMMY_BENCHMARKS_COUNT="$SEED_DUMMY_BENCHMARKS_COUNT" node dist/seedDummyDatabase.js >"$STEP_LOG" 2>&1) || { cat "$STEP_LOG" >&2; die "server: dummy benchmark seed failed"; }
else
  log "Skipping dummy benchmark seed (SEED_DUMMY_BENCHMARKS=${SEED_DUMMY_BENCHMARKS})."
fi

log "Starting server on port $SERVER_PORT..."
cd "$ROOT_DIR/server"
: > "$SERVER_LOG"
# Run node in a subshell that ignores SIGHUP then exec's node, so $! is node's PID and node won't exit on SIGHUP
( trap '' HUP; export PORT="$SERVER_PORT" DATABASE_URL="$DATABASE_URL_LOCAL" NODE_ENV=development; exec node dist/index.js >> "$SERVER_LOG" 2>&1 ) &
SERVER_PID=$!
cd "$ROOT_DIR"

# Diagnostic: after 2s report PID liveness and first health/ready response
sleep 2
if kill -0 "$SERVER_PID" 2>/dev/null; then
  log "Diagnostic: PID $SERVER_PID is alive."
else
  log "Diagnostic: PID $SERVER_PID is NOT alive (process already exited)."
fi
CURL_OUT="$(curl -s --connect-timeout 3 --max-time 5 -w '\nHTTP_CODE:%{http_code}' "http://127.0.0.1:$SERVER_PORT/health/ready" 2>/dev/null)" || true
CURL_CODE="${CURL_OUT##*HTTP_CODE:}"
CURL_BODY="${CURL_OUT%HTTP_CODE:*}"
log "Diagnostic: curl /health/ready -> HTTP $CURL_CODE body=${CURL_BODY:0:80}"
if command -v lsof >/dev/null 2>&1; then
  log "Diagnostic: port $SERVER_PORT listeners: $(lsof -i ":$SERVER_PORT" 2>/dev/null | wc -l | tr -d ' ') process(es)"
fi

# Wait for /health/ready with timeout; if server process dies, show log and exit
HEALTH_TIMEOUT=45
log "Waiting for server /health/ready (timeout ${HEALTH_TIMEOUT}s)..."
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    logerr "Server process exited. Last 50 lines of server log:"
    tail -n 50 "$SERVER_LOG" >&2
    die "Server process died before becoming ready."
  fi
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$SERVER_PORT/health/ready" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    log "Server is ready."
    break
  fi
  if [[ $i -eq $HEALTH_TIMEOUT ]]; then
    logerr "Server did not become ready within ${HEALTH_TIMEOUT}s (last check: HTTP $code). Last 50 lines of server log:"
    tail -n 50 "$SERVER_LOG" >&2
    die "Server /health/ready failed (timeout)."
  fi
  sleep 1
done

# --- Frontend (optional) ---
if [[ $NO_FRONTEND -eq 0 ]]; then
  FRONTEND_ENV="$ROOT_DIR/frontend/.env.local"
  log "Ensuring frontend .env.local (INTERNAL_API_BASE_URL)..."
  echo "INTERNAL_API_BASE_URL=http://127.0.0.1:$SERVER_PORT" > "$FRONTEND_ENV"

  log "Installing frontend dependencies..."
  (cd "$ROOT_DIR/frontend" && npm ci --no-fund --loglevel=error >"$STEP_LOG" 2>&1) || { cat "$STEP_LOG" >&2; die "frontend: npm ci failed"; }
  log "Starting frontend on port $FRONTEND_PORT (logs: $FRONTEND_LOG)"
  : > "$FRONTEND_LOG"
  (cd "$ROOT_DIR/frontend" && PORT="$FRONTEND_PORT" npm run dev >> "$FRONTEND_LOG" 2>&1) &
  FRONTEND_PID=$!

  log "Waiting for frontend to listen..."
  for i in {1..25}; do
    if curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$FRONTEND_PORT/" 2>/dev/null | grep -q '200\|304'; then
      log "Frontend is up (http://127.0.0.1:$FRONTEND_PORT)."
      break
    fi
    if [[ $i -eq 25 ]]; then
      logerr "Frontend may still be starting. Last 30 lines:"
      tail -n 30 "$FRONTEND_LOG" >&2
    fi
    sleep 2
  done
fi

# --- Optional client/health checks ---
if [[ $NO_CLIENT_CHECK -eq 0 ]]; then
  log "Checking /health/live and /query..."
  code_live="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$SERVER_PORT/health/live")"
  code_query="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$SERVER_PORT/query")"
  if [[ "$code_live" != "200" ]]; then
    die "/health/live returned HTTP $code_live"
  fi
  if [[ "$code_query" != "200" ]]; then
    die "/query returned HTTP $code_query"
  fi
  log "Health and query checks passed."
fi

# --- Summary ---
log "=========================================="
log "Local stack is up."
log "  Backend:  http://127.0.0.1:$SERVER_PORT  (logs: $SERVER_LOG)"
if [[ $NO_FRONTEND -eq 0 ]]; then
  log "  Frontend: http://127.0.0.1:$FRONTEND_PORT (logs: $FRONTEND_LOG)"
fi
log "  DB:       postgresql://${PG_USER}:****@127.0.0.1:5432/${DB_NAME}"
log "Press Ctrl+C to stop server and frontend."
log "=========================================="
wait $SERVER_PID 2>/dev/null || true
