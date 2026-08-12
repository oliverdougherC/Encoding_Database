#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="${1:-}"
if [[ -z "$BUNDLE_DIR" ]]; then echo "usage: v7-restore-drill.sh BACKUP_DIR" >&2; exit 2; fi
BUNDLE_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$BUNDLE_DIR")"
for file in SHA256SUMS artifacts.tar.gz database.dump inventory.json; do
  [[ -f "$BUNDLE_DIR/$file" ]] || { echo "backup missing $file" >&2; exit 2; }
done
(cd "$BUNDLE_DIR" && shasum -a 256 -c SHA256SUMS)

DRILL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/encodingdb-v7-restore.XXXXXX")"
CONTAINER_NAME="encodingdb-v7-restore-$RANDOM-$$"
cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf "$DRILL_DIR"
}
trap cleanup EXIT INT TERM
mkdir "$DRILL_DIR/artifacts"
tar -C "$DRILL_DIR/artifacts" -xzf "$BUNDLE_DIR/artifacts.tar.gz"
docker run -d --name "$CONTAINER_NAME" -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=benchmarks -P postgres:16-alpine >/dev/null
for _ in $(seq 1 60); do
  if docker exec "$CONTAINER_NAME" pg_isready -U app -d benchmarks >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$CONTAINER_NAME" pg_isready -U app -d benchmarks >/dev/null
RESTORE_PORT="$(docker port "$CONTAINER_NAME" 5432/tcp | head -1 | sed 's/.*://')"
[[ "$RESTORE_PORT" =~ ^[0-9]+$ ]] || { echo "could not resolve restore port" >&2; exit 1; }
RESTORE_URL="postgresql://app:app@127.0.0.1:${RESTORE_PORT}/benchmarks"
pg_restore --no-owner --no-acl --exit-on-error --dbname "$RESTORE_URL" "$BUNDLE_DIR/database.dump"
DATABASE_URL="$RESTORE_URL" node "$ROOT_DIR/server/scripts/v7-backup-inventory.mjs" \
  --mode verify --artifact-root "$DRILL_DIR/artifacts" --inventory "$BUNDLE_DIR/inventory.json"
echo "PL-v7 isolated restore drill passed"
