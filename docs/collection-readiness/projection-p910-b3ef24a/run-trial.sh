#!/usr/bin/env bash
set -euo pipefail
trial=/mnt/NVME/docker/encodingdb-operations/20260920-projection-b3ef24a
cd "$trial"
exec 9>/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts/host-state/measurement.lock
flock -n 9
image=${1:?Pass the verified optimized image ID}
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]]
[[ "${PROJECTION_MEASUREMENT_ALLOCATED:-}" == root-granted ]]
export PROJECTION_SCALE_SOURCE_SHA=b3ef24abb020bc6af5b5fe6b849ba3eae8314be2
export PROJECTION_SCALE_DATABASE_URL='postgresql://projection_synthetic:synthetic-isolated-only@127.0.0.1:55441/encodingdb_projection_synthetic?connection_limit=30'
export PROJECTION_SCALE_OUTPUT="$trial/evidence"
export PROJECTION_SCALE_PORT=55442
export PROJECTION_SCALE_CONTAINER=encodingdb-projection-synthetic-20260920
export PROJECTION_SCALE_SERVER_ROOT="$trial/server"
image_args=(--network host --memory=16g --memory-swap=16g --mount "type=bind,src=$trial/harness,dst=/projection,readonly" --mount "type=bind,src=$trial/evidence,dst=/evidence" -e PROJECTION_SCALE_SERVER_ROOT=/app -e PROJECTION_SCALE_SOURCE_SHA -e PROJECTION_SCALE_DATABASE_URL -e PROJECTION_SCALE_OUTPUT=/evidence -e PROJECTION_SCALE_PORT)
docker inspect encodingdb-server-1 encodingdb-db-1 encodingdb-frontend-1 encodingdb-candidate-730de3c-server-1 encodingdb-candidate-730de3c-db-1 encodingdb-candidate-730de3c-frontend-1 --format '{{.Name}} {{.Id}} {{.Image}} {{json .Mounts}}' > evidence/preserved-services-before.txt
python3 - <<'VERIFY'
import json
seed=json.load(open('evidence/seed.json'))
assert seed['counts']=={'runs':100000,'artifacts':100000,'analyses':100000,'derived':981,'members':80000}
assert seed['reset']['reconciliation']=={'expected':80000,'actual':80000,'missing':0,'extra':0,'dirty':0}
VERIFY
docker run -d --name encodingdb-projection-api-b3ef24a "${image_args[@]}" "$image" node /projection/run.mjs serve > evidence/api-container-id.txt
trap 'docker stop -t 30 encodingdb-projection-api-b3ef24a >/dev/null 2>&1 || true' EXIT
for i in $(seq 1 30); do if curl -fs http://127.0.0.1:55442/memory > evidence/server-ready.json; then break; fi; sleep 1; done
python3 - <<'PY'
import json
r=json.load(open('evidence/server-ready.json')); assert r['sourceSha']=='b3ef24abb020bc6af5b5fe6b849ba3eae8314be2'
PY
docker exec "$PROJECTION_SCALE_CONTAINER" cat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.stat > evidence/memory-before.txt
ps -C ffmpeg -o pid,ppid,pcpu,pmem,comm > evidence/unrelated-ffmpeg-before.txt || true
cat /proc/loadavg /proc/meminfo > evidence/host-resources-before.txt
date -u +MEASUREMENT_STARTING_%Y-%m-%dT%H:%M:%SZ
set +e
bin/node harness/run.mjs measure > evidence/measurement.log 2>&1
trial_status=$?
set -e
printf '%s\n' "$trial_status" > evidence/measurement-exit-code.txt
date -u +MEASUREMENT_DRAINED_%Y-%m-%dT%H:%M:%SZ
docker exec "$PROJECTION_SCALE_CONTAINER" cat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.stat > evidence/memory-after.txt
ps -C ffmpeg -o pid,ppid,pcpu,pmem,comm > evidence/unrelated-ffmpeg-after.txt || true
cat /proc/loadavg /proc/meminfo > evidence/host-resources-after.txt
docker exec -i "$PROJECTION_SCALE_CONTAINER" psql -U projection_synthetic -d encodingdb_projection_synthetic -At < harness/reconcile.sql > evidence/reconciliation.json
python3 - <<'PY'
import json,subprocess,pathlib
p=pathlib.Path('evidence');d=json.load(open(p/'measurement.json'))
with open(p/'postgres-interval.log','wb') as f: subprocess.run(['docker','logs','--timestamps','--since',d['started'],'--until',d['completed'],'encodingdb-projection-synthetic-20260920'],stdout=f,stderr=subprocess.STDOUT,check=True)
print(json.dumps({k:v for k,v in d.items() if k not in ['resources','mutations','failures']},indent=2));print('FAILURES',len(d['failures']));print('MUTATIONS',len(d['mutations']))
PY
docker logs encodingdb-projection-api-b3ef24a > evidence/api.log 2>&1
docker inspect encodingdb-projection-api-b3ef24a --format '{{.Id}} {{.Image}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{json .Mounts}}' > evidence/api-runtime.txt
docker inspect encodingdb-server-1 encodingdb-db-1 encodingdb-frontend-1 encodingdb-candidate-730de3c-server-1 encodingdb-candidate-730de3c-db-1 encodingdb-candidate-730de3c-frontend-1 --format '{{.Name}} {{.Id}} {{.Image}} {{json .Mounts}}' > evidence/preserved-services-after.txt
cmp evidence/preserved-services-before.txt evidence/preserved-services-after.txt
exit "$trial_status"
