#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_URL="${SERVER_URL:-http://127.0.0.1:3001}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:3100}"
SOFTWARE_ENCODER="${SOFTWARE_ENCODER:-libx264}"
HARDWARE_ENCODER="${HARDWARE_ENCODER:-}"
SOFTWARE_CRF="${SOFTWARE_CRF:-24}"
HARDWARE_TARGET_BITRATE_KBPS="${HARDWARE_TARGET_BITRATE_KBPS:-2500}"
SUITE_CLIP="${SUITE_CLIP:-sports-action-960x540-24p}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$ROOT_DIR/.test-reports/pl-v7-e2e}"
FAULT_PROXY_PORT="${FAULT_PROXY_PORT:-3011}"
BUILD_CLIENT=1
FAULT_PROXY_PID=""

cleanup() {
  if [[ -n "$FAULT_PROXY_PID" ]] && kill -0 "$FAULT_PROXY_PID" 2>/dev/null; then
    kill "$FAULT_PROXY_PID" 2>/dev/null || true
    wait "$FAULT_PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

usage() {
  echo "Usage: scripts/certify-v7-e2e.sh --hardware-encoder NAME [options]"
  echo "  --software-encoder NAME  Software encoder (default: libx264)"
  echo "  --hardware-encoder NAME  Required real hardware encoder"
  echo "  --software-crf INTEGER   Native software CRF (default: 24)"
  echo "  --hardware-target-bitrate-kbps INTEGER  Native hardware target bitrate (default: 2500)"
  echo "  --suite-clip ID          Canonical representative clip (default: sports-action-960x540-24p)"
  echo "  --server-url URL         Running v7 server (default: http://127.0.0.1:3001)"
  echo "  --frontend-url URL       Running frontend wired to that server (default: http://127.0.0.1:3100)"
  echo "  --evidence-root PATH     Retained evidence parent"
  echo "  --skip-build             Use an already packaged client"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --software-encoder) SOFTWARE_ENCODER="${2:?missing software encoder}"; shift 2 ;;
    --hardware-encoder) HARDWARE_ENCODER="${2:?missing hardware encoder}"; shift 2 ;;
    --software-crf) SOFTWARE_CRF="${2:?missing software CRF}"; shift 2 ;;
    --hardware-target-bitrate-kbps) HARDWARE_TARGET_BITRATE_KBPS="${2:?missing hardware target bitrate}"; shift 2 ;;
    --suite-clip) SUITE_CLIP="${2:?missing suite clip ID}"; shift 2 ;;
    --server-url) SERVER_URL="${2:?missing server URL}"; shift 2 ;;
    --frontend-url) FRONTEND_URL="${2:?missing frontend URL}"; shift 2 ;;
    --evidence-root) EVIDENCE_ROOT="${2:?missing evidence root}"; shift 2 ;;
    --skip-build) BUILD_CLIENT=0; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$HARDWARE_ENCODER" ]] || { echo "--hardware-encoder is required; hardware evidence is never simulated" >&2; exit 2; }
[[ "$SOFTWARE_ENCODER" != "$HARDWARE_ENCODER" ]] || { echo "Software and hardware encoders must be distinct" >&2; exit 2; }
[[ "$SOFTWARE_CRF" =~ ^[0-9]+$ ]] && (( SOFTWARE_CRF >= 0 && SOFTWARE_CRF <= 63 )) \
  || { echo "--software-crf must be an integer from 0 through 63" >&2; exit 2; }
[[ "$HARDWARE_TARGET_BITRATE_KBPS" =~ ^[1-9][0-9]*$ ]] \
  || { echo "--hardware-target-bitrate-kbps must be a positive integer" >&2; exit 2; }
[[ -n "${DATABASE_URL:-}" ]] || { echo "DATABASE_URL is required for evidence-chain verification" >&2; exit 2; }

BRANCH="$(git -C "$ROOT_DIR" branch --show-current)"
COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
[[ "$BRANCH" == "beta" ]] || { echo "Certification must run on beta, not $BRANCH" >&2; exit 2; }
if [[ -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=all | grep -v '^.. \.omx/' || true)" ]]; then
  echo "Certification requires a clean beta commit (OMX runtime state is ignored)" >&2
  exit 2
fi

case "$(uname -s)" in
  Darwin)
    BUILD_SCRIPT="$ROOT_DIR/scripts/build_macos_client.sh"
    CLIENT_BINARY="$ROOT_DIR/encodingdb-client-macos"
    BUNDLED_FFMPEG="$ROOT_DIR/client/bin/mac/ffmpeg"
    ;;
  Linux)
    BUILD_SCRIPT="$ROOT_DIR/scripts/build_linux_client.sh"
    CLIENT_BINARY="$ROOT_DIR/encodingdb-client-linux"
    BUNDLED_FFMPEG="$ROOT_DIR/client/bin/linux/ffmpeg"
    ;;
  *) echo "No certification packaging path for $(uname -s)" >&2; exit 2 ;;
esac

[[ -x "$BUNDLED_FFMPEG" ]] || { echo "Bundled ffmpeg missing: $BUNDLED_FFMPEG" >&2; exit 2; }
"$BUNDLED_FFMPEG" -hide_banner -encoders 2>/dev/null | grep -Eq "[[:space:]]${SOFTWARE_ENCODER}[[:space:]]" \
  || { echo "Software encoder unavailable in packaged ffmpeg: $SOFTWARE_ENCODER" >&2; exit 2; }
"$BUNDLED_FFMPEG" -hide_banner -encoders 2>/dev/null | grep -Eq "[[:space:]]${HARDWARE_ENCODER}[[:space:]]" \
  || { echo "Hardware encoder unavailable in packaged ffmpeg: $HARDWARE_ENCODER" >&2; exit 2; }

curl --fail --silent --show-error "$SERVER_URL/health/ready" >/dev/null
curl --fail --silent --show-error "$FRONTEND_URL/leaderboards" >/dev/null

if [[ "$BUILD_CLIENT" -eq 1 ]]; then
  "$BUILD_SCRIPT"
fi
[[ -x "$CLIENT_BINARY" ]] || { echo "Packaged client missing: $CLIENT_BINARY" >&2; exit 2; }

RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$EVIDENCE_ROOT/${COMMIT}-${RUN_STAMP}"
mkdir -p "$RUN_DIR"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CLIENT_SHA256="$(shasum -a 256 "$CLIENT_BINARY" | awk '{print $1}')"
QUEUE_DIR="$RUN_DIR/client-queue"
mkdir -p "$QUEUE_DIR"
FAULT_EVIDENCE="$RUN_DIR/upload-interruption.json"
FAULT_PROXY_URL="http://127.0.0.1:${FAULT_PROXY_PORT}"
UPSTREAM_URL="$SERVER_URL" PORT="$FAULT_PROXY_PORT" EVIDENCE_PATH="$FAULT_EVIDENCE" \
  node "$ROOT_DIR/scripts/v7-upload-fault-proxy.mjs" >"$RUN_DIR/upload-fault-proxy.log" 2>&1 &
FAULT_PROXY_PID=$!
for _ in $(seq 1 50); do
  curl --fail --silent "$FAULT_PROXY_URL/health/ready" >/dev/null 2>&1 && break
  kill -0 "$FAULT_PROXY_PID" 2>/dev/null || { echo "Upload fault proxy exited" >&2; exit 1; }
  sleep 0.1
done
curl --fail --silent --show-error "$FAULT_PROXY_URL/health/ready" >/dev/null

run_path() {
  local kind="$1"
  local encoder="$2"
  local submission_url="$3"
  local log="$RUN_DIR/${kind}-client.log"
  local -a native_rate_control=(--crf "$SOFTWARE_CRF")
  if [[ "$kind" == "hardware" ]]; then
    native_rate_control=(--target-bitrate-kbps "$HARDWARE_TARGET_BITRATE_KBPS")
  fi
  echo "Running packaged $kind path with $encoder"
  ENCODINGDB_PROTOCOL_SEED=701 \
    "$CLIENT_BINARY" \
      --base-url "$submission_url" \
      --codec "$encoder" \
      --v7-suite-clip "$SUITE_CLIP" \
      --presets fast \
      "${native_rate_control[@]}" \
      --retries 1 \
      --queue-dir "$QUEUE_DIR" \
      >"$log" 2>&1
  if find "$QUEUE_DIR" -maxdepth 1 -type f -name '*.json' -print -quit | grep -q .; then
    echo "$kind client retained an upload/submission in its retry queue" >&2
    exit 1
  fi
}

run_path software "$SOFTWARE_ENCODER" "$FAULT_PROXY_URL"
grep -q 'Queued payload for retry' "$RUN_DIR/software-client.log" \
  || { echo "Software path did not observe the injected upload interruption" >&2; exit 1; }
grep -q 'Submitted 1 queued payload(s)' "$RUN_DIR/software-client.log" \
  || { echo "Packaged client did not recover its queued upload" >&2; exit 1; }
run_path hardware "$HARDWARE_ENCODER" "$SERVER_URL"
SOFTWARE_IMPLEMENTATION="$SOFTWARE_ENCODER"
HARDWARE_IMPLEMENTATION="${HARDWARE_ENCODER##*_}"

cat >"$RUN_DIR/execution.json" <<EOF
{
  "evidenceVersion": "encodingdb-pl-v7-e2e/v2",
  "branch": "$BRANCH",
  "commit": "$COMMIT",
  "startedAt": "$STARTED_AT",
  "completedClientRunsAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "packagedClient": { "path": "$CLIENT_BINARY", "sha256": "$CLIENT_SHA256" },
  "suiteClip": "$SUITE_CLIP",
  "softwareEncoder": "$SOFTWARE_ENCODER",
  "softwareRateControl": { "mode": "CRF", "crf": $SOFTWARE_CRF },
  "hardwareEncoder": "$HARDWARE_ENCODER",
  "hardwareRateControl": { "mode": "TARGET_BITRATE", "targetBitrateKbps": $HARDWARE_TARGET_BITRATE_KBPS },
  "uploadInterruptionEvidence": "upload-interruption.json",
  "softwareImplementation": "$SOFTWARE_IMPLEMENTATION",
  "hardwareImplementation": "$HARDWARE_IMPLEMENTATION"
}
EOF

(cd "$ROOT_DIR/server" && node scripts/verify-v7-e2e.mjs \
  --since "$STARTED_AT" \
  --software-encoder "$SOFTWARE_IMPLEMENTATION" \
  --hardware-encoder "$HARDWARE_IMPLEMENTATION" \
  --server-url "$SERVER_URL" \
  --frontend-url "$FRONTEND_URL" \
  --fault-evidence "$FAULT_EVIDENCE" \
  --output "$RUN_DIR/authority-chain.json")

find "$RUN_DIR" -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 >"$RUN_DIR/SHA256SUMS"
echo "PL v7 E2E certification passed: $RUN_DIR"
