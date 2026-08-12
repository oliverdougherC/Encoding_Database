#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
BUNDLE_DIR="${ENCODINGDB_RUNTIME_BUNDLE_DIR:-$CLIENT_DIR/bin/mac}"
FFMPEG_PATH="${ENCODINGDB_FFMPEG_PATH:-$BUNDLE_DIR/ffmpeg}"
FFPROBE_PATH="${ENCODINGDB_FFPROBE_PATH:-$BUNDLE_DIR/ffprobe}"
APP_NAME="encodingdb-client-macos"
ENTRYPOINT="$CLIENT_DIR/_pyinstaller_entry.py"
BUILD_ROOT="$ROOT_DIR/.build/clients/macos"
LEGACY_DIST_DIR="$CLIENT_DIR/dist/macos"
PYI_DIST_DIR="$BUILD_ROOT/dist"
PYI_WORK_DIR="$BUILD_ROOT/work"
PYI_SPEC_DIR="$BUILD_ROOT/spec"
RUNTIME_RESOURCE_DIR="$BUILD_ROOT/runtime_resources"
OUTPUT_PATH="$ROOT_DIR/$APP_NAME"
BUILD_REQUIREMENTS="$CLIENT_DIR/requirements-build.txt"

log() {
  echo "[macOS] $*"
}

die() {
  echo "[macOS] ERROR: $*" >&2
  exit 1
}

if [[ ! -x "$FFMPEG_PATH" ]] || [[ ! -x "$FFPROBE_PATH" ]]; then
  die "Expected executable ffmpeg and ffprobe at $BUNDLE_DIR"
fi
if [[ ! -f "$CLIENT_DIR/presets.json" ]]; then
  die "Missing $CLIENT_DIR/presets.json"
fi
if [[ ! -f "$CLIENT_DIR/resources/test_suite_v1/manifest.json" ]]; then
  die "Missing $CLIENT_DIR/resources/test_suite_v1/manifest.json"
fi
if [[ ! -f "$CLIENT_DIR/resources/vmaf/manifest.json" ]]; then
  die "Missing $CLIENT_DIR/resources/vmaf/manifest.json"
fi
if [[ ! -f "$CLIENT_DIR/resources/vmaf/vmaf_v1.0.16_3d0h.json" ]]; then
  die "Missing $CLIENT_DIR/resources/vmaf/vmaf_v1.0.16_3d0h.json"
fi
if [[ ! -f "$CLIENT_DIR/resources/runtime/ffmpeg-lock.json" ]]; then
  die "Missing $CLIENT_DIR/resources/runtime/ffmpeg-lock.json"
fi
if [[ ! -f "$ENTRYPOINT" ]]; then
  die "Missing entrypoint: $ENTRYPOINT"
fi
python3 "$ROOT_DIR/scripts/verify_suite_assets.py" "$CLIENT_DIR/resources/test_suite_v1" \
  || die "Canonical suite asset verification failed"

log "Preparing output directory..."
rm -rf "$BUILD_ROOT"
rm -rf "$LEGACY_DIST_DIR"
rm -f "$OUTPUT_PATH"
rm -f "$ROOT_DIR/dist/$APP_NAME"
rm -rf "$ROOT_DIR/build/$APP_NAME"
mkdir -p "$PYI_DIST_DIR" "$PYI_WORK_DIR" "$PYI_SPEC_DIR"
python3 -m venv "$BUILD_ROOT/venv"
"$BUILD_ROOT/venv/bin/python" -m pip install --disable-pip-version-check -r "$BUILD_REQUIREMENTS" >/dev/null
PYI_CMD=("$BUILD_ROOT/venv/bin/python" -m PyInstaller)
REGISTER_ARGS=()
if [[ "${ENCODINGDB_REGISTER_RUNTIME:-0}" == "1" ]]; then REGISTER_ARGS+=(--update); fi
python3 "$ROOT_DIR/scripts/register_ffmpeg_runtime.py" \
  --platform mac \
  --ffmpeg-path "$FFMPEG_PATH" \
  --ffprobe-path "$FFPROBE_PATH" \
  "${REGISTER_ARGS[@]}" \
  --stage-runtime-dir "$RUNTIME_RESOURCE_DIR" \
  >/dev/null

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
  --add-data "$FFMPEG_PATH:bin/mac" \
  --add-data "$FFPROBE_PATH:bin/mac" \
  --add-data "$CLIENT_DIR/presets.json:." \
  --add-data "$CLIENT_DIR/resources/test_suite_v1:resources/test_suite_v1" \
  --add-data "$RUNTIME_RESOURCE_DIR:resources/runtime" \
  --add-data "$CLIENT_DIR/resources/vmaf:resources/vmaf" \
  "$ENTRYPOINT"

if [[ ! -f "$PYI_DIST_DIR/$APP_NAME" ]]; then
  die "Build output not found at $PYI_DIST_DIR/$APP_NAME"
fi

log "Placing executable in repository root..."
mv -f "$PYI_DIST_DIR/$APP_NAME" "$OUTPUT_PATH"
chmod +x "$OUTPUT_PATH" || true
python3 "$ROOT_DIR/scripts/release_manifest_lib.py" \
  --artifact-path "$OUTPUT_PATH" \
  --platform mac \
  --ffmpeg-path "$FFMPEG_PATH" \
  --ffprobe-path "$FFPROBE_PATH" \
  --output-dir "$ROOT_DIR"
log "Build complete: $OUTPUT_PATH"
log "Hidden build artifacts: $BUILD_ROOT"
