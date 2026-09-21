#!/bin/sh
# EncodingDB.app executable: opens the guided terminal interface in Terminal.app
# so the session gets a real TTY (readable output, working stdin prompts) instead
# of an invisible background process.
#
# Path resolution is relative to $0 and fully quoted, so the bundle works when
# relocated, when mounted read-only from a DMG, and under App Translocation.
# ENCODINGDB_OPEN_BIN exists only so packaging regression tests can intercept the
# Terminal hand-off; ENCODINGDB_SUPPRESS_ALERT keeps the failure alert out of
# headless CI. Leave both unset in normal use.
set -u

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || dir=""
wrapper="$dir/../Resources/EncodingDB.command"
if resources=$(CDPATH= cd -- "$dir/../Resources" 2>/dev/null && pwd -P); then
    wrapper="$resources/EncodingDB.command"
fi
open_bin=${ENCODINGDB_OPEN_BIN:-/usr/bin/open}
if [ ! -x "$open_bin" ]; then
    open_bin=$(command -v open 2>/dev/null || true)
fi

if [ -f "$wrapper" ] && [ -n "$open_bin" ]; then
    if "$open_bin" "$wrapper"; then
        exit 0
    fi
fi

# Never exit silently: surface a real error if Terminal could not be engaged.
detail="EncodingDB could not open Terminal to start the guided interface.
Expected wrapper: $wrapper
Drag EncodingDB.app to /Applications and launch it again from there."
if [ -z "${ENCODINGDB_SUPPRESS_ALERT:-}" ] && [ -x /usr/bin/osascript ]; then
    /usr/bin/osascript - "$detail" >/dev/null 2>&1 <<'OSA' || true
on run argv
    display alert "EncodingDB could not start" message (item 1 of argv)
end run
OSA
fi
printf '%s\n' "$detail" >&2
exit 72
