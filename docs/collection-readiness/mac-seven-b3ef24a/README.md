# Packaged Mac seven-clip acceptance — b3ef24a

The actual packaged ARM64 candidate completed both predeclared seven-clip campaigns with exit 0. Fresh artifact and metadata checks passed for all **46 retained outputs and 10,656 decoded frames**. **Two software timing groups remain unstable; six VideoToolbox measured attempts remain GPU-suspect.** Completion and integrity checks do not imply universal timing/environment eligibility, server acceptance, or validated PL.

| Case | Settings | Warmups | Measured | Timing-stable groups | Measured validity |
|---|---|---:|---:|---:|---|
| Software | libx264 / fast / CRF 23 | 7 | 18 | 5/7 | 18 valid |
| VideoToolbox | h264_videotoolbox / default / native VBR 6000 kbps | 7 | 14 | 7/7 | 8 valid, 6 suspect |

All seven warmups in each case are recorded valid. There are no failed or skipped attempts. Software ran from 04:04:01 to 04:09:53 UTC on 20 September 2026 (351.759 seconds); VideoToolbox ran from 04:09:53 to 04:14:59 UTC (305.606 seconds). These wall durations include collection preparation and are not encoder-speed measurements.

## Frozen choices and preserved outcomes

The original plan and runner are copied byte-for-byte. Predeclared seeds are **4053523937118112** for software and **405869481192659** for VideoToolbox, independently verified as the first 13 hexadecimal digits of SHA-256(`sourceCommit + :mac-native-acceptance: + phase + :1`). The plan remains the original pre-execution document; the separate completed receipt records actual execution. The runner held the shared existing physical-host lock, checked AC power and more than 7 GiB free space before each case, removed external helper/loader and stability/adaptive overrides, and used `--no-submit` throughout.

Software timing spreads use `(maximum − minimum) / mean` across **every** counted repetition:

| Clip | Counted repetitions | Relative spread | Recorded outcome |
|---|---:|---:|---|
| athletic-action | 2 | 2.780847% | Stable |
| natural-detail | 2 | 0.171870% | Stable |
| film-grain | 2 | 0.036278% | Stable |
| dark-gradients | 2 | 2.632020% | Stable |
| animation | 4 | **3.001136%** | **Unstable** |
| screen-text | 2 | 0.534396% | Stable |
| talking-head | 4 | **7.989572%** | **Unstable** |

The animation result exceeds the unchanged 3% threshold even though rounding it to two decimal places would hide the difference. Both unstable groups retain all four counted attempts, including the two permitted adaptive repetitions. No attempt was dropped or repeated outside that protocol to obtain a favorable result.

All seven VT timing spreads are below 1%. These six measured attempts retain `background-gpu-suspect`, severity `suspect`, threshold **35.0%**, and message “Background GPU load exceeded the suspect threshold.”:

| Attempt | Clip / repetition | Observed background GPU |
|---|---|---:|
| 000008 | film-grain / 1 | 44.0% |
| 000010 | screen-text / 1 | 37.0% |
| 000013 | dark-gradients / 1 | 38.0% |
| 000014 | animation / 1 | 46.5% |
| 000015 | animation / 2 | 46.5% |
| 000016 | dark-gradients / 2 | 53.5% |

The underlying `overallValidity`, environment snapshots, protocol reports, and submission/group sidecars are preserved unchanged. The earlier [939823e packet](../mac-seven-939823e/README.md) is separate historical evidence; its more favorable timing results do not replace this candidate's outcomes.

## Artifact, timing, and telemetry audit

Fresh locked ffprobe runs independently decoded/counted every output. All animation outputs have 192 frames; other outputs have 240. Each has one H.264 video stream, 1920×1080 yuv420p, 24/1 frame rates, BT.709 metadata, and the expected 8/10-second duration. Every actual media SHA matches its original attempt/process metadata. Monotonic start/end arithmetic matches elapsed time and FPS. Final measurement-group receipts bind every counted repetition and its exact elapsed time, including all adaptive attempts.

All **32 measured attempts** carry fresh background CPU provenance `cpu_psutil_thread_window_v1`. Observed background CPU spans 4.20–22.60% for software and 8.65–21.55% for VT. Every measured pre-run power source is AC. Warmups have no measured pre-run snapshot and are not presented as equivalent environment observations.

Forty-three attempts have fresh `ffmpeg_psutil_process_window_v1` process CPU observations. Software screen-text warmup and repetitions 1/2 complete in 0.458085, 0.482804, and 0.485391 seconds respectively; all three preserve zero samples, null average/max CPU, and `ffmpeg_unavailable`. These are unavailable observations, not observed 0% usage. Across sampled attempts, process CPU averages span 1101.0–1206.5% for software and 139.7–908.1% for VT; one fully busy CPU remains 100%.

The VT snapshots use `gpu_ioreg_agx_system_utilization_v1` for the system-selected Apple M4 Pro. That is system GPU activity, not media-engine occupancy, GPU temperature, or per-process GPU use. The selected device is `videotoolbox:system`; driver version remains explicitly unknown. Every executed VT command requests `-c:v h264_videotoolbox -b:v 6000k`, with no CRF/QP/CQ substitution. The legacy `24` filename/task field is not the executed rate-control setting.

## Exact candidate and support limits

- Source: `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2`.
- Executable SHA-256: `443e293e82f0f042b2017f55d12f1d73c7d5b6944cb43d6c9d70281beef6d70c`.
- FFmpeg SHA-256: `ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2`.
- ffprobe SHA-256: `12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66`.
- Suite fingerprint: `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e`.
- Verified source-pack SHA-256: `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150`.
- Model `vmaf-v1-sdr-1080p`: SHA-256 `e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e`, freshly extracted and hashed from the executable archive. Model presence is not a claim that quality analysis ran.

Actual execution was on Apple M4 Pro / ARM64, macOS 27.0 build 26A428. Both campaigns use the existing physical-source pseudonym recorded in their manifests; they are not independent machines. Embedded-runtime receipts resolve to packaged `_MEI` directories; each process receipt matches the helper/dependency identities. The complete runtime's minimum OS is **27.0**, set by the pcre2 and harfbuzz headers. This does not certify macOS 26.5, Intel Macs, or another OS build.

The executable has an ad hoc signature and passes local strict codesign verification. Its release sidecar has no supplied signing evidence; there is no Developer ID/notarization claim. The post-run scoped process scan reports no survivors. This evidence exercises the packaged CLI, not a Mac GUI.

## Immutable handoff and packet

Both immutable replay ledgers were captured **before any upload and before the fresh media probes**:

| Ledger | Immutable files | SHA-256 |
|---|---:|---|
| `replay-ledgers/software-before-upload.json` | 52 | `521816caa9b19ecc49635316cdb3099c89951c0fd6aa6c89a6c78a86e353d673` |
| `replay-ledgers/videotoolbox-before-upload.json` | 44 | `fd447d9e4800c4bdac509a3fca8080f45102e414155a8af52ed5124ec2fe894f` |

They cover manifests, completion markers, every attempt record, and all media hashes. Later upload-only replay must compare against these ledgers; this packet itself makes no upload/server claim.

`audit-summary.json` contains every attempt's unchanged validity, observed telemetry, exact timing spreads, source hashes, and runtime/signature observations. `fresh-probes/` retains the exact command/output for all 46 ffprobe checks. `original/` contains 178 byte-preserving metadata/log/runtime/plan copies, bound by `original-file-checksums.json`. Original media is retained in its task-owned collection directories and is not duplicated here.

The reproducible audit requires retained local media and the existing package-build Python environment (PyInstaller is used only to read the archive):

```sh
/Users/ofhd/Developer/Encoding_Database/.build/release-20260919/macos-b3ef24a/build/venv/bin/python docs/collection-readiness/mac-seven-b3ef24a/audit.py
```

The packet preserves the actual results without re-encoding, editing raw records, changing thresholds, fabricating human review, or claiming calibration, authoritative metrics, validated PL, or production readiness.
