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

## Repeat on the P910 candidate runtime (operator allocation required)

The local ARM64 trial does not certify P910 latency. A repeat must use a **new, isolated synthetic database**, the final reviewed candidate image and a quiet host interval before calibration timing. Do not point this harness at candidate, production or calibration databases, and do not reuse their volumes. Do not run while the timing lock is owned. This paragraph is preparation, not a record that a remote trial ran.

The harness accepts `PROJECTION_SCALE_SERVER_ROOT` for the image's `/app` layout, and `PROJECTION_SCALE_SOURCE_SHA` for an explicitly verified full source SHA when the runtime image lacks git. These affect only module/provenance resolution. Record the image ID/digest independently; the explicit SHA is not proof of image provenance. Disk sampling uses the evidence output filesystem on either host. Readers, writer cycles, database limits and assertions remain unchanged.

After the root allocates the remote work and the final image/source identity is recorded:

1. Verify loopback ports 55441/55442 are unused, no timing campaign is active, and sufficient disk is available. Create a uniquely named task directory and task-owned PostgreSQL container beginning `encodingdb-projection-synthetic-`. Use a freshly created volume; retain it until evidence is audited. Resolve and record the PostgreSQL 16 AMD64 image digest.
2. Start that PostgreSQL container with exactly `--memory=1g --memory-swap=1g --shm-size=256m -p127.0.0.1:55441:5432`, the same synthetic user/database/password shown above, and `-c shared_buffers=128MB -c work_mem=4MB -c max_connections=100`. Record image, kernel, CPU, Node version and cgroup version/limits. Require cgroup-v2 `memory.current`, `memory.peak`, `memory.events` and `memory.stat`; preserve before/after counters.
3. Mount only the reviewed harness and its fresh evidence directory into a **separate container from the final candidate image**, with Linux host networking and the production server's 16 GiB memory cap. Use `PROJECTION_SCALE_SERVER_ROOT=/app`, the verified `PROJECTION_SCALE_SOURCE_SHA`, and the synthetic loopback URL with `connection_limit=30`. Invoke the image's existing Prisma CLI to migrate the empty synthetic DB; invoke the harness `seed` and then `serve`. Do not run the normal API entrypoint or analysis workers.
4. Run `measure` from the host with Node, Docker CLI access and matching server modules/dist in a task-local checkout. Those modules may be copied from a stopped, disposable container created from the same final candidate image; record the copy/image provenance and do not borrow modules from a running service. This process is the load generator, not the measured API runtime. Sample `/memory` once before measurement and verify its `sourceSha` matches the reviewed pin.
5. After explicit quiet-window allocation, run the unchanged 600-second measurement and full drain. Preserve every failure. Capture the exact-interval database logs and cgroup counters; run `docs/collection-readiness/projection-20260914/trial-2/reconcile.sql` against the synthetic DB. Save actual commands, source/image hashes, seed, complete receipt, all-cohort reconciliation and resource inventory. Stop only the disposable API container. Any failed trial is retained before a fix/repeat.

Image-side command shape (variables must be resolved and recorded by the operator):

```sh
# Linux only. The runtime image, mount paths and source must already be verified.
docker run --rm --network host --memory=16g --memory-swap=16g \
  --name "$PROJECTION_API_CONTAINER" \
  --mount "type=bind,src=$PROJECTION_HARNESS_DIRECTORY,dst=/projection,readonly" \
  --mount "type=bind,src=$PROJECTION_EVIDENCE_DIRECTORY,dst=/evidence" \
  -e PROJECTION_SCALE_SERVER_ROOT=/app \
  -e "PROJECTION_SCALE_SOURCE_SHA=$PROJECTION_REVIEWED_SOURCE_SHA" \
  -e PROJECTION_SCALE_OUTPUT=/evidence \
  -e "PROJECTION_SCALE_DATABASE_URL=$PROJECTION_SCALE_DATABASE_URL" \
  -e PROJECTION_SCALE_PORT=55442 \
  "$PROJECTION_CANDIDATE_IMAGE_ID" node /projection/run.mjs serve
```

Use the same shape with `seed` after migration. The host measurement process uses the same database URL, port, explicit source SHA, output directory and PostgreSQL container name. Building/pulling/copying/migrating/seeding occurs before the quiet interval; no P910 operation has been performed merely by documenting these commands.

## Restore the original fixture after one completed trial

`reset-arrivals` is an operator-only synthetic-fixture preparation mode. Preserve the entire prior database with `pg_dump -Fc` and its SHA256 before use. Set `PROJECTION_SCALE_BASELINE_SEED` to the original successful `seed.json` and `PROJECTION_SCALE_PRESERVED_DUMP_SHA256` to that verified dump hash. The wrapper must be stopped and no writer may own the synthetic database.

The mode requires exactly 100,020 runs/artifacts/analyses, 981 derived cohorts and 80,020 members. It reconstructs the exact 20 expected arrival IDs (two cohorts × five cycles × two repetitions), verifies every generated run/artifact/analysis field, and deletes only those records and their memberships in one transaction. It rebuilds only the two affected cohorts, drains summaries, checks original hot/normal/distant member hashes, centers, scores and raw/source counts against the original seed, then proves all 80,000 remaining expected stable members by SQL set comparison. Its new seed receipt records the deleted IDs, prior counts, preserved dump hash and complete checks. Any mismatch fails; this is not a general cleanup or partial-trial recovery command. The measured workload and gates are unchanged.
