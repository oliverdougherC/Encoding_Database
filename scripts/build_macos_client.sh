#!/usr/bin/env bash
set -euo pipefail

# Build a macOS standalone client with PyInstaller
# Requirements: python3, pip, pyinstaller installed in a venv; ffmpeg/ffprobe binaries present under client/bin/mac/

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
BUILD_DIR="$CLIENT_DIR/dist/macos"
BIN_SRC_DIR="$CLIENT_DIR/bin/mac"

echo "[macOS] Preparing build directories..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/bin/mac"

echo "[macOS] Verifying ffmpeg/ffprobe binaries..."
if [[ ! -x "$BIN_SRC_DIR/ffmpeg" ]] || [[ ! -x "$BIN_SRC_DIR/ffprobe" ]]; then
  echo "ERROR: Expected ffmpeg and ffprobe at $BIN_SRC_DIR" >&2
  exit 1
fi

echo "[macOS] Copying resources..."
cp -f "$BIN_SRC_DIR/ffmpeg" "$BUILD_DIR/bin/mac/"
cp -f "$BIN_SRC_DIR/ffprobe" "$BUILD_DIR/bin/mac/"
chmod +x "$BUILD_DIR/bin/mac/ffmpeg" "$BUILD_DIR/bin/mac/ffprobe"
cp -f "$ROOT_DIR/sample.mp4" "$BUILD_DIR/" || true
cp -f "$CLIENT_DIR/presets.json" "$BUILD_DIR/" || true

echo "[macOS] Running PyInstaller..."
cd "$CLIENT_DIR"
pyinstaller \
  --onefile \
  --name encodingdb-client-macos \
  --add-data "$BUILD_DIR/bin/mac:bin/mac" \
  --add-data "$BUILD_DIR/sample.mp4:." \
  --add-data "$BUILD_DIR/presets.json:." \
  main.py

echo "[macOS] Moving artifact to $BUILD_DIR..."
mv -f "$CLIENT_DIR/dist/encodingdb-client-macos" "$BUILD_DIR/encodingdb-client-macos" 2>/dev/null || true
mv -f "$CLIENT_DIR/dist/encodingdb-client-macos"* "$BUILD_DIR/" 2>/dev/null || true

echo "[macOS] Build complete: $BUILD_DIR"

