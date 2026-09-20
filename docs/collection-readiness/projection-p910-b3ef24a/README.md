# Optimized P910 capacity repeat preparation

**PASS for the declared synthetic HTTP metadata workload, with a narrow latency margin.** The optimized `b3ef24a` interval ran from **2026-09-20 03:57:17.932 to 04:07:18.965 UTC**, including drain. All 25 readers and five writer cycles completed under the unchanged resources and criteria. The earlier `939823e` failure remains preserved; it was followed by a reviewed query change, not repeated trials seeking a favorable result.

| Measurement | Observed |
|---|---:|
| Declared interval / readers | 600 seconds / 25 concurrent HTTP readers |
| Requests / errors | 25,106 / 0 |
| Latency p50 / p95 / p99 / maximum | 605.05 / 985.57 / 1,341.06 / 2,130.71 ms |
| Required p95 / observed margin | ≤1,000 ms / 14.43 ms (1.44%) |
| Successful writer cycles | 5 of 5 |
| Final runs, artifacts and analyses | 100,020 each |
| Final exact members / cohorts | 80,020 / 981 |
| Missing / unexpected members; pending invalidations; dirty groups | 0 / 0; 0; 0 |
| Node maximum process RSS | 525,709,312 bytes |
| Maximum sampled DB cgroup charge | 1,073,614,848 bytes |
| DB lifetime high-water charge, including prior trial/setup | 1,073,754,112 bytes |
| PostgreSQL OOM / OOM-kill events | 0 / 0 |

The exact measured server image was `sha256:589c89b95e471fb32782a374c88b91d8ea2526080b7cdb7bc48608f97eba399a`, source `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2`, on the same P910 AMD64 host and PostgreSQL 16.15 database container used for the preserved earlier trial. Its Node v20.20.2 and production modules supplied both the disposable image-based API and task-local load generator. The API retained a 16 GiB memory cap; the database retained 1 GiB RAM/swap, 256 MiB shared memory, `shared_buffers=128MB`, `work_mem=4MB`, `max_connections=100`, and a 30-connection Prisma pool. The synthetic wrapper did not start media workers. Unrelated Jellyfin activity was left untouched.

The narrow p95 margin and p99 above one second do **not** establish spare capacity or justify higher concurrency. Database cgroup charge includes file cache; the post-run observation showed 548,663,296 anonymous bytes and 479,449,088 file-cache bytes. The database's lifetime peak/counters include the earlier failed interval and reset; they are not new-run process RSS. No larger memory allowance or relaxed threshold was used.

All five cycles withdrew the hot-cohort score after a pending sibling, added the two declared stable pairs, rebuilt and checked exact member hashes, raw/source counts and scoring consistency. Independent final SQL reconciliation found no missing/extra member, leftover invalidating row or dirty group. Production/candidate container IDs, images and mounts compared byte-identically before/after. The owned API stopped, load process exited and shared measurement lock was verified free before operations received explicit handback for native acceptance.

The complete failed synthetic database was preserved first as `/mnt/NVME/docker/encodingdb-operations/20260920-projection-b3ef24a/failed-939823e-before-reset.dump`, SHA256 `b7d094721595480f35ea3ce6158403844e10557046d7eab2c4137942b394a833`. Original full interval receipts remain under `docs/collection-readiness/projection-p910-20260920`.

A bounded reset ran under the shared host lock on the old immutable `939823e` runtime from **03:49:20.072 to 03:49:52.161 UTC on 20 September 2026**. It verified and removed only the 20 documented arrival rows from the completed prior trial, their matching analyses/artifacts and memberships, then rebuilt the two affected cohorts through production persistence. No production, candidate or calibration database was touched. The original 100,000 runs/artifacts/analyses, 981 derived cohorts and 80,000 qualified members are restored. All original hot/normal/distant member hashes, centers, PL values and raw/source counts matched exactly. Independent global SQL set reconciliation found zero missing/extra members or dirty groups. `reset-seed.json` records every removed run ID and all checks.

The first reset attempt failed before any delete statement and rolled back: JavaScript and Prisma/PostgreSQL rendered one generated floating-point value one ULP differently. The retained assertion is in `reset-assertion-serialization.txt`. The corrected guard round-trips expected fractional scalars through the identical PostgreSQL/Prisma path and requires exact equality; no numeric tolerance or measurement criterion changed. This was a fixture-guard correction, not a repeated capacity trial.

Preparation overlapped only the root-authorized image/package build phase. Operations explicitly handed back the quiet host at 03:56:31 UTC, and root then granted the measured interval. The repeat retains 25 readers, 600 seconds, five writer cycles, the 1 GiB database cap, 30 connections, zero-error requirement and p95 ≤1,000 ms. The retained database container's lifetime counters include the prior trial; before/after counters and interval samples must distinguish that history from the new run.


The complete 33,266-byte `measurement.json` was copied during an operations-approved gap before the next native process started; `measurement.json.gz` preserves it unchanged, including all interval resource samples, every writer receipt and the empty failure list. `summary.json` contains its uncompressed SHA256 and exact numerical results. `run-trial.sh` is the executed coordinator, including the common lock, unchanged workload, final reconciliation, preservation comparison and shutdown trap. Supporting database/runtime/preservation logs remain durably in `/mnt/NVME/docker/encodingdb-operations/20260920-projection-b3ef24a/evidence`; no extra P910 query, archive-generation or load ran during the subsequent native timing allocation.

This proof covers the specified metadata/API read-model workload only. It does not certify browser rendering, frontend-proxy latency, simultaneous media-worker throughput, calibration validity or production promotion.
