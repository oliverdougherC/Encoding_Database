#!/usr/bin/env bash
set -euo pipefail

cd ~/Encoding_Database

# --- Helpers ---
have_cmd() { command -v "$1" >/dev/null 2>&1; }
get_val() {
  # get_val FILE VAR_NAME
  # Grep last clean assignment of VAR=... ignoring merge markers
  local file="$1" var="$2"
  if [ -f "$file" ]; then
    grep -E "^${var}=" "$file" | grep -v '<<<<<<<\|=======\|>>>>>>>' | tail -n1 | sed -E "s/^${var}=//"
  fi
}

# --- Ensure env files are ignored and not tracked ---
ensure_gitignore() {
  local gi=".gitignore"
  touch "$gi"
  if ! grep -q '^\.env$' "$gi"; then echo ".env" >> "$gi"; fi
  if ! grep -q '^server/\.env$' "$gi"; then echo "server/.env" >> "$gi"; fi
  if ! grep -q '^*.bak$' "$gi"; then echo "*.bak" >> "$gi"; fi
  git add "$gi" >/dev/null 2>&1 || true
  git commit -m "chore: ignore env files on deploy host" >/dev/null 2>&1 || true
}

untrack_env_files() {
  git rm --cached .env server/.env >/dev/null 2>&1 || true
}

# --- Abort any in-progress merge/rebase cleanly ---
git merge --abort >/dev/null 2>&1 || true
git rebase --abort >/dev/null 2>&1 || true

# --- Prepare/repair .env before pulling ---
ensure_gitignore
untrack_env_files

# --- Pull latest code safely ---
# Allow overrides via env: REMOTE=origin BRANCH=main ./scripts/redploy.sh
REMOTE_REF="${REMOTE:-origin}"
BRANCH_REF="${BRANCH:-main}"
OLD_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "none")
git fetch --all --prune
git fetch "$REMOTE_REF" "$BRANCH_REF" || true
REMOTE_URL=$(git remote get-url "$REMOTE_REF" 2>/dev/null || echo "unknown")
git reset --hard "$REMOTE_REF/$BRANCH_REF"
NEW_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "Source: $REMOTE_REF/$BRANCH_REF ($REMOTE_URL)"
echo "Updated: $OLD_HEAD -> $NEW_HEAD"
echo "Recent commits on $REMOTE_REF/$BRANCH_REF:"
git log --oneline -n 3 "$REMOTE_REF/$BRANCH_REF" || true

# --- Regenerate .env with preserved values (AFTER pulling latest scripts) ---
DEFAULT_DOMAIN="encodingdb.platinumlabs.dev"
POSTGRES_PASSWORD="$(get_val .env POSTGRES_PASSWORD || get_val .env.bak POSTGRES_PASSWORD || true)"
INGEST_HMAC_SECRET="$(get_val .env INGEST_HMAC_SECRET || get_val .env.bak INGEST_HMAC_SECRET || true)"
CORS_ORIGIN="$(get_val .env CORS_ORIGIN || get_val .env.bak CORS_ORIGIN || echo "https://${DEFAULT_DOMAIN}")"
POSTGRES_USER="$(get_val .env POSTGRES_USER || echo "app")"
POSTGRES_DB="$(get_val .env POSTGRES_DB || echo "benchmarks")"
PORT_VAL="$(get_val .env PORT || echo "3001")"
NEXT_PUBLIC_API_BASE_URL="$(get_val .env NEXT_PUBLIC_API_BASE_URL || echo "https://${DEFAULT_DOMAIN}")"

# If .env contains merge markers, back it up before regenerating
if grep -q '<<<<<<<\|=======\|>>>>>>>' .env 2>/dev/null; then
  cp .env .env.autofix.bak || true
fi

# Derive domain from CORS_ORIGIN when available; fall back to default domain
DOMAIN_CAND="${CORS_ORIGIN#https://}"
DOMAIN_CAND="${DOMAIN_CAND#http://}"
DOMAIN_CAND="${DOMAIN_CAND%%/*}"
if [ -z "$DOMAIN_CAND" ] || [ "$DOMAIN_CAND" = "" ]; then DOMAIN_CAND="$DEFAULT_DOMAIN"; fi

./scripts/setup_env.sh \
  --domain "$DOMAIN_CAND" \
  --cors-origins "$CORS_ORIGIN" \
  --postgres-user "${POSTGRES_USER:-app}" \
  ${POSTGRES_PASSWORD:+--postgres-password "$POSTGRES_PASSWORD"} \
  --postgres-db "${POSTGRES_DB:-benchmarks}" \
  ${INGEST_HMAC_SECRET:+--ingest-secret "$INGEST_HMAC_SECRET"} \
  --port "${PORT_VAL:-3001}" \
  --public-api-base "${NEXT_PUBLIC_API_BASE_URL:-https://${DEFAULT_DOMAIN}}"

# Make sure env files are not tracked
untrack_env_files

# --- Build & deploy ---
docker compose -f docker-compose.prod.yml build server frontend
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate server frontend

# Apply Prisma migrations (idempotent; server also runs this on startup)
docker compose -f docker-compose.prod.yml exec server npx prisma migrate deploy || true

# Wait for backend readiness via nginx proxy
echo "Waiting for backend readiness at http://localhost/health/ready ..."
READY=0
for i in {1..30}; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health/ready || true)
  if [ "$code" = "200" ]; then READY=1; break; fi
  sleep 2
done
if [ "$READY" -ne 1 ]; then
  echo "Edge not ready, checking directly inside server container..."
  docker compose -f docker-compose.prod.yml exec -T server sh -lc "wget -qO- http://localhost:3001/health/ready >/dev/null && echo 'Server responded OK'" || echo "Server not ready yet"
fi

# Optionally check frontend
echo "Checking frontend at http://localhost ..."
curl -s -o /dev/null -w "Frontend HTTP %{http_code}\n" http://localhost || true

# Tail recent logs
docker compose -f docker-compose.prod.yml logs --tail=80 server