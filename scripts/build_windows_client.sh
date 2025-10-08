#!/usr/bin/env bash
set -euo pipefail

# Build a Windows standalone client with PyInstaller (invoke from WSL or Git Bash with access to Windows toolchain)
# Requires: Python for Windows, PyInstaller, and ffmpeg/ffprobe in client/bin/win

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
BUILD_DIR="$CLIENT_DIR/dist/windows"
BIN_SRC_DIR="$CLIENT_DIR/bin/win"

echo "[Windows] Preparing build directories..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/bin/win"

echo "[Windows] Verifying ffmpeg/ffprobe binaries..."
if [[ ! -f "$BIN_SRC_DIR/ffmpeg.exe" ]] || [[ ! -f "$BIN_SRC_DIR/ffprobe.exe" ]]; then
  echo "ERROR: Expected ffmpeg.exe and ffprobe.exe at $BIN_SRC_DIR" >&2
  exit 1
fi

echo "[Windows] Copying resources..."
cp -f "$BIN_SRC_DIR/ffmpeg.exe" "$BUILD_DIR/bin/win/"
cp -f "$BIN_SRC_DIR/ffprobe.exe" "$BUILD_DIR/bin/win/"
cp -f "$ROOT_DIR/sample.mp4" "$BUILD_DIR/" || true
cp -f "$CLIENT_DIR/presets.json" "$BUILD_DIR/" || true

echo "[Windows] Running PyInstaller..."
cd "$CLIENT_DIR"
pyinstaller \
  --onefile \
  --name encodingdb-client-windows \
  --add-data "$BUILD_DIR/bin/win;bin/win" \
  --add-data "$BUILD_DIR/sample.mp4;." \
  --add-data "$BUILD_DIR/presets.json;." \
  main.py

echo "[Windows] Moving artifact to $BUILD_DIR..."
mv -f "$CLIENT_DIR/dist/encodingdb-client-windows.exe" "$BUILD_DIR/encodingdb-client-windows.exe" 2>/dev/null || true
mv -f "$CLIENT_DIR/dist/encodingdb-client-windows"* "$BUILD_DIR/" 2>/dev/null || true

echo "[Windows] Build complete: $BUILD_DIR"

