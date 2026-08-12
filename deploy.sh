#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
if [[ ! -f "$ROOT_DIR/docker-compose.prod.yml" ]]; then
  ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

REMOTE="${DEPLOY_REMOTE:-origin}"
BRANCH="${DEPLOY_BRANCH:-main}"
COMPOSE_FILE="${DEPLOY_COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE_TIMEOUT_SECONDS="${DEPLOY_SERVICE_TIMEOUT_SECONDS:-240}"
API_TIMEOUT_SECONDS="${DEPLOY_API_TIMEOUT_SECONDS:-240}"
SKIP_PULL=0

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [--skip-pull] [--help]

Options:
  --skip-pull  Skip git fetch/pull and deploy current local checkout.
  --help       Show this help text.

Environment overrides:
  DEPLOY_REMOTE=origin
  DEPLOY_BRANCH=main
  DEPLOY_COMPOSE_FILE=docker-compose.prod.yml
  DEPLOY_SERVICE_TIMEOUT_SECONDS=240
  DEPLOY_API_TIMEOUT_SECONDS=240
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pull)
      SKIP_PULL=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[deploy] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  echo "[deploy] $*"
}

die() {
  echo "[deploy] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

read_env_value() {
  local key="$1"
  local value
  value="$(
    awk -F= -v key="$key" '
      $0 !~ /^[[:space:]]*#/ && $1 == key {
        print substr($0, index($0, "=") + 1)
      }
    ' .env | tail -n 1
  )"
  value="$(printf '%s' "$value" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

ensure_clean_worktree() {
  if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    die "Working tree is not clean. Commit/stash changes, or run with --skip-pull."
  fi
}

wait_for_service() {
  local service="$1"
  local timeout="$2"
  local elapsed=0
  while (( elapsed < timeout )); do
    local cid state health summary
    cid="$(docker compose -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
      summary="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || true)"
      state="${summary%% *}"
      health="${summary##* }"
      if [[ "$state" == "running" && ( "$health" == "healthy" || "$health" == "none" ) ]]; then
        log "Service '$service' is running (health=$health)."
        return 0
      fi
      if [[ "$state" == "exited" || "$state" == "dead" ]]; then
        log "Service '$service' entered state=$state (health=$health)."
        docker compose -f "$COMPOSE_FILE" logs --tail=120 "$service" || true
        return 1
      fi
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  log "Timed out waiting for service '$service' after ${timeout}s."
  docker compose -f "$COMPOSE_FILE" logs --tail=120 "$service" || true
  return 1
}

wait_for_api_ready() {
  local timeout="$1"
  local elapsed=0
  while (( elapsed < timeout )); do
    if docker compose -f "$COMPOSE_FILE" exec -T server \
      node -e "require('http').get('http://127.0.0.1:3001/health/ready',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1));" \
      >/dev/null 2>&1; then
      log "API readiness check passed (/health/ready=200)."
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  log "API readiness check failed after ${timeout}s."
  docker compose -f "$COMPOSE_FILE" logs --tail=120 server || true
  return 1
}

compose_exec_node() {
  local service="$1"
  local script="$2"
  docker compose -f "$COMPOSE_FILE" exec -T "$service" node -e "$script"
}

run_preflight_validation() {
  log "Validating production env contract..."
  local args=(--env-file "$ROOT_DIR/.env")
  if [[ -n "$reference_context_path" ]]; then
    args+=(--reference-context "$reference_context_path")
  fi
  node "$ROOT_DIR/scripts/validate-production-env.mjs" "${args[@]}"

  log "Validating compose configuration..."
  docker compose -f "$COMPOSE_FILE" config -q
}

cd "$ROOT_DIR"

require_cmd git
require_cmd docker
require_cmd node

[[ -d ".git" ]] || die "Not a git repository: $ROOT_DIR"
[[ -f "$COMPOSE_FILE" ]] || die "Compose file not found: $COMPOSE_FILE"
[[ -f ".env" ]] || die "Missing .env in $ROOT_DIR. Create it from env.example before deployment."

ingest_mode="$(read_env_value "INGEST_MODE")"
normalized_ingest_mode="$(printf '%s' "$ingest_mode" | tr '[:upper:]' '[:lower:]')"
if [[ -z "$normalized_ingest_mode" ]]; then
  log "WARNING: INGEST_MODE is unset. Runtime default is public (unsigned submissions accepted)."
elif [[ "$normalized_ingest_mode" == "public" ]]; then
  log "WARNING: INGEST_MODE=public allows unsigned submissions."
fi
if [[ "$normalized_ingest_mode" == "signed" ]]; then
  ingest_secret="$(read_env_value "INGEST_HMAC_SECRET")"
  [[ -n "$ingest_secret" ]] || die "INGEST_MODE=signed requires INGEST_HMAC_SECRET in .env."
fi

reference_context_path="$(read_env_value "PL_V7_REFERENCE_CONTEXT_PATH")"
if [[ -z "$reference_context_path" ]]; then
  log "PL_V7_REFERENCE_CONTEXT_PATH is unset; authoritative evidence will remain browseable and canonical PL will stay unavailable."
elif [[ ! -f "$reference_context_path" ]]; then
  die "PL_V7_REFERENCE_CONTEXT_PATH does not exist: $reference_context_path"
fi

run_preflight_validation

if [[ "$SKIP_PULL" -eq 0 ]]; then
  ensure_clean_worktree
  log "Fetching latest '$BRANCH' from '$REMOTE'..."
  git fetch --prune "$REMOTE" "$BRANCH"

  current_branch="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current_branch" != "$BRANCH" ]]; then
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
      log "Checking out local branch '$BRANCH'..."
      git checkout "$BRANCH"
    else
      log "Creating local branch '$BRANCH' tracking '$REMOTE/$BRANCH'..."
      git checkout -b "$BRANCH" --track "$REMOTE/$BRANCH"
    fi
  fi

  log "Pulling latest changes (fast-forward only)..."
  git pull --ff-only "$REMOTE" "$BRANCH"
fi

run_preflight_validation

log "Building and starting production stack..."
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

log "Waiting for services to become healthy..."
services="$(docker compose -f "$COMPOSE_FILE" config --services)"
for service in $services; do
  wait_for_service "$service" "$SERVICE_TIMEOUT_SECONDS" || die "Service readiness failed: $service"
done

if echo "$services" | grep -qx "server"; then
  wait_for_api_ready "$API_TIMEOUT_SECONDS" || die "API readiness failed."
  log "Running post-deploy smoke checks..."
  compose_exec_node server 'const {PrismaClient}=require("@prisma/client"); const prisma=new PrismaClient(); prisma.$queryRawUnsafe("SELECT 1").then(async()=>{await prisma.$disconnect();}).catch(async(error)=>{console.error(error); try{await prisma.$disconnect();}catch{} process.exit(1);});' \
    || die "Database query smoke failed."
  compose_exec_node server 'const http=require("http"); const checks=["/health/live","/health/ready","/health/v7-evidence","/query?limit=1","/test-videos","/corpus?limit=1"]; let index=0; const next=()=>{ const target=checks[index++]; if(!target) return process.exit(0); http.get({host:"127.0.0.1",port:3001,path:target},(res)=>{ let body=""; res.setEncoding("utf8"); res.on("data",(chunk)=>body+=chunk); res.on("end",()=>{ if(res.statusCode!==200) process.exit(1); try { const parsed=JSON.parse(body); if((target==="/query?limit=1" || target==="/corpus?limit=1" || target==="/test-videos") && !Array.isArray(parsed)) process.exit(1); if(target==="/health/v7-evidence" && (!parsed || parsed.status!=="ok")) process.exit(1); } catch (error) { if(target.startsWith("/health/")) process.exit(1); } next(); }); }).on("error",()=>process.exit(1)); }; next();' \
    || die "Server endpoint smoke failed."
fi

if echo "$services" | grep -qx "frontend"; then
  compose_exec_node frontend 'const http=require("http"); http.get({host:"127.0.0.1",port:3000,path:"/"},(res)=>{ let body=""; res.setEncoding("utf8"); res.on("data",(chunk)=>body+=chunk); res.on("end",()=>{ if(res.statusCode!==200 || !/Encoding Database/i.test(body)) process.exit(1); process.exit(0); }); }).on("error",()=>process.exit(1));' \
    || die "Frontend homepage smoke failed."
  compose_exec_node frontend 'const http=require("http"); http.get({host:"127.0.0.1",port:3000,path:"/api/corpus?limit=1"},(res)=>{ let body=""; res.setEncoding("utf8"); res.on("data",(chunk)=>body+=chunk); res.on("end",()=>{ if(res.statusCode!==200) process.exit(1); const parsed=JSON.parse(body); if(!Array.isArray(parsed)) process.exit(1); process.exit(0); }); }).on("error",()=>process.exit(1));' \
    || die "Frontend corpus proxy smoke failed."
fi

commit="$(git rev-parse --short HEAD)"
log "Deployment complete at commit $commit."
docker compose -f "$COMPOSE_FILE" ps
