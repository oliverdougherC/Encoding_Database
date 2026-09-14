#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${V7_BACKUP_SERVER_IMAGE:-}" ]]; then
  exec node "$ROOT_DIR/server/scripts/v7-backup-inventory.mjs" "$@"
fi
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${V7_BACKUP_DOCKER_WORK_ROOT:?V7_BACKUP_DOCKER_WORK_ROOT is required}"
[[ "$V7_BACKUP_DOCKER_WORK_ROOT" == /* && -d "$V7_BACKUP_DOCKER_WORK_ROOT" ]] || { echo 'backup Docker work root must be an existing absolute directory' >&2; exit 2; }
# Use the exact candidate's generated Prisma client, without installing host npm
# packages. Pass the database secret through the environment, never command text.
exec docker run --rm --network "${V7_BACKUP_INVENTORY_NETWORK:-${V7_BACKUP_DOCKER_NETWORK:-host}}" \
  --user "$(id -u):$(id -g)" --env DATABASE_URL \
  -v "$V7_BACKUP_DOCKER_WORK_ROOT:$V7_BACKUP_DOCKER_WORK_ROOT" \
  -v "$ROOT_DIR/server/scripts/v7-backup-inventory.mjs:/app/scripts/v7-backup-inventory.mjs:ro" \
  --entrypoint node "$V7_BACKUP_SERVER_IMAGE" /app/scripts/v7-backup-inventory.mjs "$@"
