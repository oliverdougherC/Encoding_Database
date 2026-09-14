# Finite corrected-timing matrix runner

Status: **runner rehearsed; calibration unexecuted**. No real measurements, uploads,
human judgments, or calibrated PL claims are produced by the runner tests.

`python3 scripts/run-calibration-matrix.py` orchestrates the frozen
`server/config/calibration/final1080p-corrected-timing.matrix-v1.json` using an exact
native packaged CLI. Python uses only its standard library. The runner supports
macOS/Linux; it does not certify Windows or any encoder/device.

The matrix contains 252 recipe/workload cells and two timing sessions. Software
cells run on both physical sources, so the complete schedule is 840 cell/sessions:

| Actual host | Explicit source slots | Recipes per session | Cell/sessions | Maximum encodes |
| --- | --- | ---: | ---: | ---: |
| Mac | `source-a`, `videotoolbox-host` | 196 | 392 | 1,960 |
| P910 | `source-b`, `nvenc-host` | 224 | 448 | 2,240 |

The same Mac pseudonym must appear for both Mac slots; likewise on P910. Two sessions
are not independent machines. The ledger binds observed physical-source and runtime
identity and refuses a changed identity within one host root. Missing hardware or
implementation is a failed cell, never a substituted encoder.

Each invocation defaults to **plan only**, printing every selected cell and command
without creating the campaign root. Execution defaults to **one cell/session**, a
30-minute invocation budget, a 10-minute cell budget, 16 GiB total retained storage,
and 1 GiB per-cell queue, plus an actual free-space reserve of 2 GiB (`--disk-reserve-mb`). This is an operator calibration schedule, not a normal
contributor default. Complete campaigns can take substantial time; consciously raise
`--max-cells`, `--max-duration-minutes`, `--cell-minutes`, and storage limits after
reviewing the printed schedule and the first actual timing receipt.

## Mac plan and first execution

From the exact integrated checkout (replace executable/root paths as appropriate):

```bash
python3 scripts/run-calibration-matrix.py \
  --cli "$PWD/.build/release-20260914/macos/encodingdb-client-macos" \
  --source-slot source-a --source-slot videotoolbox-host --sessions 1,2 \
  --output "$PWD/.build/calibration-final1080p-mac"
```

When the integrator has reviewed the final packaged candidate and established a quiet
host, repeat the same command with `--execute --client-source-sha FULL_BUILD_COMMIT`.
`FULL_BUILD_COMMIT` must be the actual 40-character source commit of the binary,
not an assumed current checkout revision. Keep all helper/runtime and canonical-cache
environment variables appropriate to that exact package. No submission occurs during
timing: every timed command contains `--no-submit`, and local metrics are disabled.

For P910 use its exact final Linux package, `--source-slot source-b --source-slot
nvenc-host`, and a dedicated root under
`/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate`.
See `docs/native-linux/20260914-discovery/README.md` for the authorized host, native
runtime and build prerequisites. Discovery artifacts are not final certification.

## Durability and limits

Cell order is a stable SHA256 order derived from matrix version, declared seed,
source slot, session and cell ID; session 1 completes before session 2. Each cell's
seed is passed through the client's supported `ENCODINGDB_PROTOCOL_SEED` environment
variable. Each queue belongs to exactly one cell/session. Restart discovers its
retained campaign manifest and calls `--resume-campaign ID`; clean completed markers
skip encoding. Failed/skipped completions stop the invocation. Completed attempts and
raw-process checkpoints remain owned by the client, which validates and resumes them.

The atomic, fsynced `ledger.json` records matrix, runner and executable hashes,
operator-declared build SHA, exact commands, seeds, timestamps, exit codes and log
hashes. It snapshots campaign manifests (including runtime/device/physical source),
source/artifact SHA evidence, schedule identities, and upload receipts containing
server IDs. An interrupted call keeps a null exit code rather than inventing one;
subsequent journal discovery can establish completion without another encode.

Two advisory locks protect execution: one in the output root and a host lock at
`ENCODINGDB_STATE_DIR/measurement.lock`. Without the environment override, the runner
uses the same default state directory as the client (macOS Application Support or
Linux XDG state). All matrix roots on a host must share that existing state directory;
never manufacture another installation/physical-source identity per matrix cell.
Both descriptors are inherited by the packaged child, so killing only the runner
cannot allow another root to overlap its surviving CLI. Client-owned orphan recovery
handles a crash in the measured process. Other benchmarks and analysis workers still
require a quiet-host check; they do not necessarily cooperate with this runner lock.

The runner checks actual filesystem free space and aggregate retained bytes before
each cell, reserving its remaining cell allowance plus at least 16 MiB for logs and
atomic metadata, in addition to the 2 GiB reserve. It passes the cell limit to the
client's output guard. Storage pauses retain the journal and ledger and return 6.
Upload admission counts additional managed copies from the exact prepared artifacts;
shared copies are counted once and already receipted artifacts need no new copy.
Staging must fit the remaining total budget, the per-cell staging limit and actual
free space above the reserve. Sources, package extraction and concurrent unrelated
writes remain outside this campaign budget: provision those separately before timing.
The runner passes the remaining duration to the client;
a hung CLI is interrupted after the cell limit plus 30 seconds and killed after a
further 20 seconds. These bounded shutdown allowances are additional to the declared
timing budget. This may leave an incomplete cell that needs resume, never a valid
measurement fabricated from a timeout.

No runner-level variance retry is added: each recipe uses the current protocol's
one warmup, two required measured runs and at most two adaptive runs. The runner
requires the matrix's repetition bounds to match this protocol and clears inherited
`ENCODINGDB_PROTOCOL_STABILITY_THRESHOLD` and `ENCODINGDB_PROTOCOL_MAX_ADAPTIVE_REPEATS`
for its children. Other environment, including physical-source state, source caches,
CA settings and runtime paths, is preserved. Completed unstable groups are retained
and skipped during subsequent timing; completed groups containing failed/skipped
attempts stop with a terminal status rather than being retried. Curve expansion,
longer/disjoint scene experiments, fold fitting, review and anchor-bracketing decisions
remain separately declared experiments, not automatic reactions to holdout outcomes.

## Separate publication

Finish **all timing on both hosts**, including any independently declared timing
experiments that could be contaminated by worker load, before publication. Then repeat
the same host command and build SHA with:

```text
--execute --phase upload --all-host-timing-complete --base-url EXPLICIT_REVIEWED_TARGET
```

The acknowledgement is an operator statement about both hosts; the runner can only
verify every cell/session in its own root. It refuses incomplete local schedules and
never allows more timing after upload has begun in that root. The explicit target
prevents accidentally inheriting the production URL and is pinned in the upload ledger;
it cannot be changed while reusing receipts. This runbook does not authorize
production publication.

Publication calls `--upload-only --resume-campaign ID --retries 0`. It never re-encodes.
The client's persistent seven-day retry deadline, Retry-After and exponential backoff
remain authoritative. A queued response stops the call; the runner records the next
due time and refuses to retry early (at least 60 seconds). Reinvocation processes only
due, unfinished cells, up to the invocation budget. Do not poll it in a tight loop.
Upload exit 0 indicates successful publication, not acceptance or calibrated scoring.
A terminal upload (rejection, expiry, corrupt identity) is retained in the ledger and
is never automatically resubmitted. This also applies after a crash before the runner
recorded the client's exit: retained terminal/dead-letter files block another upload.
The ordinary client now commits `queue/terminal/<localHash>.json` before moving a dead
letter or deleting its active item. That tombstone retains the original retry deadline
and payload identity. `--upload-only --resume-campaign` returns failure for that identity
without recreating its deadline or copying/re-encoding the source again. Existing
legacy dead letters are indexed on first reuse or explicit cleanup. `--queue-cleanup`
may remove dead-letter media and old queue diagnostics, but preserves these tombstones
and original campaign-owned artifacts/submissions. It does not authorize a retry.
Deleting the entire queue/state outside the client would discard that local protection
and evidence; it is not a supported resume or remedy for a terminal result.
Runner exit 0 means the bounded invocation succeeded; inspect `timingComplete` versus
`selectedCellSessions` for whole-schedule completion. Exit 10 means deferred upload or
time budget, 6 a retention/configuration guard, 124 timeout, and 130 cancellation;
other client failures propagate.

## Verification receipt

On 2026-09-14, `python3 -m unittest client.tests.test_calibration_matrix_runner -v`
passed eight orchestration tests. Synthetic fake CLI fixtures are explicitly marked
and live only in temporary directories. Tests cover all 840 native command mappings,
deterministic slot/session selection, default nonexecution, interrupted resume,
completed-cell skips, upload separation/backoff, binary drift and exclusive locking.

The actual intermediate Mac package at `.build/release-20260914/macos/encodingdb-client-macos`
ran `--help` with exit 0; SHA256 was
`86beb2547f70b67f745e5df6ce13f4a25e862968f65fc8a5345629f12cbfa717`.
It **did not yet advertise `--max-duration-minutes`**, so it is unsuitable for runner
execution. The rebuilt candidate must pass that capability check. Its real CLI plan
selected all 392 Mac cell/sessions, maximum 1,960 encodes, while retaining the default
one-cell invocation limit; plan exit was 0. Neither help nor plan is native runtime
or calibration certification. Final package testing and actual quiet-host execution
remain integrator work.


## Capacity before the full Mac/P910 matrix

The latest reported Mac free space during the backend trial was **3.9 GiB**. Do not
launch the full schedule there. First finish the quiet trial and provision capacity
without deleting retained evidence. A 16 GiB campaign budget needs at least that much
additional free space plus the reserve, metadata and any uncached sources/runtime;
it is a stop limit, not proof that all recipes fit. Publication can require up to one
additional cell's measured artifacts (at most the configured 1 GiB staging limit), so
leave that much slack in the total budget or increase the declared budget on the
existing root before publication. With no measured size forecast, the conservative
sum of cell caps is 392 GiB for Mac and 448 GiB for P910, plus at least 1 GiB staging,
2 GiB reserve and metadata/source/runtime headroom. These are policy upper bounds,
not an assertion that actual encoded data will be that large. Use the first bounded
cell receipts to refine provisioning; CRF and unconstrained VBR targets are not hard
file-size ceilings. No frozen matrix choices or source pins change when a storage
budget increases.

After storage and quiet-host readiness are established, use the same reviewed package,
source SHA, matrix, seed and existing host state. The earlier plan command still
selects all 392/448 cell-sessions; append `--execute --max-cells 1` for a first bounded
slice, then consciously increase the invocation slice and duration. Never create a
new root with the same matrix/seed to bypass a terminal or space guard: that would
reproduce campaign identities. Completed groups remain complete, including unstable
ones; publication follows only after all hosts finish timing.

Guard verification on 2026-09-14: after the backend quiet interval ended, 61 focused
runner, terminal-publication, spool, durability and preparation tests passed. This
includes inherited host-lock survival, different-root exclusion, actual-space and
staging limits, protocol-override isolation, completed unstable upload exactly once,
terminal deadline preservation, legacy indexing/cleanup and crashes on both sides
of the dead-letter artifact rename. `compileall` and `git diff --check` passed.
No matrix campaign was started and no production upload was made by this review.
The packaged client must be rebuilt from the integrated commit to include ordinary
upload-only tombstone handling; source-level test success is not native certification.
