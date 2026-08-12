#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

declare -a REQUESTED_CHECKS=("$@")
if [[ "${#REQUESTED_CHECKS[@]}" -eq 0 ]]; then
  REQUESTED_CHECKS=(
    hygiene
    metadata
    frontend
    server
    client
    stack-smoke
    migrations
    production-compose
    suite-contract
    ops-hooks
    final-suite
  )
fi

log() {
  echo "[release-preflight] $*"
}

die() {
  echo "[release-preflight] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

run_root() {
  log "RUN $*"
  (
    cd "$ROOT_DIR"
    "$@"
  )
}

run_shell() {
  log "RUN $*"
  (
    cd "$ROOT_DIR"
    bash -lc "$*"
  )
}

json_field() {
  local file="$1"
  local field="$2"
  python3 - "$file" "$field" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
value = payload
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}

check_hygiene() {
  require_cmd git
  local forbidden
  forbidden="$(git ls-files .omx nginx/certs/selfsigned.crt nginx/certs/selfsigned.key sample.mp4 | sed '/^$/d' || true)"
  [[ -z "$forbidden" ]] || die "tracked generated/runtime files remain:\n$forbidden"

  for path in .omx/context/ .omx/logs/ .omx/plans/ .omx/state/ nginx/dev-certs/ sample.mp4; do
    git check-ignore -q "$path" || die "$path is not ignored"
  done
}

check_metadata() {
  require_cmd python3
  require_cmd rg
  [[ -f "$ROOT_DIR/LICENSE" ]] || die "LICENSE missing"
  [[ -f "$ROOT_DIR/NOTICE" ]] || die "NOTICE missing"
  [[ -f "$ROOT_DIR/CHANGELOG.md" ]] || die "CHANGELOG.md missing"
  [[ -f "$ROOT_DIR/release.json" ]] || die "release.json missing"

  python3 - "$ROOT_DIR/release.json" "$ROOT_DIR/client/resources/test_suite_v1/finalization-status.json" "$ROOT_DIR/CHANGELOG.md" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
status = json.load(open(sys.argv[2], encoding="utf-8"))
changelog = open(sys.argv[3], encoding="utf-8").read()
expected = {
    "benchmarkProtocolVersion": "7.0",
    "plFormulaVersion": "7.0",
    "suiteVersion": "1.0.0",
    "clientImplementationVersion": "client/0.2.0",
}
for key, value in expected.items():
    if payload.get(key) != value:
        raise SystemExit(f"release.json {key} must be {value}")
if payload.get("projectVersion") is not None and not isinstance(payload["projectVersion"], str):
    raise SystemExit("release.json projectVersion must be a string or null")
if payload.get("releaseDate") is not None and not isinstance(payload["releaseDate"], str):
    raise SystemExit("release.json releaseDate must be a string or null")
if status.get("isFrozen") is True:
    version = payload.get("projectVersion")
    date = payload.get("releaseDate")
    if not isinstance(version, str) or not version.strip() or not isinstance(date, str) or not date.strip():
        raise SystemExit("frozen-suite releases require projectVersion and releaseDate in release.json")
    if f"## [{version}] - {date}" not in changelog:
        raise SystemExit("CHANGELOG lacks the assigned project version/date heading")
elif "## [Unreleased]" not in changelog:
    raise SystemExit("CHANGELOG must retain Unreleased until the final suite is frozen")
PY

  ! rg -n "Next\\.js 15|Next 15" README.md frontend/DEPLOYMENT.md >/dev/null
}

check_frontend() {
  require_cmd npm
  run_shell "cd frontend && npm ci --no-audit --no-fund"
  run_shell "cd frontend && npm run lint"
  run_shell "cd frontend && npm test"
  run_shell "cd frontend && npm run build"
}

check_server() {
  require_cmd npm
  run_shell "cd server && npm ci --no-audit --no-fund"
  run_shell "cd server && npm test"
  run_shell "cd server && npm audit --omit=dev --audit-level=high"
}

check_client() {
  require_cmd python3
  run_shell "cd client && python3 -m pip install --disable-pip-version-check -r requirements-ci.txt"
  run_shell "cd client && python3 -m pytest -q"
}

check_stack_smoke() {
  require_cmd bash
  run_root bash scripts/test.sh
}

check_ops_hooks() {
  run_root bash -n scripts/generate-dev-cert.sh scripts/production_smoke.sh scripts/release_preflight.sh scripts/v7-backup.sh scripts/v7-restore-drill.sh scripts/v7-migration-rehearsal.sh scripts/certify-v7-e2e.sh deploy.sh
}

check_migrations() {
  run_root bash scripts/v7-migration-rehearsal.sh
}

check_production_compose() {
  require_cmd docker
  run_shell "ARTIFACT_UPLOAD_SECRET=release-preflight-placeholder APP_URL=https://release-preflight.invalid docker compose -f docker-compose.prod.yml config -q"
}

check_suite_contract() {
  run_root python3 scripts/verify_suite_assets.py client/resources/test_suite_v1
  run_root python3 scripts/test_suite_drift_check.py
  [[ -f "$ROOT_DIR/client/resources/runtime/ffmpeg-lock.json" ]] || die "client FFmpeg runtime lock is missing"
  [[ -f "$ROOT_DIR/client/requirements-build.txt" ]] || die "pinned client build requirements are missing"
  for builder in scripts/build_linux_client.sh scripts/build_macos_client.sh scripts/build_windows_client.ps1; do
    grep -q 'ENCODINGDB_REGISTER_RUNTIME' "$ROOT_DIR/$builder" || die "$builder lacks explicit operator runtime registration"
    grep -q 'requirements-build.txt' "$ROOT_DIR/$builder" || die "$builder lacks the pinned isolated build contract"
  done
}

check_final_suite() {
  python3 - "$ROOT_DIR" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
client = root / "client/resources/test_suite_v1"
server = root / "server/resources/test_suite_v1"
try:
    cs = json.loads((client / "finalization-status.json").read_text())
    ss = json.loads((server / "finalization-status.json").read_text())
except Exception:
    raise SystemExit(1)
if cs != ss or cs.get("isFrozen") is not True:
    raise SystemExit(1)
lock_name = cs.get("finalLockPath")
if not isinstance(lock_name, str) or not lock_name:
    raise SystemExit(1)
if (client / lock_name).read_bytes() != (server / lock_name).read_bytes():
    raise SystemExit(1)
if (client / "manifest.json").read_bytes() != (server / "manifest.json").read_bytes():
    raise SystemExit(1)
PY
}

failures=0
final_suite_missing=0
for check in "${REQUESTED_CHECKS[@]}"; do
  label="$check"
  output_file="$(mktemp "${TMPDIR:-/tmp}/encodingdb-preflight.XXXXXX")"
  status=0
  set +e
  case "$check" in
    hygiene) check_hygiene >"$output_file" 2>&1 || status=$? ;;
    metadata) check_metadata >"$output_file" 2>&1 || status=$? ;;
    frontend) check_frontend >"$output_file" 2>&1 || status=$? ;;
    server) check_server >"$output_file" 2>&1 || status=$? ;;
    client) check_client >"$output_file" 2>&1 || status=$? ;;
    stack-smoke) check_stack_smoke >"$output_file" 2>&1 || status=$? ;;
    migrations) check_migrations >"$output_file" 2>&1 || status=$? ;;
    production-compose) check_production_compose >"$output_file" 2>&1 || status=$? ;;
    suite-contract) check_suite_contract >"$output_file" 2>&1 || status=$? ;;
    ops-hooks) check_ops_hooks >"$output_file" 2>&1 || status=$? ;;
    final-suite) check_final_suite >"$output_file" 2>&1 || status=$? ;;
    *)
      rm -f "$output_file"
      die "unknown check: $check"
      ;;
  esac
  set -e
  if [[ "$status" -eq 0 ]]; then
    printf 'PASS %s\n' "$label"
  elif [[ "$check" == "final-suite" ]]; then
    printf 'FAIL FINAL_TEST_SUITE_NOT_FROZEN\n'
    final_suite_missing=1
  else
    printf 'FAIL %s\n' "$label"
    sed -n '1,120p' "$output_file" >&2
    failures=$((failures + 1))
  fi
  rm -f "$output_file"
done

if (( failures > 0 || final_suite_missing > 0 )); then
  exit 1
fi
log "Release preflight checks passed: ${REQUESTED_CHECKS[*]}"
