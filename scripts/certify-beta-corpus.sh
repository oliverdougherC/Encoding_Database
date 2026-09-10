#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_URL="${SERVER_URL:-http://127.0.0.1:3001}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:3100}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$ROOT_DIR/.test-reports/beta-corpus}"
FAULT_PROXY_PORT="${FAULT_PROXY_PORT:-3011}"
CLIENT_BINARY="${CLIENT_BINARY:-}"
SUITE_PACK="${SUITE_PACK:-$ROOT_DIR/encodingdb-test-suite-v1.tar.gz}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --client) CLIENT_BINARY="${2:?}"; shift 2 ;;
    --suite-pack) SUITE_PACK="${2:?}"; shift 2 ;;
    --server-url) SERVER_URL="${2:?}"; shift 2 ;;
    --frontend-url) FRONTEND_URL="${2:?}"; shift 2 ;;
    --evidence-root) EVIDENCE_ROOT="${2:?}"; shift 2 ;;
    *) echo 'Usage: certify-beta-corpus.sh --client PATH [--suite-pack PATH] [--server-url URL] [--frontend-url URL] [--evidence-root PATH]' >&2; exit 2 ;;
  esac
done
: "${DATABASE_URL:?DATABASE_URL required}"
: "${ARTIFACT_STORAGE_ROOT:?ARTIFACT_STORAGE_ROOT must expose actual retained server files}"
[[ -z "${PL_V7_REFERENCE_BITRATES_JSON:-}" && -z "${PL_V7_REFERENCE_CONTEXT_VERSION:-}" && -z "${PL_V7_REFERENCE_CONTEXT_PATH:-}" && "${ALLOW_TEST_ONLY_REFERENCE_CONTEXTS:-0}" != 1 ]] || { echo 'PL reference configuration must be blank and test-only contexts disabled' >&2; exit 2; }
[[ -x "$CLIENT_BINARY" && -f "$SUITE_PACK" ]] || { echo 'Packaged binary and actual suite pack required' >&2; exit 2; }
[[ -z "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=all | sed '/^.. \.omx\//d')" ]] || { echo 'A clean committed candidate is required' >&2; exit 2; }
COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
RUN_DIR="$EVIDENCE_ROOT/$COMMIT-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN_DIR/install" "$RUN_DIR/cache" "$RUN_DIR/queue"
RUN_DIR="$(cd "$RUN_DIR" && pwd)"
cp "$CLIENT_BINARY" "$RUN_DIR/install/$(basename "$CLIENT_BINARY")"
cp "$SUITE_PACK" "$RUN_DIR/install/encodingdb-test-suite-v1.tar.gz"
CLIENT="$RUN_DIR/install/$(basename "$CLIENT_BINARY")"
MANIFEST="$ROOT_DIR/client/resources/test_suite_v1/manifest.json"
python3 - "$MANIFEST" "$ROOT_DIR/client/resources/test_suite_v1/finalization-status.json" "$RUN_DIR/clip-ids.txt" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); status=json.load(open(sys.argv[2]))
assert status.get('isFrozen') is True, 'Suite must be frozen'
assert len(m['clips']) == 7 and all(c['acquisition']['kind'] != 'generated' for c in m['clips'])
open(sys.argv[3],'w').write(''.join(c['id']+'\n' for c in m['clips']))
PY
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
FAULT_EVIDENCE="$RUN_DIR/upload-interruption.json"
UPSTREAM_URL="$SERVER_URL" PORT="$FAULT_PROXY_PORT" EVIDENCE_PATH="$FAULT_EVIDENCE" node "$ROOT_DIR/scripts/v7-upload-fault-proxy.mjs" >"$RUN_DIR/fault-proxy.log" 2>&1 &
PROXY_PID=$!
trap 'kill "$PROXY_PID" 2>/dev/null || true; wait "$PROXY_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
  curl -fsS "http://127.0.0.1:$FAULT_PROXY_PORT/health/ready" >/dev/null 2>&1 && break
  kill -0 "$PROXY_PID" 2>/dev/null || exit 1
  sleep 0.1
done
curl -fsS "http://127.0.0.1:$FAULT_PROXY_PORT/health/ready" >/dev/null
PROCESSED_CLIPS=0
while IFS= read -r clip; do
  [[ -n "$clip" ]] || { echo 'Empty canonical clip ID' >&2; exit 1; }
  echo "Certifying packaged client: $clip"
  env -u ENCODINGDB_SUITE_PACK_PATH -u ENCODINGDB_SUITE_PACK_URL \
    ENCODINGDB_SUITE_CACHE_DIR="$RUN_DIR/cache" \
    "$CLIENT" --submit --base-url "http://127.0.0.1:$FAULT_PROXY_PORT" --codec libx264 \
    --v7-suite-clip "$clip" --presets fast --crf 24 --retries 1 \
    --queue-dir "$RUN_DIR/queue" </dev/null >"$RUN_DIR/$clip-client.log" 2>&1
  PROCESSED_CLIPS=$((PROCESSED_CLIPS + 1))
done <"$RUN_DIR/clip-ids.txt"
[[ "$PROCESSED_CLIPS" -eq 7 ]] || { echo "Expected seven processed canonical clips; got $PROCESSED_CLIPS" >&2; exit 1; }
[[ -z "$(find "$RUN_DIR/queue" -maxdepth 1 -name '*.json' -type f -print)" ]] || { echo 'Unrecovered client queue' >&2; exit 1; }
rg -q 'Queued payload for retry' "$RUN_DIR"/*-client.log
rg -q 'Submitted 1 queued payload\(s\)' "$RUN_DIR"/*-client.log
python3 - "$RUN_DIR" "$ROOT_DIR" "$CLIENT" "$MANIFEST" "$STARTED_AT" <<'PY'
import hashlib,json,pathlib,subprocess,sys
out,root,binary,manifest,started=sys.argv[1:]
def identity(p):
 p=pathlib.Path(p); return {'path':str(p),'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest(),'byteSize':p.stat().st_size}
data={'evidenceVersion':'encodingdb-unscored-beta/v1','commit':subprocess.check_output(['git','-C',root,'rev-parse','HEAD'],text=True).strip(),'branch':subprocess.check_output(['git','-C',root,'branch','--show-current'],text=True).strip(),'startedAt':started,'packagedClient':identity(binary),'suitePack':identity(pathlib.Path(binary).parent/'encodingdb-test-suite-v1.tar.gz'),'manifest':identity(manifest),'initialCache':'empty newly created directory','acquisition':'adjacent exact suite pack','plConfiguration':{'PL_V7_REFERENCE_BITRATES_JSON':'','PL_V7_REFERENCE_CONTEXT_VERSION':'','PL_V7_REFERENCE_CONTEXT_PATH':'','ALLOW_TEST_ONLY_REFERENCE_CONTEXTS':'0'}}
pathlib.Path(out,'execution.json').write_text(json.dumps(data,indent=2)+'\n')
PY
node "$ROOT_DIR/server/scripts/verify-beta-corpus.mjs" --since "$STARTED_AT" --server-url "$SERVER_URL" --frontend-url "$FRONTEND_URL" --manifest "$MANIFEST" --fault-evidence "$FAULT_EVIDENCE" --storage-root "$ARTIFACT_STORAGE_ROOT" --output "$RUN_DIR/authority-chain.json"
python3 - "$RUN_DIR" <<'PY'
import hashlib,pathlib,sys
root=pathlib.Path(sys.argv[1])
lines=[]
for p in sorted(root.rglob('*')):
 if p.is_file() and p.name!='SHA256SUMS': lines.append(hashlib.file_digest(p.open('rb'),'sha256').hexdigest()+'  '+str(p.relative_to(root)))
(root/'SHA256SUMS').write_text('\n'.join(lines)+'\n')
PY
echo "Unscored beta corpus certification passed: $RUN_DIR"
