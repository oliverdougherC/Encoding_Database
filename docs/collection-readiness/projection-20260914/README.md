# Scored projection capacity, 14 September 2026

The first trial **failed** the declared capacity gate. All 600 seconds ran: 07:03:16.145–07:13:20.707 UTC including final in-flight drain. Source: `c9a9654493dcc66e8d65673b553f0eaa98170237`, including production collation fix `bc8300a`.

| Measurement | Observed |
|---|---:|
| Concurrent HTTP readers | 25 |
| Requests | 42,739 |
| Latency p50 / p95 / p99 | 299.65 / 881.45 / 980.01 ms |
| Reader errors | 15,988 |
| Writer errors / successful cycles | 5 / 0 |
| PostgreSQL OOM kills | 11 |
| Node process maximum RSS | 395,460,608 bytes |
| Sampled DB cgroup maximum | 1,073,438,720 bytes |
| DB cgroup limit / shared memory | 1,073,741,824 / 268,435,456 bytes |
| Minimum available host disk | 3,656,110,080 bytes |
| Initial / final runs | 100,000 / 100,010 |
| Initial / final qualified members | 80,000 / 80,000 |

The target was p95 ≤ 1,000 ms **and zero request/assertion failures**. Fast recovery-mode error responses and withdrawn hot-cohort scores make the p95 alone insufficient evidence. The intended final counts were 100,020 runs and 80,020 qualified members. The receipt retains every failure, not just successful timings.

The loopback-only PostgreSQL 16.15 ARM64 container had 1 GiB RAM, 256 MiB shared memory, `shared_buffers=128MB`, `work_mem=4MB`, `max_connections=100`. The API Prisma pool allowed 30 connections; 28 idle sessions were observed immediately after traffic. Public read transactions explicitly disable PostgreSQL parallel query workers. Node ran natively on the ARM64 Mac; PostgreSQL ran in Docker Desktop. This is a metadata/API proof, **not Chromium rendering, frontend-proxy latency, P910 capacity or media-worker throughput**.

All synthetic identities are marked `SYNTHETIC-PROJECTION-ONLY`. The fixture has 981 cohorts: 980 with 100 observations and a hot cohort with 2,000. Each 100-row block includes 80 stable observations in 40 complete groups, 16 unstable observations in four groups, and four incomplete observations. Corrected CPU markers are present. Production aggregate persistence created the scored results and their 80,000 actual qualified members. No media bytes, human reviews, production contexts or calibration approvals were fabricated. Test-only context allowlisting exists only in the loopback HTTP wrapper.

The first setup attempt exposed a separate membership-certificate collation defect with hyphenated identifiers. Both publication and verification now use SQL `COLLATE C`; the actual PostgreSQL regression includes namespaced Unicode IDs whose JavaScript UTF16 order differs. Setup diagnostics are retained separately. An unbounded test-only primary-key rewrite exhausted advisory-lock capacity and rolled back completely; bounded recovery was then used. The measured trial itself started from a clean database and a fresh 100,000-row seed.

The five writer calls also exposed a harness difference: direct aggregate persistence inherited Prisma's five-second transaction timeout, while the deployed recompute callback uses 30 seconds. The next harness revision uses that same production scope. This does not explain away the independent PostgreSQL OOM failures during concurrent reads.

Actual plans after traffic showed the old state certificate sorting 1,610 complete metadata records at estimated width 1,951 bytes and evaluating twice per scored result. The hot sort used 3,122 KiB; a 25-row scored page evaluated it 50 times. Production fix `edb97fd` hashes each complete row first and materializes one page certificate, preserving every eligibility field and full-group scope. The comparable hot sort now uses 287 KiB at width 64, with one evaluation; single-query diagnostic execution fell from 157.7 to 65.8 ms for the hot detail and 318.8 to 153.7 ms for the scored page. These serial diagnostic timings occurred after the quiet interval and **are not a second capacity pass**.

Certificate v3 has a restart upgrade path: old versions in the explicitly validated active context are revalidated/rebuilt even with clean dependency markers. The eight focused PostgreSQL tests preserve numeric scores and exact members through upgrade, and preserve historical contexts. Existing deployment-artifact behavior-hash validation remains required.

The compressed raw failed receipt and database logs preserve the full interval. `raw-sha256.json` contains hashes of their uncompressed bytes. The harness and commands are in `scripts/projection-scale/`. `host.json` records the initial container setup; seed startup used `16e47a4`, and the final seed receipt records the repository HEAD at completion. Changes between seed startup and trial source pin affected sampling only. The second sustained trial passed on 20 September after a newly coordinated quiet window; see [the complete repeat receipt](trial-2/README.md). The original failure remains part of the evidence.
