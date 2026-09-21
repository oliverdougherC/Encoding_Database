# P910 repeat against the final candidate runtime

**FAIL: the declared p95 latency gate was missed.** The full 600-second interval plus drain ran from **2026-09-20 01:57:16.482 to 02:07:17.784 UTC**. All integrity, mutation and error-count assertions passed, but p95 was **1,062.50 ms**, above the unchanged **1,000 ms** target. This result is retained; the passing Mac trial does not override it.

| Measurement | Observed |
|---|---:|
| Starting runs / cohorts / qualified members | 100,000 / 981 / 80,000 |
| Concurrent HTTP readers / requests | 25 / 24,468 |
| Latency p50 / p95 / p99 / maximum | 608.45 / 1,062.50 / 1,423.45 / 2,437.57 ms |
| Reader, writer and assertion errors | 0 |
| Successful invalidation/arrival/recompute cycles | 5 of 5 |
| Final runs, artifacts and analyses | 100,020 each |
| Final exact qualified members | 80,020 |
| Missing / unexpected members | 0 / 0 |
| Remaining pending invalidating rows / dirty groups | 0 / 0 |
| PostgreSQL OOM / OOM-kill events | 0 / 0 |
| Node process maximum RSS | 546,242,560 bytes |
| Maximum sampled database cgroup charge | 1,072,480,256 bytes |
| Database lifetime charge peak, including setup | 1,073,754,112 bytes |
| Minimum available evidence-volume disk | 1,579,437,391,872 bytes |

The measured API ran in the exact AMD64 candidate server image `sha256:f3acd4ee49ff07ab14645a85bdbe55f94de5cbd2c3a91176612128c8874663ee`, source `939823ead2c052572f9deb5c9f91c85435d5661d`, using its Node **v20.20.2** and compiled production modules. The readonly mounted test-only harness was revision `acd1d98` (root integration `7bdcf2d`); its exact file hashes are retained. The host is Linux `6.8.0-139-generic`, x86_64, dual Xeon E5-2699 v4, 88 logical CPUs. PostgreSQL **16.15 Debian AMD64** image `sha256:a3b7f434b2dc57ce85a67e171163eb8ab1a1ebcb39d27484661f26b1dfbe30d6` used a fresh task-only volume and network.

Database RAM and swap limits remained **1 GiB each**, shared memory **256 MiB**, `shared_buffers=128MB`, `work_mem=4MB`, `max_connections=100`, and Prisma connection limit **30**. The disposable API container used the existing production server's **16 GiB** memory cap. The load generator used the same image's copied Node binary and modules in a task directory; it was separate from the API process. No resource, concurrency, workload, transaction scope or pass criterion was changed from the documented repeat design.

Memory pressure was visible without OOM: the final database cgroup observation contained **590,147,584 anonymous bytes**, **451,301,376 file-cache bytes**, 2,390 `memory.events:max` events, 167,232 direct-reclaim scanned/stolen pages, and zero major page faults. These are cgroup accounting and cache/reclaim statistics, not an unreclaimable working-RSS estimate. The lifetime peak includes setup and a small transient charge above the configured maximum. Complete before/after `memory.stat` and all interval samples are retained. This result does not justify raising supported concurrency or reducing memory.

Unrelated Jellyfin thumbnail FFmpeg work was present and untouched. At both interval endpoints an FFmpeg process parented by Jellyfin was using approximately one CPU core; the PID changed between observations. Endpoint observations do not establish that this workload caused the latency miss. A root-authorized 5.50 GB read-only source-reference transfer occurred during fixture seeding only; the coordinator shell was explicitly stopped while its seed child continued, and was resumed after root confirmed transfer completion at **01:49:08 UTC**. No transfer overlapped readiness or measured traffic.

Isolation was verified: only the synthetic database `encodingdb_projection_synthetic` at loopback port 55441 received fixtures, and only the separate wrapper at loopback 55442 exposed them. All 29 migrations and the full fresh seed completed before the interval. The common host measurement lock covered seed, measurement and reconciliation. Production and candidate container IDs, images and mount records were byte-identical before and after. No media, production/candidate/calibration context or human evidence was created by this harness. The API container stopped and the lock was released before explicit handback for native acceptance; synthetic database evidence remains retained.

`raw-evidence.tar.gz` contains the executed `run-trial.sh`, exact mounted harness, seed/migration/runtime receipts, full measurement JSON, all five writer receipts, independent SQL set reconciliation, interval PostgreSQL logs, before/after resource records, and production/candidate preservation checks. The bundle includes per-file SHA256 records; `summary.json` records its archive hash. The task directory on P910 is `/mnt/NVME/docker/encodingdb-operations/20260920-projection-939823e`.

This is an HTTP metadata/read-model capacity experiment. It does not certify browser rendering, frontend proxy latency, quality-worker throughput, media calibration or production promotion. The next justified diagnostic is a bounded per-route timing and actual-query-plan capture outside any native timing interval, followed by a narrowly scoped fix only if a specific bottleneck is demonstrated. The failed target must remain visible until an unchanged complete repeat passes.
