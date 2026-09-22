#!/bin/sh
# EncodingDB guided launch wrapper (run by Terminal.app).
#
# Resolution is strictly relative to this file, so the app works from a read-only
# DMG, /Applications, or any relocated path (spaces, Unicode, shell metacharacters
# included). Nothing is copied or written next to the bundle; the CLI itself keeps
# its state under ~/Library/Application Support/EncodingDB and its cache under
# ~/Library/Caches/EncodingDB.
set -u

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || {
    printf 'EncodingDB: could not resolve the application directory.\n' >&2
    exit 66
}
cli="$dir/encodingdb"
if [ ! -x "$cli" ]; then
    printf 'EncodingDB: packaged CLI is missing or not executable at %s\n' "$cli" >&2
    printf 'Re-download the DMG and drag EncodingDB.app to /Applications again.\n' >&2
    exit 66
fi

"$cli" "$@"
status=$?
if [ "$status" -ne 0 ]; then
    printf '\nEncodingDB exited with status %s.\n' "$status"
    # Keep the window readable on failure; a clean guided exit closes normally.
    if [ -t 0 ] && [ -z "${ENCODINGDB_NO_HOLD:-}" ]; then
        printf 'Press Return to close this window... '
        IFS= read -r _ || true
    fi
fi
exit "$status"
