#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/ofhd/Developer/Encoding_Database"
COMPOSE="docker compose -f $ROOT_DIR/docker-compose.prod.yml"
BASE_URL="http://localhost:3001"

pass() { echo -e "[PASS] $1"; }
fail() { echo -e "[FAIL] $1"; exit 1; }

retry_curl_json() {
  local path="$1"; shift
  for i in {1..30}; do
    if curl -sf "$BASE_URL$path" >/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}

echo "[prep] Ensuring stack is up"
$COMPOSE up -d >/dev/null

echo "[wait] Waiting for readiness"
retry_curl_json /health/ready || { $COMPOSE logs server | tail -n 200; fail "Server not ready"; }

echo "[check] Health endpoints"
curl -sf "$BASE_URL/health/live" >/dev/null || fail "live"
curl -sf "$BASE_URL/health/ready" >/dev/null || fail "ready"
curl -sf "$BASE_URL/health" >/dev/null || fail "health"
pass "health endpoints"

echo "[check] Validation and coercion"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" -H "x-api-key: ${API_KEY:-test_api_key_123}" -d '{}')
[[ "$code" == "400" ]] || fail "invalid payload should 400"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" -H "x-api-key: ${API_KEY:-test_api_key_123}" -d '{"cpuModel":"CPU","gpuModel":null,"ramGB":"16","os":"macOS","codec":"libx264","preset":"fast","fps":"12.3","fileSizeBytes":"1000"}')
[[ "$code" == "201" ]] || fail "coercion submit should 201"
pass "validation/coercion"

echo "[check] Auth guard"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" -d '{"cpuModel":"CPU","gpuModel":null,"ramGB":16,"os":"macOS","codec":"libx264","preset":"fast","fps":1,"fileSizeBytes":1}')
[[ "$code" == "401" ]] || fail "unauthorized should 401"
pass "auth guard"

echo "[check] CORS preflight"
out=$(curl -i -s -X OPTIONS "$BASE_URL/submit" -H 'Origin: http://localhost:3000' -H 'Access-Control-Request-Method: POST')
echo "$out" | grep -qi "Access-Control-Allow-Origin: http://localhost:3000" || fail "cors origin"
pass "cors preflight"

echo "[check] Body size limit"
tmpbig=$(mktemp)
python3 - <<'PY' > "$tmpbig"
print('{'+"\"cpuModel\":\"CPU\",\"ramGB\":16,\"os\":\"macOS\",\"codec\":\"libx264\",\"preset\":\"fast\",\"fps\":1,\"fileSizeBytes\":1,\"notes\":\"" + ('x'*2*1024*1024) + "\"}")
PY
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/submit" -H "Content-Type: application/json" -H "x-api-key: ${API_KEY:-test_api_key_123}" --data-binary @"$tmpbig")
rm -f "$tmpbig"
[[ "$code" == "413" || "$code" == "400" ]] || fail "body limit should reject large payload"
pass "body limit"

echo "[check] Rate limiting"
codes=$(for i in {1..50}; do curl -s -o /dev/null -w "%{http_code} " "$BASE_URL/health"; done)
echo "$codes" | grep -q "429" && fail "health endpoints should be skipped from rate limit"
pass "rate limit skip for health"

echo "[check] DB outage handling"
$COMPOSE stop db >/dev/null
sleep 1
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health/ready")
[[ "$code" == "503" ]] || fail "ready should degrade when DB down"
$COMPOSE start db >/dev/null
retry_curl_json /health/ready || fail "ready should recover after DB up"
pass "db outage and recovery"

echo "[check] Graceful shutdown"
$COMPOSE stop server >/dev/null || true
sleep 1
$COMPOSE start server >/dev/null
retry_curl_json /health/ready || fail "server should recover after restart"
pass "graceful restart"

echo "[check] Query endpoint returns data"
curl -sf "$BASE_URL/query" >/dev/null || fail "query"
pass "query"

echo "ALL CHECKS PASSED"

