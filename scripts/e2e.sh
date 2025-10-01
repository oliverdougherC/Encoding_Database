#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/ofhd/Developer/Encoding_Database"
SERVER_DIR="$ROOT_DIR/server"
CLIENT_DIR="$ROOT_DIR/client"
SAMPLE_VIDEO="$ROOT_DIR/sample.mp4"
PORT="3001"

echo "[e2e] Using ROOT_DIR=$ROOT_DIR"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    echo "[e2e] Stopping server (PID $SERVER_PID)"
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[e2e] Preparing server"
cd "$SERVER_DIR"
export DATABASE_URL="file:./dev.db"
npx prisma migrate deploy >/dev/null
npx prisma generate >/dev/null

echo "[e2e] Starting server on port $PORT"
PORT="$PORT" DATABASE_URL="$DATABASE_URL" npx tsx src/index.ts >/dev/null 2>&1 &
SERVER_PID=$!
sleep 0.5

echo "[e2e] Waiting for server readiness"
ATTEMPTS=0
until curl -sS "http://localhost:$PORT/health" >/dev/null; do
  ATTEMPTS=$((ATTEMPTS+1))
  if [[ $ATTEMPTS -gt 60 ]]; then
    echo "[e2e] Server failed to become healthy in time" >&2
    exit 1
  fi
  sleep 0.5
done
echo "[e2e] Server is healthy"

echo "[e2e] Ensuring sample video at $SAMPLE_VIDEO"
if [[ ! -f "$SAMPLE_VIDEO" ]]; then
  ffmpeg -y -f lavfi -i testsrc=size=1280x720:rate=30 -t 5 "$SAMPLE_VIDEO" >/dev/null 2>&1
fi

echo "[e2e] Preparing Python client venv"
cd "$CLIENT_DIR"
python3 -m venv .venv >/dev/null 2>&1 || true
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

echo "[e2e] Running client benchmark and submissions"
BACKEND_URL="http://localhost:$PORT" python3 main.py "$SAMPLE_VIDEO" >/dev/null

echo "[e2e] Verifying API results"
curl -sS "http://localhost:$PORT/query" | head -c 500 && echo

echo "[e2e] DONE"

