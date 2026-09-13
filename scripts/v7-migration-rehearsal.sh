#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATIONS_DIR="$ROOT_DIR/server/prisma/migrations"
PRE_V7_CUTOFF="${PRE_V7_CUTOFF:-20260811060000_invalidate_reversed_vmaf}"
DRY_RUN=0
SERVER_PORT="${SERVER_PORT:-3311}"
SERVER_PID=""
SERVER_LOG=""

usage() {
  cat <<'EOF' >&2
usage: v7-migration-rehearsal.sh [--dry-run]

Rehearses the pre-V7 -> current migration path in an isolated PostgreSQL 16
container, including representative legacy rows plus a DerivedResultMember row
that must backfill qualityAnalysisId during the exact-membership migration.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v psql >/dev/null 2>&1 || { echo "psql is required" >&2; exit 2; }

ALL_MIGRATIONS=()
while IFS= read -r migration; do
  ALL_MIGRATIONS+=("$migration")
done < <(find "$MIGRATIONS_DIR" -mindepth 1 -maxdepth 1 -type d -print | sort)
PRE_MIGRATIONS=()
POST_MIGRATIONS=()
for migration in "${ALL_MIGRATIONS[@]}"; do
  name="$(basename "$migration")"
  [[ "$name" == "migration_lock.toml" ]] && continue
  if [[ "$name" < "$PRE_V7_CUTOFF" || "$name" == "$PRE_V7_CUTOFF" ]]; then
    PRE_MIGRATIONS+=("$migration")
  else
    POST_MIGRATIONS+=("$migration")
  fi
done

if (( DRY_RUN == 1 )); then
  printf '{\n'
  printf '  "mode": "dry-run",\n'
  printf '  "preV7Cutoff": "%s",\n' "$PRE_V7_CUTOFF"
  printf '  "preMigrationCount": %s,\n' "${#PRE_MIGRATIONS[@]}"
  printf '  "postMigrationCount": %s\n' "${#POST_MIGRATIONS[@]}"
  printf '}\n'
  exit 0
fi

CONTAINER_NAME="encodingdb-v7-migration-rehearsal-$RANDOM-$$"
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run -d --name "$CONTAINER_NAME" \
  -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=benchmarks \
  -P postgres:16-alpine >/dev/null

db_ready=0
for _ in $(seq 1 60); do
  if docker exec "$CONTAINER_NAME" pg_isready -U app -d benchmarks >/dev/null 2>&1; then
    db_ready=1
    break
  fi
  sleep 1
done
if (( db_ready != 1 )); then
  echo "rehearsal postgres did not become ready in time" >&2
  exit 1
fi
PORT="$(docker port "$CONTAINER_NAME" 5432/tcp | head -1 | sed 's/.*://')"
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "could not resolve postgres port" >&2; exit 1; }
DATABASE_URL="postgresql://app:app@127.0.0.1:${PORT}/benchmarks"

host_db_ready=0
for _ in $(seq 1 30); do
  if psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null 2>&1; then
    host_db_ready=1
    break
  fi
  sleep 1
done
if (( host_db_ready != 1 )); then
  echo "rehearsal postgres host port did not become ready in time" >&2
  exit 1
fi

run_sql_file() {
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$1" >/dev/null
}

for migration in "${PRE_MIGRATIONS[@]}"; do
  run_sql_file "$migration/migration.sql"
done

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
INSERT INTO "Benchmark" (
  "id", "createdAt", "updatedAt", "cpuModel", "gpuModel", "ramGB", "os", "codec",
  "preset", "fps", "vmaf", "fileSizeBytes", "notes", "status", "ffmpegVersion",
  "encoderName", "clientVersion", "inputHash", "runMs"
) VALUES (
  'legacy-benchmark-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'Apple M4 Pro',
  'Integrated', 48, 'macOS 15', 'h264', 'medium', 24, 94.2, 7340032,
  'legacy aggregate row carried across the V7 boundary', 'complete',
  'ffmpeg 7.1', 'libx264', 'client/0.9.0', 'legacy-input-hash', 18450
);

INSERT INTO "Submission" (
  "id", "createdAt", "updatedAt", "cpuModel", "gpuModel", "ramGB", "os", "codec",
  "preset", "crf", "fps", "vmaf", "fileSizeBytes", "notes", "status", "qualityScore",
  "ffmpegVersion", "encoderName", "clientVersion", "inputHash", "runMs", "payloadHash"
) VALUES (
  'legacy-submission-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'Apple M4 Pro',
  'Integrated', 48, 'macOS 15', 'h264', 'medium', 23, 24, 94.2, 7340032,
  'legacy submission row carried across the V7 boundary', 'complete', 94.2,
  'ffmpeg 7.1', 'libx264', 'client/0.9.0', 'legacy-input-hash', 18450,
  'legacy-payload-hash'
);
SQL

for migration in "${POST_MIGRATIONS[@]}"; do
  name="$(basename "$migration")"
  if [[ "$name" == "20260812030000_legacy_aggregate_null_identity" || "$name" == "20260812040000_exact_analysis_membership" ]]; then
    break
  fi
  run_sql_file "$migration/migration.sql"
done

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
INSERT INTO "BenchmarkProtocol" (
  "id", "createdAt", "updatedAt", "protocolVersion", "sourceSuiteVersion",
  "minimumClientVersion", "canonicalRecipeRules", "canonicalOutputRules",
  "metricWorkerVersion", "state", "activatedAt"
) VALUES (
  'proto-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'EDB-2026.1',
  'encodingdb-test-suite-v1', 'client/1.0.0', '{}'::jsonb, '{}'::jsonb,
  'authoritative-analysis/v1', 'ACTIVE', CURRENT_TIMESTAMP
);

INSERT INTO "TestClip" (
  "id", "createdAt", "updatedAt", "suiteId", "suiteVersion", "manifestVersion",
  "clipKey", "displayName", "workloadId", "contentClass", "sourceProvenance",
  "sha256", "byteSize", "exactFrameCount", "exactDurationSeconds",
  "frameRateNumerator", "frameRateDenominator", "width", "height",
  "pixelFormat", "bitDepth", "chromaSubsampling"
) VALUES (
  'clip-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'encodingdb-test-suite',
  'encodingdb-test-suite-v1', '1', 'sports-action-960x540-24p',
  'Sports Action', 'sports-action-960x540-24p', 'high-motion-sports',
  '{}'::jsonb, repeat('a', 64), 1048576, 240, 10, 24, 1, 960, 540,
  'yuv420p', 8, '4:2:0'
);

INSERT INTO "Recipe" (
  "id", "createdAt", "updatedAt", "fingerprint", "canonicalJson", "codecFamily",
  "encoderImplementation", "pixelFormat", "bitDepth", "chromaSubsampling",
  "requestedRateControlMode", "effectiveRateControlMode", "requestedRateControl",
  "effectiveRateControl"
) VALUES (
  'recipe-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'recipe-fingerprint',
  '{}'::jsonb, 'h264', 'libx264', 'yuv420p', 8, '4:2:0', 'CRF', 'CRF',
  '{"mode":"crf","qualityValue":23}'::jsonb, '{"mode":"crf","qualityValue":23}'::jsonb
);

INSERT INTO "Environment" (
  "id", "createdAt", "updatedAt", "fingerprint", "canonicalJson", "cpuModel",
  "cpuArchitecture", "physicalCoreCount", "logicalThreadCount", "gpuModel",
  "osName", "osVersion", "ffmpegBuildFingerprint", "ffmpegVersion", "clientVersion"
) VALUES (
  'env-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'environment-fingerprint',
  '{"physicalMemoryBytes":51539607552}'::jsonb, 'Apple M4 Pro', 'arm64', 12, 12, 'Integrated', 'macOS', '15',
  'ffmpeg-build-fingerprint', '7.1', 'client/1.0.0'
);

INSERT INTO "BenchmarkRun" (
  "id", "createdAt", "updatedAt", "benchmarkProtocolId", "testClipId", "workloadId",
  "recipeId", "environmentId", "payloadHash", "encodeFps", "sourceFps",
  "realTimeRatio", "status"
) VALUES (
  'run-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'proto-v7', 'clip-v7',
  'sports-action-960x540-24p', 'recipe-v7', 'env-v7', repeat('b', 64),
  120, 24, 5, 'ACCEPTED'
);

INSERT INTO "Artifact" (
  "id", "createdAt", "updatedAt", "benchmarkRunId", "role", "sha256", "byteSize",
  "storageState", "storageProvider", "storageKey"
) VALUES (
  'artifact-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'run-v7', 'ENCODED',
  repeat('c', 64), 7340032, 'RETAINED', 'filesystem', 'runs/run-v7/encoded.mkv'
);

INSERT INTO "QualityAnalysis" (
  "id", "createdAt", "updatedAt", "benchmarkRunId", "artifactId", "status",
  "metricModelId", "analysisWorkerVersion", "analysisProvenance", "vmafMean",
  "vmafP5", "videoBitrateBps", "fileSizeBytes"
) VALUES (
  'analysis-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'run-v7', 'artifact-v7',
  'COMPLETE', 'vmaf-v1-sdr-sd', 'authoritative-analysis/v1', '{}'::jsonb,
  95, 90, 4000000, 7340032
);

INSERT INTO "ScoreContext" (
  "id", "createdAt", "updatedAt", "benchmarkProtocolId", "formulaVersion",
  "contextVersion", "workloadId", "qualityModelId", "workloadReferenceBitrateBps",
  "transformConstants", "referenceFrontier"
) VALUES (
  'score-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'proto-v7', '7.0', 'ctx-v1',
  'sports-action-960x540-24p', 'vmaf-v1-sdr-sd', 4000000,
  '{"qualityExponent":2.4,"speedCurveRate":1.2,"speedSaturationRealtime":4}'::jsonb,
  '{"workloadId":"sports-action-960x540-24p","contentClass":"high-motion-sports"}'::jsonb
);

INSERT INTO "DerivedResult" (
  "id", "createdAt", "updatedAt", "kind", "scopeKey", "benchmarkProtocolId",
  "workloadId", "testClipId", "recipeId", "environmentId", "scoreContextId",
  "aggregatorVersion", "acceptedRunCount", "suspectRunCount", "rejectedRunCount",
  "invalidRunCount", "repetitionCount", "plQuality", "plBitrate", "plSpeed",
  "plTotal", "confidenceLower", "confidenceUpper", "evidenceTier", "evidenceSummary",
  "confidenceIntervals", "dispersion", "recomputationSpec"
) VALUES (
  'derived-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'WORKLOAD',
  'workload:sports-action-960x540-24p', 'proto-v7', 'sports-action-960x540-24p',
  'clip-v7', 'recipe-v7', 'env-v7', 'score-v7', 'pl-v7-derived-v1', 1, 0, 0, 0, 1,
  95, 100, 99, 97, 95, 99, 'LOW', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
  '{"selectedAnalysisIds":["analysis-v7"]}'::jsonb
);

INSERT INTO "DerivedResultMember" (
  "id", "createdAt", "derivedResultId", "benchmarkRunId"
) VALUES (
  'member-v7', CURRENT_TIMESTAMP, 'derived-v7', 'run-v7'
);
SQL

for migration in "${POST_MIGRATIONS[@]}"; do
  name="$(basename "$migration")"
  if [[ "$name" < "20260812030000_legacy_aggregate_null_identity" ]]; then
    continue
  fi
  run_sql_file "$migration/migration.sql"
done

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
INSERT INTO "Benchmark" (
  "id", "createdAt", "updatedAt", "cpuModel", "gpuModel", "ramGB", "os", "codec",
  "preset", "crf", "contentClass", "resolution", "passes", "fps", "vmaf",
  "vmafP5", "fileSizeBytes", "videoBitrateBps", "sourceFps", "sourceDurationSeconds",
  "samples", "vmafSamples", "fpsSum", "fileSizeSum", "vmafSum", "status",
  "ffmpegVersion", "encoderName", "clientVersion", "inputHash", "runMs",
  "scoreFormulaVersion", "benchmarkProtocolVersion", "sourceSuiteVersion",
  "workloadId", "metricModelId", "payloadHash"
) VALUES (
  'query-benchmark-v7', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'Apple M4 Pro',
  'Integrated', 48, 'macOS 15', 'h264', 'medium', 23, 'action', '540p', 1,
  120, 95, 90, 7340032, 4000000, 24, 10, 1, 1, 120, 7340032, 95, 'accepted',
  'ffmpeg 7.1', 'libx264', 'client/1.0.0', 'query-input-hash', 18450, '7.0',
  'EDB-2026.1', 'encodingdb-test-suite-v1', 'sports-action-960x540-24p',
  'vmaf-v1-sdr-sd', 'query-payload-hash'
);
SQL

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
DO $$
DECLARE
  member_quality_analysis TEXT;
  member_count INTEGER;
  legacy_exists INTEGER;
  environment_physical_memory BIGINT;
BEGIN
  SELECT "qualityAnalysisId" INTO member_quality_analysis
  FROM "DerivedResultMember"
  WHERE "id" = 'member-v7';
  IF member_quality_analysis <> 'analysis-v7' THEN
    RAISE EXCEPTION 'qualityAnalysisId backfill failed: %', member_quality_analysis;
  END IF;

  SELECT COUNT(*) INTO member_count
  FROM pg_indexes
  WHERE tablename = 'DerivedResultMember'
    AND indexname = 'DerivedResultMember_derivedResultId_qualityAnalysisId_key';
  IF member_count <> 1 THEN
    RAISE EXCEPTION 'exact-membership unique index missing';
  END IF;

  SELECT COUNT(*) INTO legacy_exists
  FROM "Benchmark"
  WHERE "id" = 'legacy-benchmark-1';
  IF legacy_exists <> 1 THEN
    RAISE EXCEPTION 'legacy Benchmark row did not survive migration';
  END IF;

  SELECT "physicalMemoryBytes" INTO environment_physical_memory
  FROM "Environment"
  WHERE "id" = 'env-v7';
  IF environment_physical_memory <> 51539607552 THEN
    RAISE EXCEPTION 'physicalMemoryBytes backfill failed: %', environment_physical_memory;
  END IF;
END $$;
SQL

SERVER_LOG_BASE="$(mktemp "${TMPDIR:-/tmp}/encodingdb-v7-migration-server.XXXXXX")"
SERVER_LOG="${SERVER_LOG_BASE}.log"
mv "$SERVER_LOG_BASE" "$SERVER_LOG"
(
  cd "$ROOT_DIR/server"
  env \
    DATABASE_URL="$DATABASE_URL" \
    PORT="$SERVER_PORT" \
    CORS_ORIGIN="http://127.0.0.1:${SERVER_PORT}" \
    TRUST_PROXY="false" \
    ARTIFACT_STORAGE_ROOT="/tmp/encodingdb-v7-migration-artifacts" \
    ARTIFACT_UPLOAD_SECRET="migration-rehearsal-secret" \
    ALLOW_TEST_ONLY_REFERENCE_CONTEXTS="0" \
    npx tsx src/index.ts
) >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${SERVER_PORT}/health/ready" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    cat "$SERVER_LOG" >&2
    echo "migration rehearsal server exited before readiness" >&2
    exit 1
  fi
  sleep 1
done

curl -fsS "http://127.0.0.1:${SERVER_PORT}/health/ready" >/dev/null
curl -fsS "http://127.0.0.1:${SERVER_PORT}/query?limit=1" | python3 -c 'import json,sys; data=json.load(sys.stdin); assert isinstance(data, list) and len(data) >= 1'
curl -fsS "http://127.0.0.1:${SERVER_PORT}/corpus?limit=1" | python3 -c 'import json,sys; data=json.load(sys.stdin); assert isinstance(data, list) and len(data) >= 1'

echo "PL-v7 migration rehearsal passed"
