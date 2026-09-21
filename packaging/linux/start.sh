#!/bin/sh
# EncodingDB launch default: no extra arguments starts the guided menu.
# Every argument is forwarded to the packaged CLI unchanged, and the CLI keeps
# its state under $XDG_STATE_HOME/EncodingDB (or ~/.local/state) — never next to
# this script, so extracting to a read-only location is fine.
set -u

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || {
    printf 'EncodingDB: could not resolve the installation directory.\n' >&2
    exit 66
}
cli="$dir/encodingdb-client-linux"
if [ ! -x "$cli" ]; then
    printf 'EncodingDB: packaged CLI is missing or not executable at %s\n' "$cli" >&2
    printf 'Re-extract the archive with tar (default options preserve the executable bits).\n' >&2
    exit 66
fi
exec "$cli" "$@"
