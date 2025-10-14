#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root relative to this script (portable for CI and local)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
COMPOSE="docker compose -f \"$ROOT_DIR/docker-compose.prod.yml\""

# If API_BASE_URL is provided (e.g., in CI), test against it and avoid local stack control
BASE_URL="${API_BASE_URL:-http://localhost:3001}"
CAN_CONTROL_STACK=1
if [[ -n "${API_BASE_URL:-}" ]]; then
  CAN_CONTROL_STACK=0
fi
# Allow mutation tests (POST /submit, outage) on remote only when explicitly opted in
ALLOW_MUTATION_REMOTE="${ALLOW_MUTATION_REMOTE:-0}"

pass() { echo -e "[PASS] $1"; }
fail() { echo -e "[FAIL] $1"; exit 1; }

retry_curl_json() {
  local path="$1"; shift
  for i in {1..90}; do
    if curl -sf "$BASE_URL$path" >/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}

echo "[prep] Ensuring stack is up or reachable"
if [[ "$CAN_CONTROL_STACK" -eq 1 ]]; then
  eval "$COMPOSE up -d >/dev/null"
else
  echo "[prep] Using remote API_BASE_URL=$BASE_URL; skipping docker compose up"
fi

echo "[wait] Waiting for readiness"
if ! retry_curl_json /health/ready; then
  if [[ "$CAN_CONTROL_STACK" -eq 1 ]]; then
    eval "$COMPOSE logs server | tail -n 200" || true
  fi
  fail "Server not ready"
fi

echo "[check] Health endpoints"
curl -sf "$BASE_URL/health/live" >/dev/null || fail "live"
curl -sf "$BASE_URL/health/ready" >/dev/null || fail "ready"
curl -sf "$BASE_URL/health" >/dev/null || fail "health"
pass "health endpoints"

if [[ "$CAN_CONTROL_STACK" -eq 1 || "$ALLOW_MUTATION_REMOTE" == "1" ]]; then
  echo "[check] Validation and coercion"
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" -d '{}')
  [[ "$code" == "400" ]] || fail "invalid payload should 400"
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" -d '{"cpuModel":"CPU","gpuModel":null,"ramGB":"16","os":"macOS","codec":"libx264","preset":"fast","fps":"12.3","fileSizeBytes":"1000"}')
  [[ "$code" == "201" || "$code" == "200" ]] || fail "coercion submit should 201/200"
  pass "validation/coercion"
else
  echo "[skip] Validation/coercion (no stack control and ALLOW_MUTATION_REMOTE!=1)"
fi

# Public ingest: ensure no API key required and method guard works
echo "[check] Public ingest behavior"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" -d '{"cpuModel":"CPU","gpuModel":null,"ramGB":16,"os":"macOS","codec":"libx264","preset":"fast","fps":1,"fileSizeBytes":10240}')
[[ "$code" == "201" || "$code" == "200" || "$code" == "400" ]] || fail "public ingest should not 401"
code=$(curl -s -o /dev/null -w "%{http_code}" -X GET "$BASE_URL/submit")
[[ "$code" == "405" ]] || fail "/submit should reject GET with 405"
pass "public ingest"

echo "[check] CORS preflight"
if [[ "$CAN_CONTROL_STACK" -eq 1 ]]; then
  out=$(curl -i -s -X OPTIONS "$BASE_URL/submit" -H 'Origin: http://localhost:3000' -H 'Access-Control-Request-Method: POST')
  echo "$out" | grep -qi "Access-Control-Allow-Origin: http://localhost:3000" || fail "cors origin"
  pass "cors preflight"
else
  echo "[skip] CORS preflight (remote URL; origin rules may differ)"
fi

if [[ "$CAN_CONTROL_STACK" -eq 1 || "$ALLOW_MUTATION_REMOTE" == "1" ]]; then
  echo "[check] Body size limit"
  tmpbig=$(mktemp)
  python3 - <<'PY' > "$tmpbig"
print('{'+"\"cpuModel\":\"CPU\",\"ramGB\":16,\"os\":\"macOS\",\"codec\":\"libx264\",\"preset\":\"fast\",\"fps\":1,\"fileSizeBytes\":1,\"notes\":\"" + ('x'*2*1024*1024) + "\"}")
PY
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" --data-binary @"$tmpbig")
  rm -f "$tmpbig"
  [[ "$code" == "413" || "$code" == "400" ]] || fail "body limit should reject large payload"
  pass "body limit"
else
  echo "[skip] Body size limit (no stack control and ALLOW_MUTATION_REMOTE!=1)"
fi

echo "[check] Rate limiting"
codes=$(for i in {1..50}; do curl -s -o /dev/null -w "%{http_code} " "$BASE_URL/health"; done)
echo "$codes" | grep -q "429" && fail "health endpoints should be skipped from rate limit"
pass "rate limit skip for health"

if [[ "$CAN_CONTROL_STACK" -eq 1 ]]; then
  echo "[check] DB outage handling"
  eval "$COMPOSE stop db >/dev/null"
  sleep 1
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health/ready")
  [[ "$code" == "503" ]] || fail "ready should degrade when DB down"
  eval "$COMPOSE start db >/dev/null"
  retry_curl_json /health/ready || fail "ready should recover after DB up"
  pass "db outage and recovery"
else
  echo "[skip] DB outage handling (no stack control)"
fi

if [[ "$CAN_CONTROL_STACK" -eq 1 ]]; then
  echo "[check] Graceful shutdown"
  eval "$COMPOSE stop server >/dev/null" || true
  sleep 1
  eval "$COMPOSE start server >/dev/null"
  retry_curl_json /health/ready || fail "server should recover after restart"
  pass "graceful restart"
else
  echo "[skip] Graceful restart (no stack control)"
fi

echo "[check] Query endpoint returns data"
curl -sf "$BASE_URL/query" >/dev/null || fail "query"
pass "query"

echo "ALL CHECKS PASSED"

