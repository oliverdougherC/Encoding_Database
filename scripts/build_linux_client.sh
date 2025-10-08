#!/usr/bin/env bash
set -euo pipefail

# Build a Linux standalone client with PyInstaller
# Requirements: python3, pip, pyinstaller; ffmpeg/ffprobe in client/bin/linux

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
BUILD_DIR="$CLIENT_DIR/dist/linux"
BIN_SRC_DIR="$CLIENT_DIR/bin/linux"

echo "[Linux] Preparing build directories..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/bin/linux"

echo "[Linux] Verifying ffmpeg/ffprobe binaries..."
if [[ ! -x "$BIN_SRC_DIR/ffmpeg" ]] || [[ ! -x "$BIN_SRC_DIR/ffprobe" ]]; then
  echo "ERROR: Expected ffmpeg and ffprobe at $BIN_SRC_DIR" >&2
  exit 1
fi

echo "[Linux] Copying resources..."
cp -f "$BIN_SRC_DIR/ffmpeg" "$BUILD_DIR/bin/linux/"
cp -f "$BIN_SRC_DIR/ffprobe" "$BUILD_DIR/bin/linux/"
chmod +x "$BUILD_DIR/bin/linux/ffmpeg" "$BUILD_DIR/bin/linux/ffprobe"
cp -f "$ROOT_DIR/sample.mp4" "$BUILD_DIR/" || true
cp -f "$CLIENT_DIR/presets.json" "$BUILD_DIR/" || true

echo "[Linux] Running PyInstaller..."
cd "$CLIENT_DIR"
pyinstaller \
  --onefile \
  --name encodingdb-client-linux \
  --add-data "$BUILD_DIR/bin/linux:bin/linux" \
  --add-data "$BUILD_DIR/sample.mp4:." \
  --add-data "$BUILD_DIR/presets.json:." \
  main.py

echo "[Linux] Moving artifact to $BUILD_DIR..."
mv -f "$CLIENT_DIR/dist/encodingdb-client-linux" "$BUILD_DIR/encodingdb-client-linux" 2>/dev/null || true
mv -f "$CLIENT_DIR/dist/encodingdb-client-linux"* "$BUILD_DIR/" 2>/dev/null || true

echo "[Linux] Build complete: $BUILD_DIR"

