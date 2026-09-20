# Frozen hardware extension for source 939823e

**Prepared, not executed.** This packet freezes the existing 28-cell extension: 14 Mac VideoToolbox/default cells and 14 P910 NVENC/p4 cells, all seven registered 30-second sources at native VBR 4000 and 8000 kbps. `execution.json` copies the original `timing-hardware-extension-v1.json` cells exactly, preserving their original global order and each host's ordered subsequence, seeds, reference paths and source registrations. The base plan is unchanged. It is not a claim that two independent hosts must execute simultaneously or share a wall-clock order.

Source commit: `939823ead2c052572f9deb5c9f91c85435d5661d`.

Execution hash: `c59993cae26188c0d7519aa9d9371f0ecb0aa7e8d1ec4e2de02163d3ef7fe89e`.

Deterministic source archive: `/Users/ofhd/Developer/Encoding_Database/.build/release-20260919/hardware-holdouts/source-939823e.tar.gz`, SHA-256 `36ec9835272b0d2cfc7ea2d59ad7607d2c6e5bf79cb7a0cca1ca505c192a2449`. It was created using `git archive --format=tar <commit> | gzip -n`. Before P910 timing, stage these exact bytes at `/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts/source/hardware-939823e.tar.gz`; the driver refuses a missing or mismatched archive.

## Runtime binding

| Host | Filtered runtime fingerprint | Reviewed lock SHA-256 |
| --- | --- | --- |
| Mac | `a3929406d94ea18976b7ba56c5b6991d0d70cf27ec9b544c76c319ad2f0db659` | `5db0f9c3d5178f2bad9a84cced0141df44b82532314c7e5e30f401f47e7262b0` |
| P910 | `494132ca850dadf47226fbb267bcde9d454b37b4a68892d9759d48db3a89fe7b` | `fe3ef337dbaffb3d129d05ce1472461a4dfac5349206f13c412cfc86482b8e42` |

The source's unfiltered lock fingerprint is `09d0a493de921e3eb88c245c3e0fbe8312eac87a7032f110d45a3a4a53a53890`. These are distinct cohort identities. The operator explicitly sets `ENCODINGDB_RUNTIME_LOCK_PATH` to each reviewed package-filtered lock; it never assumes equivalence with the unfiltered source lock. The Mac's two helpers and 100 dependency files were hashed during preparation. P910 helper/filtered-lock pins come from the existing source939 package archive audit, and are rechecked against live files only after a timing allocation is granted. No P910 contact or workload occurred during this preparation.

The pinned VMAF model is `vmaf-v1-sdr-1080p`, SHA-256 `e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e`. This is the model identity for subsequent authoritative analysis; the timing driver does not run quality metrics.

## Storage-only preparation adjustment

The original one-source-at-a-time Mac policy addressed approximately 8 GiB of free space. The parent staged all seven references before any hardware timing while P910 coordination was paused. `mac-reference-staging.json` records every SHA and byte count: 5,499,942,827 bytes in total. The preparation check found 12,315,164,672 free bytes, above the unchanged 5 GiB reserve. This adjusts only when references are copied. It does not change source choices, scene ranges, recipes, seeds, order, measurement criteria, or retained failed observations. No transfer or source preparation may run during timing.

Before each cell, the driver requires at least 5 GiB plus that cell's 2 GiB maximum journal allocation to remain free. P910 retains the original 20 GiB task cap. The Mac output cap is the sum of the original fourteen 2 GiB cell allocations. It never removes previous observations to make space.

## Ready-to-run handoff

1. Complete the existing capacity/native acceptance phases and explicitly allocate the target host. Mac must be on AC power with a valid actual environment snapshot; battery or high GPU activity stops the operator before encoding. Both hosts retain their original physical-source identity and shared `measurement.lock`.
2. Stage this packet, the unchanged base plan, and the exact source archive at the paths in `execution.json`. Preserve the pinned checkout and helper paths. The operator is separate from the source939 application checkout, so staging it does not dirty that source.
3. Inspect the command-only dry run. It performs no runtime probes, encoding, remote calls or writes:

```sh
python3 run.py --host Mac --base-plan ../timing-hardware-extension-v1.json
python3 run.py --host P910 --base-plan ../timing-hardware-extension-v1.json
```

4. After host handoff, the coordinating parent writes a current allocation JSON containing `host`, the exact `executionHash`, exact `sourceCommit`, an ISO-8601 `expiresAt` with timezone, and true values for `exclusiveTimingGranted`, `nativeAcceptanceComplete`, and `noBuildAnalysisUploadOrSourcePreparation`. This is an operator coordination receipt, not an authentication credential. No allocation is fabricated in this packet. Then run:

```sh
python3 run.py --host Mac --base-plan ../timing-hardware-extension-v1.json --execute --allocation /absolute/path/to/current-allocation.json
```

Use `P910` for that host. `run.py` holds the host lock across identity preflight, environment sampling, cell timing and receipt verification. It passes the same locked descriptor into each timing child, so operator parent death does not release host exclusivity while that child survives. The runner starts in its own session. On operator Ctrl+C, the operator forwards SIGINT once and waits for the runner’s graceful owned-media cleanup while retaining its host lock; repeated Ctrl+C is ignored only during that cleanup wait. It never force-kills the runner via `subprocess.run` interruption behavior. The original client runner owns the warmup, two measured attempts, up to two adaptive attempts, 3% stability threshold, per-cell duration budget, journal checkpoints and native process ownership. No upload, metric analysis or source preparation is performed.

Completed stable **and unstable** cell receipts are reused only if their receipt and retained artifact hashes still match. The driver preserves terminal failures and refuses automatic replacement attempts. Interrupted cells require explicit `--resume-interrupted`; verify their previous owned processes are gone before using it, and preserve the same allocation/plan/commands. A caught operator interruption is recorded explicitly; unexplained terminal failures are not reclassified as interruptions. Runner exit 11 is a resumable budget pause only when its exact `PAUSED_MEASUREMENT_BUDGET` receipt matches the owned journal, campaign, seed, duration and completed-attempt count. The operator verifies and pins the manifest, recipe, completed attempt bytes and retained artifact hashes before allowing explicit resume. A changed or missing saved observation is refused. Actual `FAILED` cells remain terminal, and completed unstable cells remain reusable without execution. The original runner then resumes its durable journal rather than replacing completed attempts. Creating the host's configured `PAUSE_HARDWARE_TIMING` file requests a stop at the next cell boundary. The operator does not delete that file.

Raw output, environment preflight and per-cell operator records are written beneath the frozen host output root. `exitCode=4` denotes a completed unstable cell, retained and ineligible; it is not retried to obtain a favorable result. A phase completion receipt establishes execution completion only, not quality or PL acceptance.

## Verification and remaining gates

`guard-tests.txt` records 19 passing tests for exact allocation/source/host binding, expiry, immutable completed receipts, terminal failure preservation, explicit interrupted resume, seal/helper tampering, and unchanged native command/seed/order construction. Recovery tests also cover validated budget pauses, changed attempts/recipes/counts, explicit observed interruptions and a real synthetic parent-death/child-lock-inheritance regression. These process tests launch only Python waiting fixtures, with no encoder or host probe. The parent-only SIGINT regression includes a detached media grandchild and repeated SIGINT during blocked cleanup: the host lock stays unavailable until the media exits, and the original signal handler is restored. Normal child exit 4 and the original parent-SIGKILL/surviving-child guard remain covered. `mac-dry-run.json` and `p910-dry-run.json` are retained historical dry receipts from the prior operator seal and contain all 28 unchanged commands. `operator-revision-proof.json` binds the current operator/execution hashes and verifies every command against those receipts; only the operator implementation and its seal changed. `preparation.json` remains the historical byte/staging receipt under its prior execution hash; it records local byte checks and remaining live P910 validation, not a current allocation. Neither dry run launched an encode or measured environment conditions.

Before the first encode, live host allocation, AC/environment readiness, exact runtime/source/archive/model bytes and reserve checks must pass. Human quality judgments, authoritative metrics, held-out ranking, independent-machine confidence and any calibration/context activation remain subsequent gates. The corrected 42-cell software experiment and its five unstable groups are untouched.
