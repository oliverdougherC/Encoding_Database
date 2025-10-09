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

# --- Hotfix: ensure strict-safe diskWatchdog.ts present even if remote hasn't updated ---
cat > server/src/diskWatchdog.ts <<'EOF'
import { execFile } from 'node:child_process';

let thresholdGb = Math.max(1, Number(process.env.DISK_MIN_FREE_GB || 25));
let diskPath = String(process.env.DISK_PATH || '/');

export let ingestReadOnly = false;
let freeGb = Number.NaN;

function parseDfKB(out: string): { freeBytes: number } | null {
  // Expect lines like: Filesystem 1K-blocks Used Available Use% Mounted on
  // We will pick the line for diskPath (best-effort: last column equals diskPath)
  const lines = out.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return null;
  // Skip header, find a line whose last column matches diskPath
  for (let i = 1; i < lines.length; i++) {
    const raw = lines[i] ?? '';
    const parts = raw.split(/\s+/);
    if (parts.length < 6) continue;
    const mount = String(parts[parts.length - 1] ?? '');
    if (mount === diskPath) {
      const availStr = String(parts[parts.length - 3] ?? '');
      const availableKb = Number(availStr);
      if (Number.isFinite(availableKb)) {
        return { freeBytes: availableKb * 1024 };
      }
    }
  }
  // Fallback: try the second line if no exact match
  const raw2 = lines[1] ?? '';
  const parts = raw2.split(/\s+/);
  if (parts.length >= 6) {
    const availStr = String(parts[parts.length - 3] ?? '');
    const availableKb = Number(availStr);
    if (Number.isFinite(availableKb)) {
      return { freeBytes: availableKb * 1024 };
    }
  }
  return null;
}

export function getState() {
  return {
    ingestReadOnly,
    freeGB: freeGb,
    thresholdGB: thresholdGb,
    path: diskPath,
  } as const;
}

export function startWatchdog(intervalMs: number = 10_000) {
  tryTick();
  setInterval(tryTick, Math.max(2_000, intervalMs)).unref();
}

function tryTick() {
  execFile('df', ['-k', diskPath], { timeout: 5000 }, (err, stdout) => {
    if (err || !stdout) {
      return; // keep previous state
    }
    const parsed = parseDfKB(stdout);
    if (!parsed) return;
    const gb = parsed.freeBytes / (1024 * 1024 * 1024);
    freeGb = gb;
    const nextReadOnly = gb < thresholdGb;
    ingestReadOnly = nextReadOnly;
  });
}
EOF

# --- Ensure DB user password matches .env (handles existing volumes) ---
echo "Ensuring database is up..."
docker compose -f docker-compose.prod.yml up -d db
# Wait for Postgres to accept connections
DB_READY=0
for i in {1..30}; do
  docker compose -f docker-compose.prod.yml exec -T db pg_isready -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-benchmarks}" >/dev/null 2>&1 && DB_READY=1 && break || true
  sleep 2
done
if [ "$DB_READY" -ne 1 ]; then
  echo "Postgres not ready after timeout; continuing anyway..."
fi
# Align user password inside DB to match .env (safe if already aligned)
docker compose -f docker-compose.prod.yml exec -T db sh -lc "psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \"ALTER USER \\\"${POSTGRES_USER:-app}\\\" WITH PASSWORD '${POSTGRES_PASSWORD}';\"" >/dev/null 2>&1 || true

# --- Build & deploy ---
docker compose -f docker-compose.prod.yml build --no-cache server frontend
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