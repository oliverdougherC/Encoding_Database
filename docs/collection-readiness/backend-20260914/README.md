# Authoritative collection backend verification — 2026-09-14

Implemented PLA-551 through PLA-555 on the current-main collection branch. This is backend implementation and isolated verification evidence, not production approval or PL calibration.

## Contract and recovery behavior

- Canonical contribution requires protocol `7.1`, `client/0.3.0` or newer, `encodeTimerBoundary=ffmpeg-process-v1`, a persistent physical-source pseudonym, installed worker `authoritative-analysis/v2`, and the frozen server-owned suite/hash. `/v7/compatibility` exposes the protocol, client minimum and timer boundary before client encoding.
- Source/encoded counts must match the complete clip. Wall time is an integer 1 ms–24 h; FPS and real-time ratio must agree with canonical count/duration and wall time within 0.2% (0.001 absolute floor). Source cadence must match the exact rational manifest. Old measurements are not rewritten or relabeled.
- The upload/worker gate decodes the entire video and requires the exact count, zero-origin presentation timestamps at canonical cadence (1.1 ms timestamp tolerance for container time bases), duration within 2 ms, progressive frames, expected output and color. VMAF and all three diagnostic metrics must each cover every frame exactly once. FFmpeg frame synchronization cannot repeat the last reference frame. The existing XPSNR cadence repair remains intact.
- PostgreSQL transaction advisory locking reserves pending/analysis capacity and logical bytes at create, includes uploaded-but-not-yet-queued work, and gates upload slots across processes sharing the database and artifact root. Valid reservations drain at the cap; expired reservations must reacquire capacity. Defaults: 24 h reservation, 5 min upload deadline, existing configured upload and analysis caps. Expired incomplete staging older than at least 24 h is reclaimed conservatively at startup, at most 1,000 entries per pass; quarantined and retained evidence is not removed.
- Idempotency keys are checked against a server-computed immutable digest, including source pseudonym/timer identity, telemetry and artifact identity. Identical concurrent creates converge. Reusing a key with altered contents conflicts. Published uploads verify retry bytes without staging a second copy or regressing disposition. Transport truncation/hash corruption remains retryable; hash-verified bad media is quarantined with its evidence key.
- Anonymous contribution remains public. Reanalysis requires `V7_OPERATOR_TOKEN`, `V7_OPERATOR_ID`, and a reason. Caller model/worker labels cannot invent an installed identity. Duplicate enqueue preserves active leases and terminal analyses. Queue admission applies to reanalysis too.
- Native execution owns a process group, a 5 min configurable deadline (probe default 60 s), combined output bounds, and cancellation. Both metric inputs and ffprobe decode with one thread; filters/metrics are bounded separately. Canonical/artifact hashing streams bytes, after checking the expected size. Whole-process memory remains a deployment resource limit.
- Analysis leases renew every third of the lease interval. Completion/retry/failure all require the current unexpired claim. Expired poison jobs terminate at the attempt limit. Aggregate failure does not erase successful immutable analysis: `recomputePending` persists and retries separately, including uploaded work interrupted before queue insertion.
- Recompute holds PostgreSQL advisory lock `714555` over its reads and writes. Review invalidation uses the same lock. Acknowledgement compares `updatedAt`, so a late rebuild cannot erase newer invalidation. Selection uses immutable analysis `createdAt,id`, never review/retry `updatedAt`; a newer pending/suspect analysis cannot inherit an older expected-disagreement review. Review-adjusted eligibility, calibrated policy and persistent physical-source independence are applied during online rebuild.
- Corrected protocols do not automatically inherit historical reference contexts. Explicit reviewed context activation and public unscored visibility remain integrator responsibilities.

The server checks decoded pixels and metadata consistency. It does not cryptographically attest anonymous hardware timing or establish independent physical machines solely from contributor claims. Structurally valid duplicated pixel content cannot in general be distinguished from legitimately static/compressed content by timestamps; perceptual review and independent evidence remain necessary.

## Executed checks

The exact full transcript is `server-tests.tap`. Commands executed in the backend worktree:

```sh
npm --prefix server ci --no-audit --no-fund
cd server
npx prisma generate
DATABASE_URL="$ISOLATED_BACKEND_DB" npx prisma migrate deploy
npm run build
BACKEND_TEST_DATABASE_URL="$ISOLATED_BACKEND_DB" \
REVIEW_TEST_DATABASE_URL="$ISOLATED_BACKEND_DB" \
CALIBRATION_TEST_DATABASE_URL="$ISOLATED_BACKEND_DB" \
node --test --test-concurrency=1 test/*.test.js
```

PostgreSQL 16 was an isolated Docker database `encodingdb_backend`, with all 25 migrations applied. The test refuses a differently named backend database. No production database or artifact volume was touched.

The fault suite runs real PostgreSQL contention from two independent Prisma connections, 12 identical creates, 25 concurrent admissions at cap two, immutable conflicts, reservation expiry/drain, quota/near-full rollback, globally bounded slots, duplicate active enqueue, explicit stale completion/retry rejection, lease renewal across a slow valid job, poison-worker expiry, transport recovery, durable rebuild retry, and deliberately out-of-order aggregate snapshots. It also appends an older synthetic EXPECTED review and verifies that review time cannot select the old analysis, and that a newer PENDING analysis blocks it.

Actual native processes exercise deadline, output overflow, cancellation and child-process cleanup. Real FFmpeg media fixtures include truncated, extra-frame, wrong-FPS, timestamp-offset and duplicate timestamp cases. A one-frame 1080p artifact is run through the real durable worker: it becomes FAILED/INVALID and its exact bytes remain present. No synthetic scale/test rows are calibration evidence.

## Seven-clip worker trial

`seven-clip-worker.json`, `seven-clip-worker.log` and `seven-clip-worker-time.log` preserve the exact successful local trial. Run with:

```sh
BACKEND_MEDIA_ARTIFACT_DIR=/path/to/preserved/trial \
BACKEND_MEDIA_REPORT=/path/to/report.json \
PATH=/path/to/verified/native-runtime:$PATH \
/usr/bin/time -l node test/v7-real-media.mjs
```

The runtime was the integrator's native arm64 FFmpeg 9.0 build with pinned VMAF 3.2. The host Homebrew runtime could not load the required speed/chroma model feature and was rejected rather than substituted. The trial used all seven frozen 1920×1080 24 fps SDR BT.709 clips with libx264 veryfast CRF23, and independently ran probe, VMAF, XPSNR, SSIM and PSNR.

All seven passed complete frame coverage: six ×240 frames and animation ×192. Five analyses were COMPLETE. Film grain and dark gradients remained SUSPECT due to metric disagreement; no human approval was fabricated and no flags were suppressed. The exact encoded outputs and complete per-frame analysis reports are preserved under:

`/Users/ofhd/Developer/Encoding_Database/.build/evidence/backend-seven-v2-bounded/`

The prior v2 trial before resource tightening is preserved separately under `backend-seven-v2/`. This is a local functional worker trial, not a canonical packaged-client campaign or calibrated RC matrix.

The bounded trial took 312.76 s wall time. Darwin `/usr/bin/time -l` reported **2,572,140,544 bytes maximum resident set size** and **90,429,152 bytes peak memory footprint**. These are distinct raw utility fields; the latter is not a claim that the full native worker uses 90 MB. This experiment ran one analysis at a time amid local development work. It does not certify Linux/P910 cgroup memory, concurrency two, sustained production throughput, or a smaller replacement for the configured 16 GiB production budget.

## Remaining integration and external gates

Wire `stopArtifactPipelineBackgroundWork()` into shutdown before disconnecting Prisma; mount the review router with the shared operator helper and cache invalidation. Apply migrations and explicitly activate the new collection protocol without rewriting history. Re-run integrated packaged-client, deployment, concurrency and public-visibility checks on the final integrated commit. The broader native-platform/device matrix, perceptual review of the preserved SUSPECT evidence, independent-source calibration/holdouts and production promotion remain outside this backend trial's proof.
