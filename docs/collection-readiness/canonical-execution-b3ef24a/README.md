# Canonical b3ef24a matrix execution proposal

**Plan only; no canonical cell has been launched by this packet.** Two local dry-plan invocations of the unchanged b3 runner produced the complete 448-cell/session P910 plan and 392-cell/session Mac plan. Native acceptance, publication demonstration, host allocation and adequate capacity remain prerequisites. The proposed directories have not been created by this task.

This packet uses source `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2`, the frozen matrix without edits, master seed `20260914` and sessions `1,2`. The runner deterministically derives per-cell seeds and orders both sessions; do not cherry-pick a favorable first recipe. There are 840 cell/session invocations, at least 2,520 warmup/measured attempts if every cell completes normally, and at most 4,200 attempts under the unchanged adaptive limits. Stable timing and eligibility are separate from execution completion.

Execution plan hash: `95fa4957bc2f610efabe783933b763c94362bf4fbf2447f5f5fd0986e50d0417`.

Runner SHA-256: `63c267aad259b24f50e71d540454b5e7563bf0473ce55a0717e25e8f5a4595bd`.

Frozen matrix file SHA-256: `28471be198b342733d57c0dcd75dc3fcef257d9ca96a4adc136d1b2ea812d373`; matrix semantic hash: `a3b676fe7e09ff9ed2f4f136193f2d3df16aca270b41b633c9c725276d3bb126`.

## Host and artifact bindings

| Host | Slots | Cell/sessions | Proposed initial total queue budget | Original installation identity |
| --- | --- | ---: | ---: | --- |
| P910 | `source-b`, `nvenc-host` | 448 | 16,384 MiB | `installation-3569f9d49855c02b183458161105102622a2ef46bfcfb739183eb390ba89a0b4` |
| Mac | `source-a`, `videotoolbox-host` | 392 | 8,192 MiB | `installation-17a3f0bdfe484d859dc5daf069d82ef5d3580563d7c33e0ed2cbe15b7746b7f6` |

The two slots on each machine reuse its existing physical state directory. Sessions and encoder slots do not create additional independent machines. Do not create or replace `physical-source-id` to satisfy a gate.

- Mac package SHA: `443e293e82f0f042b2017f55d12f1d73c7d5b6944cb43d6c9d70281beef6d70c`. Original build/embedded smoke evidence is in `../mac-build-b3ef24a`; its runtime floor is macOS 27, native ARM64, ad-hoc signed. The coordinator now reports AC and valid fresh software/VideoToolbox preflights; b3 seven-clip acceptance has started. Its completion and the retained upload demonstration remain gates.
- P910 package SHA: `3abd38ee72fa9f5afd9b81934717b3319f7f6143f2675038f6293798c078bf9a`. `linux-package-build-provenance.json` is the original build-only receipt. The verified binary currently resides at the candidate checkout root used in the plans. No b3 smoke/release sidecars existed at preparation time. Native ops has proposed a separate Japanese-path acceptance copy, but that path has not been created/verified and is not silently substituted here. If the coordinator selects a different final CLI path, regenerate and reseal this packet before first execution.

`execution.json` binds each original binary hash, filtered runtime-lock identity, exact runner/matrix paths, state directory, proposed output root and full argv. The binary hashes come from existing verified build receipts; this docs task neither accessed P910 nor reran a native binary.

## Finite initial allocation proposal

Use **one cell/session per initial invocation**, a **30-minute client measurement budget**, a **45-minute runner invocation budget**, a **1,024 MiB per-cell retained queue cap**, and a **5,120 MiB real filesystem reserve**. These limits are proposed for coordinator allocation; the full host matrix is not authorized merely by printing it.

The corrected 42 software holdouts provide a bounded reference: for 30-second sources, the largest observed per-attempt wall time was 41.968 seconds for x265 fast; maximum summed encode time in one cell was 159.299 seconds. SVT-AV1 preset 6 peaked at 26.992 seconds per attempt and 83.048 seconds summed per cell. All 42 cells, including the five unstable cells, were included in that budget reference. `budget-proposal.json` records the archive hash and exact summary.

These observations do not cover canonical x264/x265 slow presets or Mac timing. They do not establish that the runner's default ten minutes always suffices, nor justify changing presets. The proposed uniform 30 minutes gives a finite allowance without guessing a throughput guarantee. The runner bounds the whole child process to the selected cell minutes plus 30 seconds (1,830 seconds here), then gives SIGINT cleanup at most 20 seconds before SIGKILL. Native extraction/preparation also consumes that outer bound, so a cold cache can pause before the client's measurement budget expires. Pre-stage and verify required pack/cache/runtime data before allocating timing. Help validation has a separate 60-second bound before the runner starts its invocation clock.

A budget, interrupt or storage exit is a retained administrative pause; inspect its ledger and resume the same cell, recipe, seed and journal when allocated. Never delete completed attempts or restart a finished unstable cell to seek stability. Completed failed/skipped cells are terminal in this runner. Completed unstable timing groups retain their original eligibility status even if a campaign completion marker exists. Successful exit of a one-cell invocation does not mean the 392/448-cell host phase is complete.

## Gates and current blockers

1. Complete final b3 native acceptance and a retained-artifact upload demonstration on each relevant host **before** canonical timing. Those acceptance uploads are a separate validation phase; do not interleave publication with the canonical matrix.
2. The coordinator records a quiet host allocation, exact binary/runner/matrix hashes, original physical-source ID, proposed output root, concrete budgets and exclusive ownership. Recheck actual runtime bytes and remaining disk space at that handoff. No builds, imports, quality analysis, uploads or source preparation may run during timing. The matrix runner holds shared host and execution-root locks, inherited by its native child.
3. Mac must be on AC and its actual CPU/GPU environment must meet unchanged validity gates. The earlier battery hold has cleared: the coordinator reports AC, background CPU approximately 10–12% and VideoToolbox GPU 30.5% below the unchanged 35% threshold. Seven-clip b3 acceptance is in progress. Recheck those conditions at the later canonical allocation; no telemetry, stability or repetition threshold may be relaxed.
4. The reported Mac free space is only approximately **16 GiB**, and was not reprobed by this task. It is enough to consider a bounded first-cell allocation after fresh reserve checks, not evidence that all 392 cells fit. A full worst-case retention ceiling is 392 GiB on Mac and 448 GiB on P910 at the proposed 1 GiB/cell limit, plus metadata, source/runtime/cache files and publication staging. These are conservative caps, not predicted artifact sizes. P910 live filesystem capacity/allocation has not been checked here. Prefer a stable, sufficiently provisioned execution root before starting; do not assume absolute journal paths can be moved later without a reviewed preservation plan.
5. The initial 8/16 GiB total runner limits deliberately stop before uncontrolled growth. Use actual initial retained-byte receipts to assess whether further allocation can fit. Finishing the entire matrix may require more capacity and explicit larger limits, while preserving every observation and the same identities. No deletion, early bulk upload, recipe removal or threshold change is a capacity workaround.
6. All canonical timing on **both hosts**, and any other allocated timed experiment on a shared physical host, must finish before bulk publication/analysis. This is an operational cross-host gate: the runner only verifies its selected local cells and trusts the explicit `--all-host-timing-complete` assertion. The coordinator must collect both ledgers before setting it. The explicit upload target remains unset in this packet; do not infer production publication authority.

## Dry commands and first-cell handoff

The following target-host commands print plans only. Their local equivalents generated the archived JSON without running the native CLI, probing a host, creating a campaign root or contacting a server. Every proposed actual command is also stored as an argv array in `execution.json`.


### Mac

```sh
ENCODINGDB_STATE_DIR=/Users/ofhd/Developer/Encoding_Database/.build/release-20260914/mac-host-state \
  /Users/ofhd/Developer/Encoding_Database/.venv-release/bin/python /Users/ofhd/Developer/EncodingDB-worktrees/native-mac-b3ef24a/scripts/run-calibration-matrix.py --matrix /Users/ofhd/Developer/EncodingDB-worktrees/native-mac-b3ef24a/server/config/calibration/final1080p-corrected-timing.matrix-v1.json --cli /Users/ofhd/Developer/Encoding_Database/.build/release-20260919/macos-b3ef24a/encodingdb-client-macos --client-source-sha b3ef24abb020bc6af5b5fe6b849ba3eae8314be2 --sessions 1,2 --seed 20260914 --output /Users/ofhd/Developer/Encoding_Database/.build/release-20260920/canonical-matrix-b3ef24a --phase timing --max-cells 1 --max-duration-minutes 45 --cell-minutes 30 --max-storage-mb 8192 --cell-storage-mb 1024 --disk-reserve-mb 5120 --source-slot source-a --source-slot videotoolbox-host
```


First planned cell: `source-a/session-1/fit-animation-1080p24-final-libsvtav1-6-crf20`; derived seed `25494854976677863`. The archived dry-plan SHA is `422bd7e188c66c8afb4984433fc5724cffdcd2047921afb92ff93b1829c2fdd7`.


After all applicable gates and the explicit one-cell host allocation, use the same command with `--execute` appended. It selects the first unfinished cell automatically; do not pass a different source slot, session set or master seed to skip ahead.


### P910

```sh
ENCODINGDB_STATE_DIR=/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts/host-state \
  /mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/native-build-venv/bin/python /mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c/scripts/run-calibration-matrix.py --matrix /mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c/server/config/calibration/final1080p-corrected-timing.matrix-v1.json --cli /mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c/encodingdb-client-linux --client-source-sha b3ef24abb020bc6af5b5fe6b849ba3eae8314be2 --sessions 1,2 --seed 20260914 --output /mnt/NVME/docker/encodingdb-operations/20260920-canonical-matrix-b3ef24a --phase timing --max-cells 1 --max-duration-minutes 45 --cell-minutes 30 --max-storage-mb 16384 --cell-storage-mb 1024 --disk-reserve-mb 5120 --source-slot source-b --source-slot nvenc-host
```


First planned cell: `source-b/session-1/fit-screen-text-1080p24-final-libx264-slow-crf18`; derived seed `8396261971526397`. The archived dry-plan SHA is `e81bb4fa3645f7ff383e4ced0e60e89bc13692069919ff81d57dadaf6ea83fb7`.


After all applicable gates and the explicit one-cell host allocation, use the same command with `--execute` appended. It selects the first unfinished cell automatically; do not pass a different source slot, session set or master seed to skip ahead.


## Resume and bulk publication

Keep the same output root, state directory, complete slot selection, sessions, master seed, source pin and reviewed binary/runner/matrix hashes. The ledger binds those identities. A later invocation reuses completed cells and resumes partial owned journals; inspect nonzero exits instead of wrapping the runner in an automatic retry loop. If a task storage limit must grow, record the new finite allocation and preserve the original ledger and data. Do not use a new output root to replace a bad observed cell.

After the coordinator verifies all host timing is finished, publication uses the same host bindings with `--phase upload --all-host-timing-complete --base-url APPROVED_UPLOAD_BASE_URL --execute`. Keep `--max-cells 1` initially, explicit time/storage limits and the configured normal credentials/CA environment. `APPROVED_UPLOAD_BASE_URL` is an unresolved operational value, not a literal destination to run. The runner requires every selected cell/session's timing completion, preserves one upload target in its ledger, observes queued retry deadlines and refuses terminal rejections.

Publication retains originals and can stage an additional managed copy of each unique artifact. The b3 client counts aggregate queue bytes, so a nearly full 1 GiB cell may require a larger declared cell allowance as well as total-budget headroom before publication. The runner checks exact pending staging sizes, real disk reserve and metadata overhead; the client independently checks queue admission. Increase bounded capacity on the same retained identity if required. Never reclaim completed measurement bytes to force a green upload result.

The frozen matrix and selection do not imply that every row qualifies: stability, authoritative media/quality analysis, exact cohorts, review and independent-machine confidence remain separate. The no-submit phase produces measurement evidence only. Neither these dry files nor a phase-complete count activates calibration or PL.

## Verification scope

The unchanged runner and matrix bytes were compared with source b3. Both real local dry invocations exited successfully, produced exactly 392/448 selections and 1,960/2,240 maximum encodes, and preserved all native commands/derived seeds. `files.json` seals this packet. No application file, frozen matrix, threshold or source setting was modified. No canonical timing, build, host probe, remote contact, artifact import or publication occurred.
