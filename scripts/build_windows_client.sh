#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
BIN_DIR="$CLIENT_DIR/bin/win"
APP_NAME="encodingdb-client-windows"
ENTRYPOINT="$CLIENT_DIR/_pyinstaller_entry.py"
BUILD_ROOT="$ROOT_DIR/.build/clients/windows"
LEGACY_DIST_DIR="$CLIENT_DIR/dist/windows"
PYI_DIST_DIR="$BUILD_ROOT/dist"
PYI_WORK_DIR="$BUILD_ROOT/work"
PYI_SPEC_DIR="$BUILD_ROOT/spec"
OUTPUT_PATH="$ROOT_DIR/$APP_NAME.exe"

# Optional: set VERBOSE=1 to enable shell tracing; set PAUSE_ON_EXIT=1 to pause at end
if [[ "${VERBOSE:-0}" == "1" ]]; then
  set -x
fi

log() {
  echo "[Windows] $*"
}

die() {
  echo "[Windows] ERROR: $*" >&2
  exit 1
}

if [[ ! -f "$BIN_DIR/ffmpeg.exe" ]] || [[ ! -f "$BIN_DIR/ffprobe.exe" ]]; then
  die "Expected ffmpeg.exe and ffprobe.exe at $BIN_DIR"
fi
if [[ ! -f "$ROOT_DIR/sample.mp4" ]]; then
  die "Missing $ROOT_DIR/sample.mp4"
fi
if [[ ! -f "$CLIENT_DIR/presets.json" ]]; then
  die "Missing $CLIENT_DIR/presets.json"
fi
if [[ ! -f "$ENTRYPOINT" ]]; then
  die "Missing entrypoint: $ENTRYPOINT"
fi

log "Preparing build directories..."
rm -rf "$BUILD_ROOT"
rm -rf "$LEGACY_DIST_DIR"
rm -f "$OUTPUT_PATH"
rm -f "$ROOT_DIR/dist/$APP_NAME.exe"
rm -rf "$ROOT_DIR/build/$APP_NAME"
mkdir -p "$PYI_DIST_DIR" "$PYI_WORK_DIR" "$PYI_SPEC_DIR"

# Capture build output for troubleshooting double-click or CI runs.
LOG_FILE="$BUILD_ROOT/build.log"
: > "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

PY_CMD=()
if command -v py >/dev/null 2>&1; then
  PY_CMD=(py -3)
elif command -v py.exe >/dev/null 2>&1; then
  PY_CMD=(py.exe -3)
elif command -v python.exe >/dev/null 2>&1; then
  PY_CMD=(python.exe)
elif [[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* ]] && command -v python >/dev/null 2>&1; then
  PY_CMD=(python)
else
  die "No Windows Python interpreter found. Use py/py.exe/python.exe from Windows."
fi

log "Using Python command: ${PY_CMD[*]}"
if ! "${PY_CMD[@]}" -m PyInstaller --version >/dev/null 2>&1; then
  die "PyInstaller is not installed for this interpreter. Install with: ${PY_CMD[*]} -m pip install pyinstaller"
fi

log "Running PyInstaller..."
cd "$ROOT_DIR"
"${PY_CMD[@]}" -m PyInstaller \
  --clean \
  --onefile \
  --name "$APP_NAME" \
  --distpath "$PYI_DIST_DIR" \
  --workpath "$PYI_WORK_DIR" \
  --specpath "$PYI_SPEC_DIR" \
  --paths "$ROOT_DIR" \
  --add-data "client/bin/win/ffmpeg.exe;bin/win" \
  --add-data "client/bin/win/ffprobe.exe;bin/win" \
  --add-data "sample.mp4;." \
  --add-data "client/presets.json;." \
  "$ENTRYPOINT"

if [[ ! -f "$PYI_DIST_DIR/$APP_NAME.exe" ]]; then
  die "Build output not found at $PYI_DIST_DIR/$APP_NAME.exe"
fi

log "Placing executable in repository root..."
mv -f "$PYI_DIST_DIR/$APP_NAME.exe" "$OUTPUT_PATH"
log "Build complete: $OUTPUT_PATH"
log "Build log saved to: $LOG_FILE"
log "Hidden build artifacts: $BUILD_ROOT"

# Optional pause for double-click runs (set PAUSE_ON_EXIT=1)
if [[ "${PAUSE_ON_EXIT:-0}" == "1" ]]; then
  read -r -p "Press Enter to close..." _
fi
