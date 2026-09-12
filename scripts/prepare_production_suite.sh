#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# This is also the supported preparation entry point before a direct Compose
# build. No host Python, pip, client installation, or media runtime is needed.
cache="${DEPLOY_SUITE_CACHE_DIR:-$ROOT_DIR/.build/final-suite-cache}"
pack="${DEPLOY_SUITE_PACK_PATH:-}"
url="${DEPLOY_SUITE_PACK_URL:-}"
if [[ -n "$pack" && -n "$url" ]]; then
  echo '[suite-preparation] Choose only DEPLOY_SUITE_PACK_PATH or DEPLOY_SUITE_PACK_URL.' >&2
  exit 2
fi
if [[ -n "$pack" && ! -f "$pack" ]]; then
  echo '[suite-preparation] suite pack not found at DEPLOY_SUITE_PACK_PATH' >&2
  exit 1
fi
mkdir -p "$cache"
cache="$(cd "$cache" && pwd)"
args=(--repo-root /workspace --cache-dir /suite-cache)
mounts=(--mount "type=bind,src=$ROOT_DIR,dst=/workspace"
        --mount "type=bind,src=$cache,dst=/suite-cache")
if [[ -n "$pack" ]]; then
  pack="$(cd "$(dirname "$pack")" && pwd)/$(basename "$pack")"
  mounts+=(--mount "type=bind,src=$pack,dst=/suite-input/pack.tar.gz,readonly")
  args+=(--pack-path /suite-input/pack.tar.gz)
elif [[ -n "$url" ]]; then
  args+=(--pack-url "$url")
fi

# Use an immutable image ID, so concurrent preparations cannot change this run's
# runtime by moving a shared image tag. The tiny build context excludes assets,
# caches, .env and unrelated checkout contents.
iid="$(mktemp)"
trap 'rm -f "$iid"' EXIT
docker build --iidfile "$iid" -f scripts/suite-preparation.Dockerfile .
docker run --rm --user "$(id -u):$(id -g)" "${mounts[@]}" "$(cat "$iid")" "${args[@]}"
