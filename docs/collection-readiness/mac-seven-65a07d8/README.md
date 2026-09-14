# Historical Mac seven-clip execution — exploratory only

**Every observation here is ineligible for final calibration.** This preserves actual packaged CLI execution from source `65a07d843c26f331c77270188ae9e3732df13117`, before the corrected CPU sampler and its provenance markers. Neither campaign has `cpu_psutil_thread_window_v1` or `cpu_psutil_blocking_window_v1`. Original records, “valid” labels, counted flags, suspect warnings and unstable outcomes remain unchanged. Do not backfill corrected provenance or promote these observations after later fixes.

The recorded host was an Apple M4 Pro, 24 GiB RAM, Darwin 27.0.0. Both runs used the same persistent installation pseudonym and warmed canonical cache under a path containing `épreuve 客户端`. The [original receipt](evidence/receipt.json) preserves exact command arguments, seeds, UTC timestamps and exit codes; the [original harness](evidence/original-run.py) records runtime-override removal and the installation measurement lock. This is CLI evidence, not GUI acceptance or proof that all OS background activity was absent.

| Recorded outcome | libx264 fast, CRF 23 | H.264 VideoToolbox, default, VBR 6000 kbit/s |
|---|---:|---:|
| Campaign | `campaign-8cf5cad6d31bff9f` | `campaign-28e2def1d446eab1` |
| Seed | 20260914 | 20260915 |
| UTC start → finish | 05:12:46 → 05:19:34 | 05:19:34 → 05:24:48 |
| Whole invocation wall seconds | 408.746695 | 313.3049915 |
| Process exit | 0 | 0 |
| Actual attempt records | 27 | 21 |
| Warmup / measured | 7 / 20 | 7 / 14 |
| Originally counted for stability | 20 | 14 |
| Original overall valid / suspect | 23 / 4 | 7 / 14 |
| Original structural-valid records | 27 | 21 |
| Locally retained submission payloads | 20 | 14 |
| Submitted / queued / skipped / failed in client log | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Stable / unstable recipe groups | 4 / 3 | 7 / 0 |

All times are on 2026-09-14 UTC. Exit zero means these local campaigns completed; it does not establish calibration eligibility. Console “Completed Encodes” counts 20 and 14 measured records, excluding the seven actual warmup encodes in each campaign. Every command specified `--campaign full --no-submit`, 35 maximum attempts, 2048 MiB storage and a 20-minute measurement allowance. VideoToolbox's saved task label includes the unused default CRF 24; the executed command and native recipe use `-b:v 6000k`, not CRF.

Original stability, independently reconciled from the stored counted timing records as `(maximum − minimum) / mean`, uses the declared 3% threshold:

| Clip ID prefix | Software measured / spread / stable | VideoToolbox measured / spread / stable |
|---|---|---|
| athletic-action | 2 / 0.488486% / yes | 2 / 0.162828% / yes |
| natural-detail | 4 / 7.232373% / **no** | 2 / 0.905337% / yes |
| film-grain | 2 / 2.493084% / yes | 2 / 0.805244% / yes |
| dark-gradients | 2 / 2.228918% / yes | 2 / 1.711033% / yes |
| animation | 2 / 0.825188% / yes | 2 / 0.507749% / yes |
| screen-text | 4 / 3.670314% / **no** | 2 / 0.191318% / yes |
| talking-head | 4 / 3.956946% / **no** | 2 / 0.038304% / yes |

Software execution orders 21, 22, 25 and 26 retain CPU-suspect observations of 35.0%, 40.6%, 38.4% and 45.25%. The subsequently confirmed thread-baseline defect prevents trusted interpretation of these old CPU windows; this audit does not claim it explains every historical reading.

All 14 measured VideoToolbox records retain `gpu-environment-unobserved`: GPU load and temperature are null, GPU sample count is zero and `gpu_load_trustworthy` is false. Device selection was `videotoolbox:system`; driver version was unknown. These records predate the later AGX telemetry work. No AGX observations, device-specific GPU certification, or inferred idle GPU values are retroactively attached.

## Runtime and artifact receipts

The original execution receipt records packaged executable SHA-256 `f76ebaa3ca384394276c5bff28f2738d91fcbde79f7749f88fbd7eb4d3bc175b`. The two frozen-runtime receipts show distinct `_MEIVfZOO3` and `_MEItIFROI` extraction roots, the same runtime-lock fingerprint `a3929406d94ea18976b7ba56c5b6991d0d70cf27ec9b544c76c319ad2f0db659`, and matching sets of 100 dependency records. Manifests identify arm64 execution. Recorded helpers are FFmpeg/ffprobe 9.0:

- FFmpeg: `ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2`.
- ffprobe: `12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66`.

[Audit metadata](audit.json) preserves each attempt's exact timer endpoints, source hash, output hash/size, command, original disposition and full stored probe. All 48 artifact files existed with matching recorded byte sizes at audit time; process receipts matched their stored artifact hashes, commands, runtime dependency records and successful exit. Stored probes report complete decodable H.264 video: 192 frames for animation and 240 for each other clip, matching the frozen source manifest. Source hashes match that manifest. Fractional submitted timing values match monotonic endpoints; the older rounded `elapsedMs` diagnostic is not substituted for them.

## Preservation and limits

[Evidence inventory](evidence-inventory.json) identifies the original paths and hashes of the copied metadata/log files. Protocol-attempts files contain all 48 original journal records; those copies were compared against the separate attempt files before avoiding duplicate storage. Both tiny client-log hashes match the original execution receipt. The audit also reconciles all 34 retained submission references and group receipts against their attempts. No media binaries are committed.

This was a metadata/log-only audit during a backend performance interval: no media probes, full source/artifact/executable rehashing, test suite, build, or new collection. Binary hashes are historical recorded evidence, not freshly verified bytes. There was no adjacent release-manifest sidecar in the inspected `macos-65a07d8` package directory; the source pin comes from the execution receipt/harness, not an independently preserved build attestation. There are no server upload/acceptance or authoritative quality-analysis receipts for these `--no-submit` runs, and no proof of performance on other macOS versions. Final calibration requires fresh runs from the corrected, rebuilt client.
