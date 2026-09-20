# Sustained repeat after the bounded certificate fix

**PASS for the local synthetic metadata/API workload.** The interval ran from 2026-09-20 01:02:31.410 to 01:12:36.361 UTC, including final drain, on source `9370c70baba4adea617e2a96f773fc5293592886`. This includes production certificate fix `edb97fd` and the explicitly documented harness correction to the production 30-second recompute transaction scope. The failed first trial is preserved in the parent directory.

| Measurement | Observed |
|---|---:|
| Readers / declared interval | 25 concurrent HTTP readers / 600 seconds |
| Requests / reader, writer, assertion failures | 29,713 / 0 |
| Latency p50 / p95 / p99 / maximum | 612.72 / 820.68 / 916.54 / 1,339.16 ms |
| Required p95 | ≤ 1,000 ms |
| Successful invalidation, arrival and recompute cycles | 5 of 5 |
| Initial / final runs, artifacts and analyses | 100,000 / 100,020 each |
| Initial / final qualified members | 80,000 / 80,020 |
| Derived cohorts | 981 |
| Missing / unexpected final members | 0 / 0 |
| PostgreSQL OOM / OOM-kill events | 0 / 0 |
| Node maximum process RSS | 370,049,024 bytes |
| Maximum sampled DB cgroup charge | 1,073,479,680 bytes |
| DB lifetime cgroup peak, including setup | 1,073,930,240 bytes |
| Unchanged DB memory / swap limit | 1,073,741,824 bytes each |
| Unchanged DB shared-memory limit | 268,435,456 bytes |
| Minimum available host disk | 20,381,630,464 bytes |

The host is an ARM64 Mac running Darwin 27.0.0; Node v22.23.0 ran natively, and PostgreSQL 16 ran in Docker Desktop. Exact host, image digest, container, configuration and the prior-state dump hash are in `host.json`. The container retained `shared_buffers=128MB`, `work_mem=4MB`, `max_connections=100`; the Prisma pool retained 30 connections. No resource limit, workload, error criterion or latency target was relaxed.

Database memory pressure was substantial. At the post-interval observation, the cgroup reported 608,899,072 anonymous bytes and 418,082,816 file-cache bytes, with 4,485 `memory.events:max` events and zero OOM events. The lifetime high-water mark includes setup and a small transient charge above `memory.max`; it is not an RSS measurement or a promise of spare capacity. The complete `memory.stat` includes reclaim and cache counters. Node RSS, database cgroup accounting, Docker Desktop VM memory and load-generator memory are different scopes; the latter two were not measured by this harness. Do not infer higher concurrency or a smaller supported database limit.

Each writer cycle added a pending sibling to a stable hot-cohort group, observed score withdrawal, removed that sibling, inserted a fresh stable pair into the hot and normal cohorts, and rebuilt using production aggregation. All ten resulting cohort checks retained exact member hashes, raw counts and physical-source counts. The final independent SQL set comparison checks all 80,020 expected stable/arrival observations against every derived membership across all 981 cohorts: no missing or unexpected member, leftover invalidating row or dirty corpus group remained. Public read responses checked displayed-center ordering and scored/diagnostic consistency throughout. Diagnostic rows during intentional invalidation are preserved in the receipt.

The original failed database was dumped before resetting only `encodingdb_projection_synthetic`. A fresh identical 100k fixture passed its seed assertions after all 29 migrations. No production or candidate database, retained media object, score context, human review or calibration evidence was touched. The loopback server was stopped after reconciliation. This is not browser-rendering, frontend-proxy, media-worker throughput or P910 latency certification.

`measurement.json.gz` retains every sampled resource and all five mutations; `postgres-interval.log.gz` retains PostgreSQL logs for the exact interval. `raw-sha256.json` hashes uncompressed bytes. Commands use the existing `scripts/projection-scale/run.mjs` harness:

```sh
export PROJECTION_SCALE_DATABASE_URL='postgresql://projection_synthetic:synthetic-isolated-only@127.0.0.1:55441/encodingdb_projection_synthetic?connection_limit=30'
export PROJECTION_SCALE_OUTPUT="$PWD/.test-reports/projection-scale-trial2"
export PROJECTION_SCALE_CONTAINER=encodingdb-projection-synthetic-20260914
export PROJECTION_SCALE_PORT=55442
npm --prefix server run build
DATABASE_URL="$PROJECTION_SCALE_DATABASE_URL" npx --prefix server prisma migrate deploy --schema server/prisma/schema.prisma
node scripts/projection-scale/run.mjs seed
node scripts/projection-scale/run.mjs serve
# Separate shell, only after coordinated quiet-window allocation:
node scripts/projection-scale/run.mjs measure
# After full drain:
docker exec -i "$PROJECTION_SCALE_CONTAINER" psql -U projection_synthetic -d encodingdb_projection_synthetic -At < docs/collection-readiness/projection-20260914/trial-2/reconcile.sql
```
