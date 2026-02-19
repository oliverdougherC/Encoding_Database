#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
BIN_DIR="$CLIENT_DIR/bin/mac"
APP_NAME="encodingdb-client-macos"
ENTRYPOINT="$CLIENT_DIR/_pyinstaller_entry.py"
BUILD_ROOT="$ROOT_DIR/.build/clients/macos"
LEGACY_DIST_DIR="$CLIENT_DIR/dist/macos"
PYI_DIST_DIR="$BUILD_ROOT/dist"
PYI_WORK_DIR="$BUILD_ROOT/work"
PYI_SPEC_DIR="$BUILD_ROOT/spec"
OUTPUT_PATH="$ROOT_DIR/$APP_NAME"

log() {
  echo "[macOS] $*"
}

die() {
  echo "[macOS] ERROR: $*" >&2
  exit 1
}

if [[ ! -x "$BIN_DIR/ffmpeg" ]] || [[ ! -x "$BIN_DIR/ffprobe" ]]; then
  die "Expected executable ffmpeg and ffprobe at $BIN_DIR"
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

if command -v pyinstaller >/dev/null 2>&1; then
  PYI_CMD=(pyinstaller)
elif python3 -m PyInstaller --version >/dev/null 2>&1; then
  PYI_CMD=(python3 -m PyInstaller)
else
  die "PyInstaller not found. Install it with: python3 -m pip install pyinstaller"
fi

log "Preparing output directory..."
rm -rf "$BUILD_ROOT"
rm -rf "$LEGACY_DIST_DIR"
rm -f "$OUTPUT_PATH"
rm -f "$ROOT_DIR/dist/$APP_NAME"
rm -rf "$ROOT_DIR/build/$APP_NAME"
mkdir -p "$PYI_DIST_DIR" "$PYI_WORK_DIR" "$PYI_SPEC_DIR"

log "Running PyInstaller..."
cd "$ROOT_DIR"
"${PYI_CMD[@]}" \
  --clean \
  --onefile \
  --name "$APP_NAME" \
  --distpath "$PYI_DIST_DIR" \
  --workpath "$PYI_WORK_DIR" \
  --specpath "$PYI_SPEC_DIR" \
  --paths "$ROOT_DIR" \
  --add-data "$BIN_DIR/ffmpeg:bin/mac" \
  --add-data "$BIN_DIR/ffprobe:bin/mac" \
  --add-data "$ROOT_DIR/sample.mp4:." \
  --add-data "$CLIENT_DIR/presets.json:." \
  "$ENTRYPOINT"

if [[ ! -f "$PYI_DIST_DIR/$APP_NAME" ]]; then
  die "Build output not found at $PYI_DIST_DIR/$APP_NAME"
fi

log "Placing executable in repository root..."
mv -f "$PYI_DIST_DIR/$APP_NAME" "$OUTPUT_PATH"
chmod +x "$OUTPUT_PATH" || true
log "Build complete: $OUTPUT_PATH"
log "Hidden build artifacts: $BUILD_ROOT"
