#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${ARTIFACT_STORAGE_ROOT:?ARTIFACT_STORAGE_ROOT is required}"
OUTPUT_DIR="${1:-}"
if [[ -z "$OUTPUT_DIR" ]]; then echo "usage: v7-backup.sh OUTPUT_DIR" >&2; exit 2; fi
OUTPUT_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT_DIR")"
if [[ -e "$OUTPUT_DIR" ]]; then echo "backup output already exists: $OUTPUT_DIR" >&2; exit 2; fi
if [[ ! -d "$ARTIFACT_STORAGE_ROOT" ]]; then echo "artifact root is not a directory: $ARTIFACT_STORAGE_ROOT" >&2; exit 2; fi
mkdir -p "$OUTPUT_DIR"
trap 'if [[ ! -f "$OUTPUT_DIR/SHA256SUMS" ]]; then rm -rf "$OUTPUT_DIR"; fi' EXIT

PG_DATABASE_URL="$(python3 -c 'import sys,urllib.parse as u; p=u.urlsplit(sys.argv[1]); q=u.urlencode([(k,v) for k,v in u.parse_qsl(p.query) if k != "schema"]); print(u.urlunsplit((p.scheme,p.netloc,p.path,q,p.fragment)))' "$DATABASE_URL")"
pg_dump --format=custom --no-owner --no-acl --file "$OUTPUT_DIR/database.dump" "$PG_DATABASE_URL"
DATABASE_URL="$DATABASE_URL" node "$ROOT_DIR/server/scripts/v7-backup-inventory.mjs" \
  --mode export --artifact-root "$ARTIFACT_STORAGE_ROOT" \
  --inventory "$OUTPUT_DIR/inventory.json" --output "$OUTPUT_DIR/inventory.json"
tar -C "$ARTIFACT_STORAGE_ROOT" -czf "$OUTPUT_DIR/artifacts.tar.gz" .
(
  cd "$OUTPUT_DIR"
  shasum -a 256 artifacts.tar.gz database.dump inventory.json > SHA256SUMS
)
trap - EXIT
echo "PL-v7 backup created: $OUTPUT_DIR"
