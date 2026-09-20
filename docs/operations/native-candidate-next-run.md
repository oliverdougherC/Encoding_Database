# Next isolated Linux contribution acceptance

Status: harness prepared locally from source `1a12471` and verified on September
19, 2026. Final application source is not yet pinned. No command below authorizes
overlap with scoring's exclusive P910 timing
allocation. Wait for its explicit handback and the integrator's final SHA. These
steps concern the existing isolated candidate only, never production.

## Fixed topology and identity

- Candidate checkout: `/mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c`.
- Compose file: `candidate.compose.json`; project `encodingdb-candidate-730de3c`.
- Existing volumes: `encodingdb-candidate-730de3c_db_data` and
  `encodingdb-candidate-730de3c_artifact_data`. Preserve their exact bindings.
- Existing candidate network: `encodingdb-candidate-730de3c_app`; no production or
  `npm_default` network membership.
- Loopback API/frontend/DB: 3091/3092/3093; trusted nginx TLS: 3094; HTTP: 3095.
  The task-owned transport-fault proxy will use loopback TLS 3096 only.
- Existing public cert and private key remain under candidate
  `nginx/dev-certs/`. The public certificate already copied to the Mac is
  `.test-reports/release-20260914/p910-candidate-ca.crt`. Never print/copy the key
  or candidate `.env` into receipts. The proxy uses those existing local files.
- Reuse physical state and outer lock at
  `/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts/host-state`.
  The native client still has its own queue lock; it is not a substitute for
  the explicit outer host allocation and `host-state/measurement.lock`.

## Build and update phase, before any native timing

1. Receive the final reviewed bundle. Verify its prerequisites, fetch its exact
   commit, and check out that SHA in the candidate. Record the commit and bundle
   SHA256. Preserve private `.env`, candidate compose overrides, certs and volumes.
   Do not use a prior package or runtime-registration override as final proof.
2. Read-only inspect the four candidate containers' project labels, mounts,
   networks and resource limits, and the current production container IDs/start
   times as an unchanged baseline. Check fresh free storage and MemAvailable.
   The measured production envelope remains two analyzers / 16 GiB, PostgreSQL
   1 GiB with 256 MiB shared memory, and 10 GiB retained artifact quota.
3. Run `node scripts/verify-deployment-volumes.mjs candidate.compose.json` before
   build and again immediately before rollout. Use the existing task-owned Node
   runtime if host PATH has none. Keep explicit candidate volume names in both
   `.env` and compose overrides. Any mismatch aborts the rollout.
4. Create a paired candidate backup and isolated restore using the existing
   candidate `cron-backup` private configuration and final source
   `scripts/v7-scheduled-backup.sh`. Do not reinstall cron. The wrapper's actual
   PostgreSQL-container clients avoid assuming host pg_dump/node availability.
   Record backup inventory/checksum, restore result and original-container restart.
5. Build final tags `encodingdb-candidate-server:<final-short-sha>` and
   `encodingdb-candidate-frontend:<final-short-sha>` from final server/frontend
   contexts. Save complete build logs and immutable Docker image IDs. Ensure the
   candidate service command matches final source:
   `npx prisma migrate deploy && node scripts/rebuild-corpus.mjs --enqueue-all && node dist/index.js`.
   Preserve ports/volumes/network rather than copying the production compose over
   the candidate overrides. Keep analysis concurrency zero during native timing;
   this explicitly pauses worker claims, whereas disabling auto-enqueue alone
   would not stop old queued work. Leave automatic analysis enqueue enabled.
6. Run the final image's migrations, then `prisma migrate status`. The local
   prepared pin contains **29 migration.sql files**; check the final source count
   and verify each migration name/checksum against successful `_prisma_migrations`
   rows, with no unfinished/rolled-back entry. A changed final migration count
   needs a new recorded expected manifest, not a hard-coded green count.
7. Start only the candidate with `docker compose -f candidate.compose.json up -d
   --no-build --pull never --wait`. Verify image IDs/mounts and bounded `/health/ready`,
   `/health/v7-evidence`, corpus and actual frontend. Run
   `scripts/production_smoke.sh` with API_BASE_URL and APP_URL both
   `https://127.0.0.1:3094`, and CURL_CA_BUNDLE set to the existing public cert.
   Production IDs/start times must remain unchanged.
8. Build the Linux executable from the same final checkout with
   `scripts/build_linux_client.sh`. Existing runtime directory is
   `/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/runtime/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1/bin`;
   existing Python 3.11 is under that native root's `python/bin`. Use the build
   script's ENCODINGDB_RUNTIME_BUNDLE_DIR / ENCODINGDB_FFMPEG_PATH /
   ENCODINGDB_FFPROBE_PATH build inputs;
   do not update the lock. Record package, lock, helper/dependency and suite hashes,
   signing sidecar and exact helper architecture. The earlier source84 package
   does not satisfy this final-source step.

## Native timing phase

Copy the final executable outside the checkout into a new evidence directory
with a Japanese/space path. Use that working directory as parent of both queues;
otherwise the client correctly rejects unsafe sibling queue paths. Start with an
empty suite cache, preserve the existing physical state, and scrub FFMPEG_EXE,
FFPROBE_EXE, ENCODINGDB_FFMPEG_PATH, ENCODINGDB_FFPROBE_PATH, runtime-lock overrides,
PYTHONPATH/PYTHONHOME and loader overrides. Set REQUESTS_CA_BUNDLE to an owned bundle
containing the existing certifi public roots plus the candidate public cert:
a candidate-only bundle replaces public trust and fails the advertised GitHub
download. Set ENCODINGDB_STATE_DIR to the existing host-state, and a new
ENCODINGDB_SUITE_CACHE_DIR. First verify actual clean acquisition from the frozen
advertised URL; a later explicit local pack fallback must be labeled separately.
Use execve tracing only for a separate runtime-path smoke diagnostic. Ordinary
full campaigns must run **without a tracer**: `strace -f -e trace=execve` without
seccomp filtering still imposes syscall interception overhead. Prove the ordinary
campaign helper paths and hashes through the packaged runtime receipt plus saved
executed-command/process receipts, which must resolve into `_MEI.../bin/linux/`.
Instrumented smoke timings are not ordinary performance or calibration evidence.
Do not upload while any timing is active.

Under the outer shared `flock -n`, use the real final executable for these two
predeclared complete campaigns (replace queue names only with owned absolute paths):

```sh
./encodingdb-client-linux --cli --campaign full --codec libx264 --presets medium \
  --crf 24 --no-submit --max-attempts 35 --max-duration-minutes 45 \
  --max-storage-mb 2048 --queue-dir "$software_queue" --base-url https://127.0.0.1:3094
./encodingdb-client-linux --cli --campaign full --codec h264_nvenc --presets p4 \
  --target-bitrate-kbps 4000 --no-submit --max-attempts 35 --max-duration-minutes 45 \
  --max-storage-mb 2048 --queue-dir "$nvenc_queue" --base-url https://127.0.0.1:3094
```

Require actual NVENC device-0 selection, driver/runtime observation, valid fresh
CPU/GPU samples, exact native VBR command and unchanged runtime bytes. Inspect all
seven clip groups per campaign: attempts, warmups, measured/adaptive repeats,
quality-independent timing validity and final stability receipts. A nonzero exit,
missing clip, unobserved environment, invalid or unstable group is retained and
reported; no flags or thresholds are edited to qualify it. These operational
campaigns do not replace the separately declared calibration matrix.

After each completed campaign, run `native-e2e-ledger.py capture` before any
publication. The ledger verifies journal artifact SHA256s and retains original
manifest/attempt/artifact hashes, while allowing the retry spool to change.

## Upload and recovery phase, after timing has ended

Start `candidate-upload-fault-proxy.mjs` using the existing task Node and these
explicit values: CANDIDATE_UPSTREAM_URL=https://127.0.0.1:3094,
CANDIDATE_FAULT_PORT=3096, CANDIDATE_CA_FILE/CERT_FILE/KEY_FILE pointing to existing
candidate cert files, a private CANDIDATE_FAULT_MODE_FILE, and a new exclusive
CANDIDATE_FAULT_EVIDENCE JSONL path. The mode file contains one plain word:
`offline`, `pressure`, `lost-response-once` or `pass`; replace it atomically.
The proxy streams bodies, limits active requests to four, request bodies to
256 MiB and upstream responses to 1 MiB, enforces a 300-second wall deadline,
redacts tokens, rejects request URLs over 4096 characters, and caps receipts at
10,000 events.
Its transport faults are explicitly tagged injected, never described as server
admission-limit evidence. Both TLS hops validate certificates.

1. With `offline`, invoke the packaged client's `--resume-campaign <actual-id>
   --submit --queue-dir <same-queue> --base-url https://127.0.0.1:3096`. Completed
   campaigns must take upload-only behavior. Record truthful deferred exit/status,
   pending spool and untouched original artifacts. Compatibility reads still work.
2. Use `pressure` to verify the client preserves retryable authorization failures
   and Retry-After. Wait for the real spool retry deadline; never rewrite it.
3. To exercise **real** server capacity, keep proxy mode `pass`, set candidate
   pending-analysis cap to two and worker concurrency to zero, restart only the
   candidate server with unchanged image/volumes, then replay due entries. Two
   admitted uploads must remain completable; subsequent run admission must receive
   actual bounded backpressure. Capture observed server response codes, pending
   counts/reservations and the source-tagged forwarded proxy receipt. Do not infer
   this result from the injected pressure test.
4. Restore the candidate's original limits from a private pre-test snapshot and
   set its declared analysis concurrency to two. Use `lost-response-once` on the
   next due upload: the proxy forwards all bytes and consumes a successful upstream
   response before dropping the client response. Replay using the native executable
   with `--upload-only`; the server must retain the original run/artifact identity
   and complete idempotently. The fault must be observed in a real PUT, not assumed.
5. Set mode `pass`, honor retry deadlines, and drain all due campaign uploads and
   analysis. Poll bounded health and exact campaign IDs to a predeclared deadline;
   report actual terminal statuses separately from upload completion. A timeout
   remains a failure with retained state. At the source84 finite batch rate, 28
   measured uploads can require roughly 23 minutes at two workers; use a 60-minute
   drain budget and record actual latency rather than promising that estimate.
6. Run `native-e2e-ledger.py assert` after every replay phase. A completed-campaign
   replay must start no encode; inspect execution traces, immutable bytes and
   attempt counts. Preserve token-free HTTP receipts and all client exit codes.
7. With final Prisma and campaign IDs read from the real journals, reconcile exact
   run payload identities, artifact SHA/byte sizes/storage states, worker/model and
   full frame coverage, final group receipts, and public/derived membership after
   queue drain. Verify each original object on disk; check missing/duplicate members
   and physical source ID equality with the preexisting host-state. Show SUSPECT,
   REJECTED and FAILED evidence honestly; do not bulk-review it or infer ACCEPTED
   from client upload success. Re-run both-surface TLS smoke and restart/rebuild
   persistence checks, then paired candidate backup/restore with retained objects.

## Required handoffs and remaining evidence

No additional production authority, installed package, elevated client, driver
change or external alert is needed for this isolated lane. It needs the final
reviewed source/package pin, explicit P910 quiet allocation, existing candidate
private configuration/cert paths, sufficient fresh disk/RAM, and honest native
hardware readiness. Reuse the existing runtime and backup helpers. Any unavailable
resource or failed threshold is recorded before deciding a bounded repair; it is
not waived. The prepared proxy's local TLS tests and ledger tests establish harness
behavior only. Final image, migrations, packaged runs, admission faults, retained
object/DB reconciliation and recovery must still be executed after handoff.

## Local harness verification

`node --test scripts/candidate-upload-fault-proxy.test.mjs`: **6 passed**.
Actual ephemeral loopback TLS connections exercise streamed 2 MiB uploads,
injected 503/429 with Retry-After, consumption of a successful upstream upload
before disconnecting its client, failed-upload rearming, certificate rejection,
active-request admission, body/response size limits and the wall deadline.
Authorization headers and upload tokens are absent from retained event records.

`python3 -m unittest discover -s scripts -p test_native_e2e_ledger.py`: **4 passed**.
The ledger hashes original manifests, completion markers, attempt records and
artifact bytes. Tests permit changing the retry spool while rejecting changed
measurements/completion markers, new attempts, journal SHA mismatches, incomplete
campaigns, out-of-campaign artifacts and symlinked external records.

Logs: `docs/operations/evidence/native-e2e-harness-20260919/`. These tests used
ephemeral test certificates and synthetic bytes locally, never the candidate
database, calibration corpus or production.
