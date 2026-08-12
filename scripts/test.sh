#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$SCRIPT_DIR/client" && -d "$SCRIPT_DIR/server" && -d "$SCRIPT_DIR/frontend" ]]; then
  ROOT_DIR="$SCRIPT_DIR"
else
  ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-encodingdb_test}"
export COMPOSE_PROJECT_NAME

SERVER_PORT="${SERVER_PORT:-3001}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"
PG_USER="${POSTGRES_USER:-app}"
PG_PASS="${POSTGRES_PASSWORD:-app}"
DB_NAME="${LOCAL_TEST_DATABASE:-benchmarks_test}"
PG_PORT="${POSTGRES_PORT:-55432}"
export POSTGRES_PORT="$PG_PORT"
DATABASE_URL_LOCAL="postgresql://${PG_USER}:${PG_PASS}@127.0.0.1:${PG_PORT}/${DB_NAME}?schema=public"
KEEP_DB=0

REPORT_BASE="${REPORT_BASE:-$ROOT_DIR/.test-reports}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$REPORT_BASE/$RUN_ID"

SERVER_PID=""
FRONTEND_PID=""
OVERALL=0 # 0=pass, 1=warn, 2=fail
LAST_STATUS=""

declare -a STEP_NAMES=()
declare -a STEP_STATUS=()
declare -a STEP_LOGS=()
declare -a STEP_NOTES=()

usage() {
  cat <<EOF
Usage: ./test.sh [--keep-db] [--help]

Options:
  --keep-db   Keep database container running after tests.
  --help      Show this help text.

Environment overrides:
  SERVER_PORT, FRONTEND_PORT, LOCAL_TEST_DATABASE, POSTGRES_PORT, COMPOSE_FILE, REPORT_BASE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-db) KEEP_DB=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "[test] Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

mkdir -p "$RUN_DIR"

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-*//; s/-*$//'
}

update_overall() {
  local status="$1"
  if [[ "$status" == "FAIL" || "$status" == "BLOCKED" ]]; then
    OVERALL=2
    return
  fi
  if [[ "$status" == "WARN" && "$OVERALL" -lt 2 ]]; then
    OVERALL=1
  fi
}

record_step() {
  local name="$1"
  local status="$2"
  local log="$3"
  local note="$4"
  STEP_NAMES+=("$name")
  STEP_STATUS+=("$status")
  STEP_LOGS+=("$log")
  STEP_NOTES+=("$note")
  LAST_STATUS="$status"
  update_overall "$status"
}

issue_scan() {
  local input_log="$1"
  local output_log="$2"
  local raw_log="${output_log}.raw"
  local scan_log="${output_log}.scan"
  : > "$output_log"
  : > "$raw_log"
  : > "$scan_log"

  # Scan only command output; exclude our injected command line header.
  if command -v rg >/dev/null 2>&1; then
    rg -n -v -e '^\[command\]' "$input_log" > "$scan_log" || true
  else
    grep -Env '^\[command\]' "$input_log" > "$scan_log" || true
  fi

  local pattern='(^|[^[:alnum:]_])(warn|warning|deprecated|error|failed|failure|fail|vulnerability|vulnerabilities)([^[:alnum:]_]|$)'
  if command -v rg >/dev/null 2>&1; then
    rg -n -i -e "$pattern" "$scan_log" > "$raw_log" || true
  else
    grep -Ein "$pattern" "$scan_log" > "$raw_log" || true
  fi

  local ignore='0 warnings?|no warnings?|0 errors?|no errors?|without warnings?|without errors?|found 0 vulnerabilities|#[[:space:]]*subtest:|(^|:)ok [0-9]+ -|fail[[:space:]]*[:=]?[[:space:]]*0([^0-9]|$)|failed[[:space:]]*[:=]?[[:space:]]*0([^0-9]|$)|failures?[[:space:]]*[:=]?[[:space:]]*0([^0-9]|$)'
  if command -v rg >/dev/null 2>&1; then
    rg -n -v -i -e "$ignore" "$raw_log" > "$output_log" || true
  else
    grep -Eiv "$ignore" "$raw_log" > "$output_log" || true
  fi
}

mark_blocked() {
  local name="$1"
  local reason="$2"
  local idx="$(( ${#STEP_NAMES[@]} + 1 ))"
  local slug
  slug="$(slugify "$name")"
  local log="$RUN_DIR/$(printf '%02d' "$idx")-${slug}.log"
  {
    echo "BLOCKED: $reason"
  } > "$log"
  record_step "$name" "BLOCKED" "$log" "$reason"
  printf '[%02d] BLOCKED: %s (%s)\n' "$idx" "$name" "$reason"
}

run_step() {
  local name="$1"
  local command="$2"

  local idx="$(( ${#STEP_NAMES[@]} + 1 ))"
  local slug
  slug="$(slugify "$name")"
  local log="$RUN_DIR/$(printf '%02d' "$idx")-${slug}.log"
  local issues="${log}.issues"

  printf '[%02d] RUN: %s\n' "$idx" "$name"
  {
    echo "[command] $command"
    echo
  } > "$log"

  local rc=0
  bash -lc "cd \"$ROOT_DIR\" && $command" >> "$log" 2>&1 || rc=$?
  issue_scan "$log" "$issues"

  local note=""
  if [[ "$rc" -ne 0 ]]; then
    note="exit=$rc"
    if [[ -s "$issues" ]]; then
      note="$note; issue=$(head -n 1 "$issues" | tr -d '\r' | cut -c1-180)"
    fi
    record_step "$name" "FAIL" "$log" "$note"
    printf '[%02d] FAIL: %s (%s)\n' "$idx" "$name" "$note"
    return "$rc"
  fi

  if [[ -s "$issues" ]]; then
    note="warnings detected; first=$(head -n 1 "$issues" | tr -d '\r' | cut -c1-180)"
    record_step "$name" "WARN" "$log" "$note"
    printf '[%02d] WARN: %s (%s)\n' "$idx" "$name" "$note"
    return 0
  fi

  record_step "$name" "PASS" "$log" "ok"
  printf '[%02d] PASS: %s\n' "$idx" "$name"
  return 0
}

start_server() {
  local idx="$(( ${#STEP_NAMES[@]} + 1 ))"
  local name="Server start and readiness"
  local slug
  slug="$(slugify "$name")"
  local log="$RUN_DIR/$(printf '%02d' "$idx")-${slug}.log"
  local issues="${log}.issues"
  local ready_url="http://127.0.0.1:${SERVER_PORT}/health/ready"

  printf '[%02d] RUN: %s\n' "$idx" "$name"
  : > "$log"
  if command -v lsof >/dev/null 2>&1; then
    local listeners
    listeners="$(lsof -nP -iTCP:"${SERVER_PORT}" -sTCP:LISTEN | awk 'NR>1 {print $1 "/" $2}' | paste -sd, -)"
    if [[ -n "$listeners" ]]; then
      echo "Port ${SERVER_PORT} already in use by: ${listeners}" >> "$log"
      record_step "$name" "FAIL" "$log" "port ${SERVER_PORT} already in use (${listeners})"
      printf '[%02d] FAIL: %s (port %s in use)\n' "$idx" "$name" "$SERVER_PORT"
      return 1
    fi
  fi
  (
    cd "$ROOT_DIR/server"
    export PORT="$SERVER_PORT" DATABASE_URL="$DATABASE_URL_LOCAL" NODE_ENV=development
    exec node dist/index.js
  ) >> "$log" 2>&1 &
  SERVER_PID=$!

  local rc=0
  for _ in $(seq 1 50); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      rc=1
      break
    fi
    code="$(curl -s -o /dev/null -w '%{http_code}' "$ready_url" 2>/dev/null || true)"
    if [[ "$code" == "200" ]]; then
      rc=0
      break
    fi
    sleep 1
  done

  if [[ "$rc" -eq 0 ]] && ! kill -0 "$SERVER_PID" 2>/dev/null; then
    rc=1
    echo "Server process exited after readiness probe." >> "$log"
  fi

  issue_scan "$log" "$issues"
  if [[ "$rc" -ne 0 ]]; then
    record_step "$name" "FAIL" "$log" "server did not become ready"
    printf '[%02d] FAIL: %s\n' "$idx" "$name"
    return 1
  fi

  if [[ -s "$issues" ]]; then
    local note="warnings detected; first=$(head -n 1 "$issues" | tr -d '\r' | cut -c1-180)"
    record_step "$name" "WARN" "$log" "$note"
    printf '[%02d] WARN: %s (%s)\n' "$idx" "$name" "$note"
    return 0
  fi

  record_step "$name" "PASS" "$log" "ok"
  printf '[%02d] PASS: %s\n' "$idx" "$name"
  return 0
}

start_frontend() {
  local idx="$(( ${#STEP_NAMES[@]} + 1 ))"
  local name="Frontend start and readiness"
  local slug
  slug="$(slugify "$name")"
  local log="$RUN_DIR/$(printf '%02d' "$idx")-${slug}.log"
  local issues="${log}.issues"
  local frontend_url="http://127.0.0.1:${FRONTEND_PORT}/"

  printf '[%02d] RUN: %s\n' "$idx" "$name"
  : > "$log"
  if command -v lsof >/dev/null 2>&1; then
    local listeners
    listeners="$(lsof -nP -iTCP:"${FRONTEND_PORT}" -sTCP:LISTEN | awk 'NR>1 {print $1 "/" $2}' | paste -sd, -)"
    if [[ -n "$listeners" ]]; then
      echo "Port ${FRONTEND_PORT} already in use by: ${listeners}" >> "$log"
      record_step "$name" "FAIL" "$log" "port ${FRONTEND_PORT} already in use (${listeners})"
      printf '[%02d] FAIL: %s (port %s in use)\n' "$idx" "$name" "$FRONTEND_PORT"
      return 1
    fi
  fi
  (
    cd "$ROOT_DIR/frontend"
    unset ENABLE_QUERY_MOCK NEXT_PUBLIC_API_BASE_URL NEXT_PUBLIC_APP_URL
    export PORT="$FRONTEND_PORT"
    export APP_URL="http://127.0.0.1:${FRONTEND_PORT}"
    export INTERNAL_API_BASE_URL="http://127.0.0.1:${SERVER_PORT}"
    exec npm run start
  ) >> "$log" 2>&1 &
  FRONTEND_PID=$!

  local rc=0
  for _ in $(seq 1 50); do
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      rc=1
      break
    fi
    code="$(curl -s -o /dev/null -w '%{http_code}' "$frontend_url" 2>/dev/null || true)"
    if [[ "$code" == "200" || "$code" == "304" ]]; then
      rc=0
      break
    fi
    sleep 1
  done

  if [[ "$rc" -eq 0 ]] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    rc=1
    echo "Frontend process exited after readiness probe." >> "$log"
  fi

  issue_scan "$log" "$issues"
  if [[ "$rc" -ne 0 ]]; then
    record_step "$name" "FAIL" "$log" "frontend did not become ready"
    printf '[%02d] FAIL: %s\n' "$idx" "$name"
    return 1
  fi

  if [[ -s "$issues" ]]; then
    local note="warnings detected; first=$(head -n 1 "$issues" | tr -d '\r' | cut -c1-180)"
    record_step "$name" "WARN" "$log" "$note"
    printf '[%02d] WARN: %s (%s)\n' "$idx" "$name" "$note"
    return 0
  fi

  record_step "$name" "PASS" "$log" "ok"
  printf '[%02d] PASS: %s\n' "$idx" "$name"
  return 0
}

run_v7_api_contract_smoke() {
  local idx="$(( ${#STEP_NAMES[@]} + 1 ))"
  local name="API: PL-v7 suite and evidence routes"
  local slug
  slug="$(slugify "$name")"
  local log="$RUN_DIR/$(printf '%02d' "$idx")-${slug}.log"

  printf '[%02d] RUN: %s\n' "$idx" "$name"
  : > "$log"
  echo "[command] Validate canonical seven-class suite and PL-v7 artifact route guards" >> "$log"

  local rc=0
  curl -fsS "http://127.0.0.1:${SERVER_PORT}/test-videos" \
    | python3 -c 'import json,sys; clips=json.load(sys.stdin); assert len(clips)==7; assert {c["suiteVersion"] for c in clips} == {"encodingdb-test-suite-v1"}; assert len({c["contentClass"] for c in clips})==7; assert all(c["fileName"] != "sample.mp4" for c in clips)' \
    >> "$log" 2>&1 || rc=$?

  local create_code
  create_code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    "http://127.0.0.1:${SERVER_PORT}/v7/benchmark-runs" \
    -H 'Content-Type: application/json' -d '{}')"
  echo "empty v7 run status: $create_code" >> "$log"
  [[ "$create_code" == "400" ]] || rc=1

  local missing_code
  missing_code="$(curl -sS -o /dev/null -w '%{http_code}' \
    "http://127.0.0.1:${SERVER_PORT}/v7/benchmark-runs/not-a-run/artifacts/ENCODED")"
  echo "missing v7 artifact status: $missing_code" >> "$log"
  [[ "$missing_code" == "404" ]] || rc=1

  if [[ "$rc" -eq 0 ]]; then
    record_step "$name" "PASS" "$log" "seven-class suite and immutable evidence routes available"
    printf '[%02d] PASS: %s\n' "$idx" "$name"
    return 0
  fi

  record_step "$name" "FAIL" "$log" "PL-v7 API contract smoke failed"
  printf '[%02d] FAIL: %s\n' "$idx" "$name"
  return 1
}

cleanup() {
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ "$KEEP_DB" -ne 1 ]]; then
    (cd "$ROOT_DIR" && docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1) || true
  fi
}
trap cleanup EXIT

echo "[test] Report directory: $RUN_DIR"
echo "[test] Base URLs: server=http://127.0.0.1:${SERVER_PORT} frontend=http://127.0.0.1:${FRONTEND_PORT}"
echo "[test] Database port: ${PG_PORT}"
echo "[test] Docker project: ${COMPOSE_PROJECT_NAME}"

PRECHECK_OK=1
SERVER_BUILD_OK=1
FRONTEND_BUILD_OK=1
DOCKER_READY_OK=1
SERVER_RUNNING_OK=1

run_step "Precheck: required commands" "command -v bash python3 node npm docker curl >/dev/null"
if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
  PRECHECK_OK=0
fi

run_step "Precheck: key repository paths" "test -f \"$ROOT_DIR/scripts/client_test.sh\" && test -d \"$ROOT_DIR/client\" && test -d \"$ROOT_DIR/server\" && test -d \"$ROOT_DIR/frontend\""
if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
  PRECHECK_OK=0
fi

if [[ "$PRECHECK_OK" -eq 1 ]]; then
  run_step "Client: install test dependencies" "python3 -m pip install --disable-pip-version-check -r \"$ROOT_DIR/client/requirements-ci.txt\""
  run_step "Client: compile Python modules" "PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m compileall client"
  run_step "Client: import core modules" "python3 -c \"import client.config, client.network, client.ffmpeg, client.main\""
  run_step "Client: CLI help and localhost base URL wiring" "BASE_URL=http://127.0.0.1:${SERVER_PORT} scripts/client_test.sh --help"
  run_step "Client: pytest suite" "cd \"$ROOT_DIR/client\" && python3 -m pytest -q"

  run_step "Server: npm ci" "cd \"$ROOT_DIR/server\" && npm ci --no-audit --no-fund"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    SERVER_BUILD_OK=0
  fi
  run_step "Server: prisma generate" "cd \"$ROOT_DIR/server\" && PRISMA_TELEMETRY_DISABLED=1 npx prisma generate"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    SERVER_BUILD_OK=0
  fi
  run_step "Server: build" "cd \"$ROOT_DIR/server\" && npm run build"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    SERVER_BUILD_OK=0
  fi
  run_step "Server: node test suite" "cd \"$ROOT_DIR/server\" && npm test"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    SERVER_BUILD_OK=0
  fi

  run_step "Frontend: npm ci" "cd \"$ROOT_DIR/frontend\" && npm ci --no-audit --no-fund"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    FRONTEND_BUILD_OK=0
  fi
  run_step "Frontend: lint" "cd \"$ROOT_DIR/frontend\" && npm run lint"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    FRONTEND_BUILD_OK=0
  fi
  run_step "Frontend: unit tests" "cd \"$ROOT_DIR/frontend\" && npm test"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    FRONTEND_BUILD_OK=0
  fi
  run_step "Frontend: build" "cd \"$ROOT_DIR/frontend\" && ENABLE_QUERY_MOCK=1 APP_URL=\"http://127.0.0.1:${FRONTEND_PORT}\" npm run build"
  if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
    FRONTEND_BUILD_OK=0
  fi

  if [[ "$SERVER_BUILD_OK" -eq 1 && "$FRONTEND_BUILD_OK" -eq 1 ]]; then
    run_step "Docker: compose config validation" "docker compose -f \"$COMPOSE_FILE\" config -q"
    if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
      DOCKER_READY_OK=0
    fi
    run_step "Docker: daemon reachable" "docker info >/dev/null"
    if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
      DOCKER_READY_OK=0
    fi

    if [[ "$DOCKER_READY_OK" -eq 1 ]]; then
      run_step "Docker: build authoritative analysis image" "docker compose -f \"$COMPOSE_FILE\" build --quiet server"
      if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
        DOCKER_READY_OK=0
      fi
    fi
    if [[ "$DOCKER_READY_OK" -eq 1 ]]; then
      run_step "Docker: authoritative media capability contract" "docker compose -f \"$COMPOSE_FILE\" run --rm --no-deps server sh -c 'ffmpeg -hide_banner -filters 2>/dev/null | grep -Eq \"[[:space:]]libvmaf[[:space:]]\" && ffmpeg -hide_banner -filters 2>/dev/null | grep -Eq \"[[:space:]]xpsnr[[:space:]]\" && ffprobe -version >/dev/null && echo \"e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e  /app/resources/vmaf/vmaf_v1.0.16_3d0h.json\" | sha256sum -c -'"
      if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
        DOCKER_READY_OK=0
      fi
    fi
    if [[ "$DOCKER_READY_OK" -eq 1 ]]; then
      run_step "Database: start container" "docker compose -f \"$COMPOSE_FILE\" up -d db"
      if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
        DOCKER_READY_OK=0
      fi
      if [[ "$DOCKER_READY_OK" -eq 1 ]]; then
        run_step "Database: readiness wait" "for i in \$(seq 1 50); do docker compose -f \"$COMPOSE_FILE\" exec -T db pg_isready -U \"$PG_USER\" -d postgres >/dev/null 2>&1 && exit 0; sleep 2; done; echo 'Database not ready in time' >&2; exit 1"
        if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
          DOCKER_READY_OK=0
        fi
      else
        mark_blocked "Database: readiness wait" "database container failed to start"
      fi

      if [[ "$DOCKER_READY_OK" -eq 1 ]]; then
        run_step "Database: create test database if missing" "docker compose -f \"$COMPOSE_FILE\" exec -T db psql -U \"$PG_USER\" -d postgres -v ON_ERROR_STOP=1 -c \"CREATE DATABASE \\\"$DB_NAME\\\";\" 2>/dev/null || true"
        run_step "Server: migrate deploy" "cd \"$ROOT_DIR/server\" && PRISMA_TELEMETRY_DISABLED=1 DATABASE_URL=\"$DATABASE_URL_LOCAL\" npx prisma migrate deploy"
        if [[ "$LAST_STATUS" == "FAIL" || "$LAST_STATUS" == "BLOCKED" ]]; then
          SERVER_RUNNING_OK=0
        fi
      else
        mark_blocked "Database: create test database if missing" "database did not become ready"
        mark_blocked "Server: migrate deploy" "database did not become ready"
        SERVER_RUNNING_OK=0
      fi

      if [[ "$SERVER_RUNNING_OK" -eq 1 ]]; then
        start_server || SERVER_RUNNING_OK=0
        if [[ "$SERVER_RUNNING_OK" -eq 1 ]]; then
          run_step "API: health live" "curl -fsS \"http://127.0.0.1:${SERVER_PORT}/health/live\" >/dev/null"
          run_step "API: health ready" "curl -fsS \"http://127.0.0.1:${SERVER_PORT}/health/ready\" >/dev/null"
          run_step "API: query returns array" "curl -fsS \"http://127.0.0.1:${SERVER_PORT}/query?limit=5\" | python3 -c \"import json,sys; data=json.load(sys.stdin); assert isinstance(data, list)\""
          run_v7_api_contract_smoke
          run_step "API: submit method guard" "test \"\$(curl -s -o /dev/null -w '%{http_code}' -X GET \"http://127.0.0.1:${SERVER_PORT}/submit\")\" = \"405\""

          start_frontend || true
          run_step "Frontend: homepage response" "code=\$(curl -s -o /dev/null -w '%{http_code}' \"http://127.0.0.1:${FRONTEND_PORT}/\"); test \"\$code\" = \"200\" -o \"\$code\" = \"304\""
          run_step "Frontend: query proxy response" "curl -fsS \"http://127.0.0.1:${FRONTEND_PORT}/api/query?limit=2\" | python3 -c \"import json,sys; data=json.load(sys.stdin); assert isinstance(data, list)\""
          run_step "Frontend: leaderboard response" "code=\$(curl -s -o /dev/null -w '%{http_code}' \"http://127.0.0.1:${FRONTEND_PORT}/leaderboards\"); test \"\$code\" = \"200\" -o \"\$code\" = \"304\""
          run_step "Frontend: hardware response" "code=\$(curl -s -o /dev/null -w '%{http_code}' \"http://127.0.0.1:${FRONTEND_PORT}/hardware\"); test \"\$code\" = \"200\" -o \"\$code\" = \"304\""
        else
          mark_blocked "API and frontend runtime checks" "server failed to start"
        fi
      else
        mark_blocked "API and frontend runtime checks" "database setup or migration failed"
      fi
    else
      mark_blocked "Database and runtime smoke" "docker daemon is unavailable"
      mark_blocked "Frontend runtime smoke" "docker-backed API smoke could not run"
    fi
  else
    if [[ "$SERVER_BUILD_OK" -ne 1 ]]; then
      mark_blocked "Database and runtime smoke" "server build/test pipeline failed earlier"
    fi
    if [[ "$FRONTEND_BUILD_OK" -ne 1 ]]; then
      mark_blocked "Frontend runtime smoke" "frontend build/test pipeline failed earlier"
    fi
  fi
else
  mark_blocked "All functional checks" "precheck failed"
fi

echo
echo "==================== Test Summary ===================="
pass_count=0
warn_count=0
fail_count=0
for i in "${!STEP_NAMES[@]}"; do
  status="${STEP_STATUS[$i]}"
  case "$status" in
    PASS) pass_count=$((pass_count + 1)) ;;
    WARN) warn_count=$((warn_count + 1)) ;;
    FAIL|BLOCKED) fail_count=$((fail_count + 1)) ;;
  esac
  printf '%02d. %-7s %-45s %s\n' "$((i + 1))" "$status" "${STEP_NAMES[$i]}" "${STEP_NOTES[$i]}"
  printf '    log: %s\n' "${STEP_LOGS[$i]}"
done
echo "------------------------------------------------------"
echo "PASS=$pass_count WARN=$warn_count FAIL=$fail_count"
echo "Report directory: $RUN_DIR"

if [[ "$OVERALL" -eq 2 ]]; then
  echo "Overall result: FAIL"
  exit 1
fi
if [[ "$OVERALL" -eq 1 ]]; then
  echo "Overall result: WARN (treated as failure by policy)"
  exit 2
fi
echo "Overall result: PASS"
exit 0
