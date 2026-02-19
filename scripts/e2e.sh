#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
PORT="${PORT:-3001}"
BASE_URL="http://127.0.0.1:${PORT}"
LOCAL_TEST_LOG="$SCRIPT_DIR/.e2e_local_test.log"
CLIENT_LOG="$SCRIPT_DIR/.e2e_client.log"

NO_SUBMIT=0
SEED_COUNT="${SEED_DUMMY_BENCHMARKS_COUNT:-480}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-submit) NO_SUBMIT=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--no-submit]"
      echo "  --no-submit   Run client smoke test without submitting to API."
      echo ""
      echo "Env:"
      echo "  PORT                          Backend port (default: 3001)"
      echo "  SEED_DUMMY_BENCHMARKS_COUNT   Local dummy rows for local_test (default: 480)"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

echo "[e2e] ROOT_DIR=$ROOT_DIR"
echo "[e2e] BASE_URL=$BASE_URL"

LOCAL_TEST_PID=""
cleanup() {
  if [[ -n "$LOCAL_TEST_PID" ]] && kill -0 "$LOCAL_TEST_PID" >/dev/null 2>&1; then
    echo "[e2e] Stopping local_test stack (PID $LOCAL_TEST_PID)"
    kill "$LOCAL_TEST_PID" >/dev/null 2>&1 || true
    wait "$LOCAL_TEST_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[e2e] Starting local stack via scripts/local_test.sh"
: > "$LOCAL_TEST_LOG"
(
  cd "$ROOT_DIR"
  SEED_DUMMY_BENCHMARKS=1 \
  SEED_DUMMY_BENCHMARKS_COUNT="$SEED_COUNT" \
  PORT="$PORT" \
  ./scripts/local_test.sh --no-frontend --no-client-check
) >> "$LOCAL_TEST_LOG" 2>&1 &
LOCAL_TEST_PID=$!

echo "[e2e] Waiting for /health/ready"
for i in {1..120}; do
  if ! kill -0 "$LOCAL_TEST_PID" >/dev/null 2>&1; then
    echo "[e2e] local_test.sh exited unexpectedly. Last 80 lines:" >&2
    tail -n 80 "$LOCAL_TEST_LOG" >&2 || true
    exit 1
  fi
  code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/health/ready" || true)"
  if [[ "$code" == "200" ]]; then
    echo "[e2e] Backend is ready"
    break
  fi
  if [[ "$i" -eq 120 ]]; then
    echo "[e2e] Timed out waiting for backend readiness (last code=$code)." >&2
    tail -n 80 "$LOCAL_TEST_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done

echo "[e2e] Preparing Python client venv"
cd "$CLIENT_DIR"
python3 -m venv .venv >/dev/null 2>&1 || true
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

echo "[e2e] Running automated client menu flow (single benchmark)"
: > "$CLIENT_LOG"
CLIENT_CMD=(python3 main.py --base-url "$BASE_URL")
if [[ "$NO_SUBMIT" -eq 1 ]]; then
  CLIENT_CMD+=(--no-submit)
fi

# Menu automation:
# 1) Run Single Benchmark
# 2) encoder: default
# 3) CRF: default
# 4) preset: default
printf '1\n\n\n\n' | "${CLIENT_CMD[@]}" | tee "$CLIENT_LOG"

if [[ "$NO_SUBMIT" -eq 0 ]]; then
  if ! grep -q "Submitted Results" "$CLIENT_LOG"; then
    echo "[e2e] Client run did not report a successful submission." >&2
    tail -n 120 "$CLIENT_LOG" >&2 || true
    exit 1
  fi
fi

echo "[e2e] Verifying API query endpoint"
code_query="$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/query")"
if [[ "$code_query" != "200" ]]; then
  echo "[e2e] /query returned HTTP $code_query" >&2
  exit 1
fi
curl -s "$BASE_URL/query?limit=3" | head -c 600 && echo

echo "[e2e] PASS"
