# Synthetic scored-projection scale trial

This harness exercises production `loadPublicCorpusPage`, full-group eligibility and aggregate persistence with a test-only context override. It does not activate a context, fabricate media bytes, or measure quality-worker throughput. Every synthetic identity is prefixed `SYNTHETIC-PROJECTION-ONLY`. The database URL must use127.0.0.1 and the dedicated `encodingdb_projection_synthetic` name; the server binds loopback only.

Predeclared workload:100,000 runs and matching artifacts/analyses;981cohorts (980×100 plus a2,000-row hotcohort). Each100-row block has80stable observations in40complete groups,16unstable observations in4complete groups, and4observations from incomplete groups. All have corrected CPU sampler markers. The production persistence path builds981scored derived results with80,000actual qualified members and group dependencies. Synthetic stored-artifact metadata has no corresponding media; it is never calibration evidence.

Predeclared measured target:25concurrent HTTP readers for600seconds, p95≤1000ms, zero request/assertion errors. Readers alternate global scored sorts/pagination, a filter and the hotcohort detail. Every response checks ordered displayed centers and scored/diagnostic PL consistency. Five writer cycles invalidate a hot stable group with an extra pending sibling, observe withdrawn PL, remove that sibling, add complete stable pairs to hot and normal cohorts, rebuild through production persistence and check exact memberships/raw/source counts. The measured interval records all errors including503backpressure. The API wrapper is test-only; this does not measure actual browser rendering or frontend proxy overhead.

Run from repository root after build; no build/tests should run during the measured interval:

```sh
docker run -d --name encodingdb-projection-synthetic-20260914 --memory=1g --memory-swap=1g --shm-size=256m -p127.0.0.1:55441:5432 -e POSTGRES_USER=projection_synthetic -e POSTGRES_PASSWORD=synthetic-isolated-only -e POSTGRES_DB=encodingdb_projection_synthetic postgres:16 -c shared_buffers=128MB -c work_mem=4MB -c max_connections=100
export PROJECTION_SCALE_DATABASE_URL='postgresql://projection_synthetic:synthetic-isolated-only@127.0.0.1:55441/encodingdb_projection_synthetic?connection_limit=30'
export PROJECTION_SCALE_OUTPUT="$PWD/.test-reports/projection-scale"
export PROJECTION_SCALE_CONTAINER=encodingdb-projection-synthetic-20260914
export PROJECTION_SCALE_PORT=55442
(cd server && DATABASE_URL="$PROJECTION_SCALE_DATABASE_URL" npx prisma migrate deploy)
node scripts/projection-scale/run.mjs seed
node scripts/projection-scale/run.mjs serve
# In a separate shell with the same variables, after server readiness:
node scripts/projection-scale/run.mjs measure
```

NodeRSS is sampled in the server every200ms and includes the process resourceUsage maximum; DBcgroup memory is sampled every5seconds with its lifetime memory.peak high-water mark separately retained (including seeding). The latter includes PostgreSQL processes and pagecache within the1GiBcontainer and is not directly comparable to processRSS. Docker Desktop VM memory and load-generator RSS are outside these two series. The exact source SHA, image digest, platform, commands, seed proof and measured receipt must accompany any result claim. No existing database or P910workload is used.
