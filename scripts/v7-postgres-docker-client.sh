#!/usr/bin/env bash
# Portable PostgreSQL16 clients; a work-root bind preserves host file arguments.
set -Eeuo pipefail
client="$(basename "$0")"
if [[ "$client" != pg_dump && "$client" != pg_restore ]]; then client="${1:-}"; shift; fi
[[ "$client" == pg_dump || "$client" == pg_restore ]] || { echo 'expected pg_dump or pg_restore' >&2; exit 2; }
: "${V7_BACKUP_DOCKER_WORK_ROOT:?V7_BACKUP_DOCKER_WORK_ROOT is required}"
[[ "$V7_BACKUP_DOCKER_WORK_ROOT" == /* && -d "$V7_BACKUP_DOCKER_WORK_ROOT" ]] || { echo 'backup Docker work root must be an existing absolute directory' >&2; exit 2; }
network="${V7_BACKUP_DOCKER_NETWORK:-host}"
# The isolated restore script publishes its fresh DB only on host loopback.
if [[ "$client" == pg_restore ]]; then network=host; fi
exec docker run --rm --cpus "${V7_BACKUP_DOCKER_CPUS:-2}" --network "$network" --user "$(id -u):$(id -g)" \
  -v "$V7_BACKUP_DOCKER_WORK_ROOT:$V7_BACKUP_DOCKER_WORK_ROOT" \
  "${V7_BACKUP_POSTGRES_IMAGE:-postgres:16-alpine}" "$client" "$@"
