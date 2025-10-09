#!/usr/bin/env bash
set -euo pipefail

# Simple environment setup script for Encoding Database
# - Writes ./.env (used by docker-compose.prod.yml and server)
# - Mirrors to server/.env for local runs
# - Accepts flags to override defaults; otherwise generates sensible defaults
#
# Usage examples:
#   scripts/setup_env.sh                           # use defaults + random secrets
#   scripts/setup_env.sh --domain example.com      # set domain and derive CORS
#   scripts/setup_env.sh --ingest-secret abc123    # set specific HMAC secret
#   scripts/setup_env.sh --postgres-password s3cr3t --cors-origins https://a.com,https://b.com

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"

color() { printf "\033[%sm%s\033[0m" "$1" "$2"; }
green() { color 32 "$1"; }
yellow() { color 33 "$1"; }
red() { color 31 "$1"; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

rand_hex() {
  local bytes="${1:-32}"
  if have_cmd openssl; then
    openssl rand -hex "$bytes"
  elif have_cmd hexdump; then
    hexdump -vn "$bytes" -e '"%02x"' /dev/urandom
  else
    # Very weak fallback; should not occur on typical systems
    date +%s%N | shasum | awk '{print $1}'
  fi
}

# Defaults
DOMAIN="encodingdb.platinumlabs.dev"
POSTGRES_USER="app"
POSTGRES_PASSWORD=""
POSTGRES_DB="benchmarks"
PORT="3001"
INGEST_HMAC_SECRET=""
CORS_ORIGINS=""
BODY_LIMIT="1mb"
RATE_LIMIT_WINDOW_MS="60000"
RATE_LIMIT_MAX="300"
SUBMIT_RATE_WINDOW_MS="60000"
SUBMIT_RATE_MAX="30"
NEXT_PUBLIC_API_BASE_URL=""
# Beta auth & quotas
API_KEY_HEADER="X-API-Key"
SUBMIT_PER_KEY_PER_MINUTE="30"
SUBMIT_PER_KEY_PER_DAY="1000"
DISK_MIN_FREE_GB="25"
DISK_PATH="/"
ADMIN_TOKEN=""

print_help() {
  cat <<'EOF'
Usage: setup_env.sh [options]

Options:
  --domain DOMAIN                 Public site domain (default: encodingdb.platinumlabs.dev)
  --postgres-user USER            Postgres username (default: app)
  --postgres-password PASS        Postgres password (default: random)
  --postgres-db NAME              Postgres database name (default: benchmarks)
  --port PORT                     Backend port (default: 3001)
  --ingest-secret HEX             HMAC secret for /submit (default: random 32 bytes hex)
  --cors-origins CSV              Comma-separated allowlist for CORS_ORIGIN (default: https://<domain>)
  --body-limit SIZE               express.json size limit (default: 1mb)
  --rate-window-ms MS             Global rate limit window (default: 60000)
  --rate-max N                    Global rate limit max (default: 300)
  --submit-window-ms MS           /submit rate limit window (default: 60000)
  --submit-max N                  /submit rate limit max (default: 30)
  --public-api-base URL           NEXT_PUBLIC_API_BASE_URL (default: https://<domain>)
  --api-key-header NAME           Header name for API key (default: X-API-Key)
  --per-key-per-minute N          Per-key minute quota (default: 30)
  --per-key-per-day N             Per-key day quota (default: 1000)
  --disk-min-free-gb N            Reject submissions below this free GB (default: 25)
  --disk-path PATH                Filesystem mount to monitor (default: /)
  --admin-token TOKEN             Admin token for /admin API (default: random)
  -h, --help                      Show this help

This script writes .env at repo root and mirrors it to server/.env.
EOF
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --postgres-user) POSTGRES_USER="$2"; shift 2 ;;
    --postgres-password) POSTGRES_PASSWORD="$2"; shift 2 ;;
    --postgres-db) POSTGRES_DB="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --ingest-secret) INGEST_HMAC_SECRET="$2"; shift 2 ;;
    --cors-origins) CORS_ORIGINS="$2"; shift 2 ;;
    --body-limit) BODY_LIMIT="$2"; shift 2 ;;
    --rate-window-ms) RATE_LIMIT_WINDOW_MS="$2"; shift 2 ;;
    --rate-max) RATE_LIMIT_MAX="$2"; shift 2 ;;
    --submit-window-ms) SUBMIT_RATE_WINDOW_MS="$2"; shift 2 ;;
    --submit-max) SUBMIT_RATE_MAX="$2"; shift 2 ;;
    --public-api-base) NEXT_PUBLIC_API_BASE_URL="$2"; shift 2 ;;
    --api-key-header) API_KEY_HEADER="$2"; shift 2 ;;
    --per-key-per-minute) SUBMIT_PER_KEY_PER_MINUTE="$2"; shift 2 ;;
    --per-key-per-day) SUBMIT_PER_KEY_PER_DAY="$2"; shift 2 ;;
    --disk-min-free-gb) DISK_MIN_FREE_GB="$2"; shift 2 ;;
    --disk-path) DISK_PATH="$2"; shift 2 ;;
    --admin-token) ADMIN_TOKEN="$2"; shift 2 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; print_help; exit 2 ;;
  esac
done

# Sanitize/derive DOMAIN and public URLs
DOMAIN="$(echo "${DOMAIN}" | sed -E 's#^https?://##; s#/+$##')"
if [[ -z "$DOMAIN" ]]; then DOMAIN="encodingdb.platinumlabs.dev"; fi

# Fill defaults
if [[ -z "$CORS_ORIGINS" || "$CORS_ORIGINS" = "https://" || "$CORS_ORIGINS" = "http://" ]]; then CORS_ORIGINS="https://$DOMAIN"; fi
if [[ -z "$NEXT_PUBLIC_API_BASE_URL" || "$NEXT_PUBLIC_API_BASE_URL" = "https://" || "$NEXT_PUBLIC_API_BASE_URL" = "http://" ]]; then NEXT_PUBLIC_API_BASE_URL="https://$DOMAIN"; fi
if [[ -z "$POSTGRES_PASSWORD" ]]; then POSTGRES_PASSWORD="$(rand_hex 24)"; fi
if [[ -z "$INGEST_HMAC_SECRET" ]]; then INGEST_HMAC_SECRET="$(rand_hex 32)"; fi
if [[ -z "$ADMIN_TOKEN" ]]; then ADMIN_TOKEN="$(rand_hex 24)"; fi

DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}?schema=public"

write_env() {
  local path="$1"
  cat >"$path" <<EOF
# Generated by scripts/setup_env.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Safe to commit? NO. This file may contain secrets.

# Postgres
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=${POSTGRES_DB}
DATABASE_URL=${DATABASE_URL}

# Server
PORT=${PORT}
CORS_ORIGIN=${CORS_ORIGINS}
BODY_LIMIT=${BODY_LIMIT}
RATE_LIMIT_WINDOW_MS=${RATE_LIMIT_WINDOW_MS}
RATE_LIMIT_MAX=${RATE_LIMIT_MAX}
SUBMIT_RATE_WINDOW_MS=${SUBMIT_RATE_WINDOW_MS}
SUBMIT_RATE_MAX=${SUBMIT_RATE_MAX}
INGEST_HMAC_SECRET=${INGEST_HMAC_SECRET}

# API key auth (beta)
API_KEY_HEADER=${API_KEY_HEADER}
SUBMIT_PER_KEY_PER_MINUTE=${SUBMIT_PER_KEY_PER_MINUTE}
SUBMIT_PER_KEY_PER_DAY=${SUBMIT_PER_KEY_PER_DAY}

# Disk watchdog
DISK_MIN_FREE_GB=${DISK_MIN_FREE_GB}
DISK_PATH=${DISK_PATH}

# Admin API
ADMIN_TOKEN=${ADMIN_TOKEN}

# Frontend (public)
NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
EOF
}

ROOT_ENV="$ROOT_DIR/.env"
SERVER_ENV="$ROOT_DIR/server/.env"

write_env "$ROOT_ENV"
mkdir -p "$ROOT_DIR/server"
cp "$ROOT_ENV" "$SERVER_ENV"

chmod 600 "$ROOT_ENV" || true
chmod 600 "$SERVER_ENV" || true

echo "$(green "✔") Wrote $(yellow "$ROOT_ENV") and $(yellow "$SERVER_ENV")"
echo "Domain:          $DOMAIN"
echo "CORS_ORIGIN:     $CORS_ORIGINS"
echo "Public API base: $NEXT_PUBLIC_API_BASE_URL"
echo "Postgres user:   $POSTGRES_USER"
echo "Postgres db:     $POSTGRES_DB"
echo "Server port:     $PORT"
echo "Submit limits:   ${SUBMIT_RATE_MAX} per ${SUBMIT_RATE_WINDOW_MS}ms"
echo "Global limits:   ${RATE_LIMIT_MAX} per ${RATE_LIMIT_WINDOW_MS}ms"
echo "Body limit:      $BODY_LIMIT"

echo
echo "Next steps:"
echo "  1) Ensure Nginx Proxy Manager host uses HTTPS and the Advanced config from nginx/NPM_ADVANCED_CONFIG.md"
echo "  2) Deploy with: docker compose -f docker-compose.prod.yml up -d --build"
echo "  3) Verify /health/ready at your domain"


