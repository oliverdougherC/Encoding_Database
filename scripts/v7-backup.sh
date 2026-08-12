#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${DATABASE_URL:?DATABASE_URL is required}"
ARTIFACT_VOLUME_NAME="${ARTIFACT_VOLUME_NAME:-}"
ARTIFACT_STORAGE_ROOT="${ARTIFACT_STORAGE_ROOT:-}"
COMPOSE_FILE=""
QUIESCE_SERVICES="${QUIESCE_SERVICES:-server}"
DRY_RUN=0
OUTPUT_DIR=""
QUIESCED_RUNNING_SERVICES=()

usage() {
  cat <<'EOF' >&2
usage: v7-backup.sh [--dry-run] [--artifact-volume NAME] [--compose-file FILE] OUTPUT_DIR
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --artifact-volume)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      ARTIFACT_VOLUME_NAME="$2"
      shift 2
      ;;
    --compose-file)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    -*)
      usage
      exit 2
      ;;
    *)
      if [[ -n "$OUTPUT_DIR" ]]; then usage; exit 2; fi
      OUTPUT_DIR="$1"
      shift
      ;;
  esac
done

if [[ -z "$OUTPUT_DIR" ]]; then usage; exit 2; fi
OUTPUT_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT_DIR")"
if [[ -e "$OUTPUT_DIR" ]]; then echo "backup output already exists: $OUTPUT_DIR" >&2; exit 2; fi

if [[ -n "$ARTIFACT_VOLUME_NAME" ]]; then
  command -v docker >/dev/null 2>&1 || { echo "docker is required for --artifact-volume" >&2; exit 2; }
  docker volume inspect "$ARTIFACT_VOLUME_NAME" >/dev/null
elif [[ ! -d "$ARTIFACT_STORAGE_ROOT" ]]; then
  echo "artifact root is not a directory: $ARTIFACT_STORAGE_ROOT" >&2
  exit 2
fi

if (( DRY_RUN == 1 )); then
  printf '{\n'
  printf '  "mode": "dry-run",\n'
  printf '  "databaseUrlPresent": true,\n'
  printf '  "outputDir": "%s",\n' "$OUTPUT_DIR"
  if [[ -n "$COMPOSE_FILE" ]]; then
    printf '  "composeFile": "%s",\n' "$COMPOSE_FILE"
    printf '  "quiesceServices": "%s",\n' "$QUIESCE_SERVICES"
  fi
  if [[ -n "$ARTIFACT_VOLUME_NAME" ]]; then
    printf '  "artifactSource": { "kind": "docker-volume", "name": "%s" }\n' "$ARTIFACT_VOLUME_NAME"
  else
    printf '  "artifactSource": { "kind": "filesystem", "path": "%s" }\n' "$ARTIFACT_STORAGE_ROOT"
  fi
  printf '}\n'
  exit 0
fi

mkdir -p "$OUTPUT_DIR"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/encodingdb-v7-backup.XXXXXX")"

restart_quiesced_services() {
  if [[ -n "$COMPOSE_FILE" && ${#QUIESCED_RUNNING_SERVICES[@]} -gt 0 ]]; then
    echo "Restarting quiesced writer services: ${QUIESCED_RUNNING_SERVICES[*]}" >&2
    docker compose -f "$COMPOSE_FILE" up -d "${QUIESCED_RUNNING_SERVICES[@]}" >/dev/null
  fi
}

cleanup() {
  restart_quiesced_services
  rm -rf "$STAGING_DIR"
  if [[ ! -f "$OUTPUT_DIR/SHA256SUMS" ]]; then rm -rf "$OUTPUT_DIR"; fi
}
trap cleanup EXIT INT TERM

if [[ -n "$COMPOSE_FILE" ]]; then
  command -v docker >/dev/null 2>&1 || { echo "docker is required for --compose-file" >&2; exit 2; }
  docker compose -f "$COMPOSE_FILE" config --services >/dev/null
  OLD_IFS="$IFS"
  IFS=','
  read -r -a requested_services <<<"$QUIESCE_SERVICES"
  IFS="$OLD_IFS"
  for service in "${requested_services[@]}"; do
    service="${service#"${service%%[![:space:]]*}"}"
    service="${service%"${service##*[![:space:]]}"}"
    [[ -n "$service" ]] || continue
    cid="$(docker compose -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null || true)"
    if [[ -z "$cid" ]]; then
      continue
    fi
    state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)"
    if [[ "$state" == "running" ]]; then
      QUIESCED_RUNNING_SERVICES+=("$service")
    fi
  done
  if [[ ${#QUIESCED_RUNNING_SERVICES[@]} -gt 0 ]]; then
    echo "Quiescing writer services for backup consistency (downtime begins): ${QUIESCED_RUNNING_SERVICES[*]}" >&2
    docker compose -f "$COMPOSE_FILE" stop "${QUIESCED_RUNNING_SERVICES[@]}" >/dev/null
  fi
fi

PG_DATABASE_URL="$(python3 -c 'import sys,urllib.parse as u; p=u.urlsplit(sys.argv[1]); q=u.urlencode([(k,v) for k,v in u.parse_qsl(p.query) if k != "schema"]); print(u.urlunsplit((p.scheme,p.netloc,p.path,q,p.fragment)))' "$DATABASE_URL")"
pg_dump --format=custom --no-owner --no-acl --file "$OUTPUT_DIR/database.dump" "$PG_DATABASE_URL"

ARTIFACT_EXPORT_ROOT="$ARTIFACT_STORAGE_ROOT"
if [[ -n "$ARTIFACT_VOLUME_NAME" ]]; then
  ARTIFACT_EXPORT_ROOT="$STAGING_DIR/artifacts"
  mkdir -p "$ARTIFACT_EXPORT_ROOT"
  docker run --rm \
    -v "${ARTIFACT_VOLUME_NAME}:/from:ro" \
    -v "${ARTIFACT_EXPORT_ROOT}:/to" \
    alpine:3.20 sh -c 'cp -a /from/. /to/'
fi

DATABASE_URL="$DATABASE_URL" node "$ROOT_DIR/server/scripts/v7-backup-inventory.mjs" \
  --mode export --artifact-root "$ARTIFACT_EXPORT_ROOT" \
  --inventory "$OUTPUT_DIR/inventory.json" --output "$OUTPUT_DIR/inventory.json"
tar -C "$ARTIFACT_EXPORT_ROOT" -czf "$OUTPUT_DIR/artifacts.tar.gz" .
(
  cd "$OUTPUT_DIR"
  shasum -a 256 artifacts.tar.gz database.dump inventory.json > SHA256SUMS
)
restart_quiesced_services
QUIESCED_RUNNING_SERVICES=()
echo "PL-v7 backup created: $OUTPUT_DIR"
