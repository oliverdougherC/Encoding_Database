#!/usr/bin/env bash
# Environment comes from the operator's private service EnvironmentFile.
set -Eeuo pipefail
umask 077
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${V7_BACKUP_DESTINATION:?V7_BACKUP_DESTINATION is required}"
: "${V7_BACKUP_RETENTION_COUNT:=7}"
: "${V7_BACKUP_VERIFY_RESTORE:=1}"
[[ "$V7_BACKUP_RETENTION_COUNT" =~ ^[1-9][0-9]*$ ]] || { echo 'retention count must be positive' >&2; exit 2; }
mkdir -p "$V7_BACKUP_DESTINATION"
BUNDLE="$V7_BACKUP_DESTINATION/backup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BACKUP_PASSED=0
record_status() {
  local code=$?
  if [[ "$BACKUP_PASSED" != 1 && "$code" == 0 ]]; then code=1; fi
  python3 - "$V7_BACKUP_DESTINATION" "$BUNDLE" "$started" "$code" "$V7_BACKUP_VERIFY_RESTORE" <<'PY'
from datetime import datetime,timezone
import json,os,sys,tempfile
root,bundle,started,code,restore=sys.argv[1:]
value={'version':1,'startedAt':started,'finishedAt':datetime.now(timezone.utc).isoformat(),'bundle':bundle,'exitCode':int(code),'restoreRequired':restore=='1'}
fd,name=tempfile.mkstemp(prefix='.last-backup-',dir=root)
with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')
os.replace(name,os.path.join(root,'last-backup.json'))
PY
  exit "$code"
}
trap record_status EXIT
if [[ -n "${V7_BACKUP_COMPOSE_FILE:-}" ]]; then
  bash "$ROOT_DIR/scripts/v7-backup.sh" --compose-file "$V7_BACKUP_COMPOSE_FILE" "$BUNDLE"
else
  bash "$ROOT_DIR/scripts/v7-backup.sh" "$BUNDLE"
fi
if [[ "$V7_BACKUP_VERIFY_RESTORE" == 1 ]]; then
  bash "$ROOT_DIR/scripts/v7-restore-drill.sh" "$BUNDLE"
fi
# Prune only completed bundles created by this wrapper. Failed runs never prune.
python3 - "$V7_BACKUP_DESTINATION" "$V7_BACKUP_RETENTION_COUNT" <<'PY'
import pathlib,re,shutil,sys
root=pathlib.Path(sys.argv[1]);keep=int(sys.argv[2])
bundles=sorted((p for p in root.iterdir() if not p.is_symlink() and p.is_dir() and re.fullmatch(r'backup-\d{8}T\d{6}Z-\d+',p.name) and (p/'SHA256SUMS').is_file() and (p/'inventory.json').is_file()),key=lambda p:p.name,reverse=True)
for old in bundles[keep:]:shutil.rmtree(old)
PY

BACKUP_PASSED=1
