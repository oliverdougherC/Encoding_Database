
#!/usr/bin/env bash
set -e
set -u
# Enable pipefail if supported (older shells may not support it)
set -o pipefail 2>/dev/null || true

# MSYS2/Git Bash: ignore CR characters if the file has CRLF endings
export SHELLOPTS
set -o igncr 2>/dev/null || true

# Build a Windows standalone client with PyInstaller.
# Run this from Windows PowerShell/CMD or from Git Bash/WSL that can invoke Windows Python (py launcher).
# Requires: Windows Python ("py" launcher) with PyInstaller installed, and ffmpeg/ffprobe in client/bin/win.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
BUILD_DIR="$CLIENT_DIR/dist/windows"
BIN_SRC_DIR="$CLIENT_DIR/bin/win"
VENV_SCRIPTS_DIR="$ROOT_DIR/.myenv/Scripts"

# Optional: set VERBOSE=1 to enable shell tracing; set PAUSE_ON_EXIT=1 to pause at end
if [[ "${VERBOSE:-0}" == "1" ]]; then
  set -x
fi

echo "[Windows] Preparing build directories..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/bin/win"

# Capture full build output to a log file for debugging even if the window closes
LOG_FILE="$BUILD_DIR/build.log"
: > "$LOG_FILE" || true
# tee may not be available in all shells, but is present in Git Bash/MSYS2; ignore failure
exec > >(tee -a "$LOG_FILE") 2>&1 || true

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

# Prefer local Windows venv tools if present
if [[ -x "$VENV_SCRIPTS_DIR/pyinstaller.exe" ]]; then
  echo "[Windows] Using local venv PyInstaller: $VENV_SCRIPTS_DIR/pyinstaller.exe"
  PYI_CMD=("$VENV_SCRIPTS_DIR/pyinstaller.exe")
elif [[ -x "$VENV_SCRIPTS_DIR/python.exe" ]]; then
  echo "[Windows] Using local venv Python: $VENV_SCRIPTS_DIR/python.exe"
  PYI_CMD=("$VENV_SCRIPTS_DIR/python.exe" -m PyInstaller)
else
  # Pick Windows Python launcher if available to ensure a native .exe is produced
  PY_CMD=( )
  if command -v py >/dev/null 2>&1; then
    PY_CMD=(py -3)
  elif command -v py.exe >/dev/null 2>&1; then
    PY_CMD=(py.exe -3)
  elif command -v python.exe >/dev/null 2>&1; then
    PY_CMD=(python.exe)
  else
    # Fallback (may build for non-Windows if not using Windows Python!)
    PY_CMD=(python)
  fi
  echo "[Windows] Using Python: ${PY_CMD[*]}"
  # Verify PyInstaller is available in this interpreter
  if ! "${PY_CMD[@]}" -m PyInstaller --version >/dev/null 2>&1; then
    echo "ERROR: PyInstaller is not installed for this Python interpreter (${PY_CMD[*]})." >&2
    echo "       Install with: ${PY_CMD[*]} -m pip install pyinstaller" >&2
    exit 3
  fi
  PYI_CMD=("${PY_CMD[@]}" -m PyInstaller)
fi

"${PYI_CMD[@]}" \
  --clean \
  --onefile \
  --name encodingdb-client-windows \
  --add-data "bin/win/ffmpeg.exe;bin/win" \
  --add-data "bin/win/ffprobe.exe;bin/win" \
  --add-data "../sample.mp4;." \
  --add-data "presets.json;." \
  main.py

echo "[Windows] Moving artifact to $BUILD_DIR..."
if [[ -f "$CLIENT_DIR/dist/encodingdb-client-windows.exe" ]]; then
  mv -f "$CLIENT_DIR/dist/encodingdb-client-windows.exe" "$BUILD_DIR/encodingdb-client-windows.exe"
elif [[ -d "$CLIENT_DIR/dist/encodingdb-client-windows" ]]; then
  mv -f "$CLIENT_DIR/dist/encodingdb-client-windows" "$BUILD_DIR/"
else
  echo "ERROR: PyInstaller did not produce encodingdb-client-windows.exe. Ensure Windows Python (py -3) is used and PyInstaller is installed." >&2
  exit 2
fi

echo "[Windows] Build complete: $BUILD_DIR"
echo "[Windows] Build log saved to: $LOG_FILE"

# Optional pause for double-click runs (set PAUSE_ON_EXIT=1)
if [[ "${PAUSE_ON_EXIT:-0}" == "1" ]]; then
  read -r -p "Press Enter to close..." _
fi

