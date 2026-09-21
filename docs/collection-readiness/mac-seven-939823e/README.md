# Packaged Mac seven-clip acceptance — source 939823e

The actual packaged ARM64 client completed both seven-clip campaigns with exit 0: libx264 / fast / CRF 23, and h264_videotoolbox / default / native VBR 6000 kbps. Each retained seven warmups plus fourteen measured attempts, with no failed or skipped attempts. All fourteen timing groups met the unchanged 3% relative-spread threshold. **Five VideoToolbox measured attempts remain suspect.** Timing stability does not remove environment flags or establish server/PL eligibility.

| Case | Warmups | Measured | Timing-stable groups | Validity across all attempts | Measured validity |
|---|---:|---:|---:|---|---|
| Software | 7 | 14 | 7/7 | 21 valid | 14 valid |
| VideoToolbox | 7 | 14 | 7/7 | 16 valid, 5 suspect | 9 valid, 5 suspect |

Fresh read-only locked-ffprobe decoding/counting verified **42/42 retained artifacts**, 9,792 decoded frames total. Every animation artifact has 192 frames; all others have 240. Every artifact has exactly one H.264 video stream, 1920×1080 yuv420p, 24/1 frame rates, BT.709 color metadata, expected 8/10-second duration, and its recorded SHA-256. Original monotonic start/end arithmetic matches retained elapsed time, FPS, process receipts, and final two-member measurement-group receipts. No media was regenerated, copied into this packet, or modified.

## Conditions preserved

All 28 measured attempts carry the fresh background CPU marker `cpu_psutil_thread_window_v1`; observed pre-run CPU spans 1.35–8.25% for software and 0.35–16.20% for VideoToolbox. Warmups have no pre-run environment snapshot and are not presented as measured environment observations.

Thirty-nine attempts carry `ffmpeg_psutil_process_window_v1` with actual nonzero process CPU samples. All three software screen-text attempts finish in approximately 0.444–0.450 seconds and have **zero samples, null CPU averages/maxima, and `ffmpeg_unavailable`**. This is unavailable telemetry, not an observed 0% load. Observed process CPU averages span 1188.40–1284.25% for sampled software attempts and 141.60–906.90% for VideoToolbox. The existing units are percent of one CPU, so multithreaded values above 100% are expected.

All VideoToolbox measured snapshots use `gpu_ioreg_agx_system_utilization_v1`, attributable to the system-selected Apple M4 Pro adapter. This measures system GPU activity, not media-engine occupancy, temperature, or process-specific GPU activity. The manifest identifies `videotoolbox:system`, with driver version explicitly unknown. Every executed VT command requests `-c:v h264_videotoolbox -b:v 6000k` without CRF/QP/CQ substitution. The legacy `24` filename/task field is not the executed rate-control setting.

These five original suspect records are retained verbatim:

| VT attempt | Clip / repetition | Background GPU | Other condition |
|---|---|---:|---|
| 000008 | athletic-action / 1 | 39.5% | — |
| 000017 | film-grain / 2 | 40.0% | — |
| 000019 | dark-gradients / 2 | 41.0% | Battery |
| 000020 | talking-head / 2 | 42.5% | Battery |
| 000021 | athletic-action / 2 | 42.5% | Battery |

All five have `background-gpu-suspect`, severity `suspect`, threshold 35.0. The last three additionally have `power-source-battery`, actual `battery`, threshold `ac`, and message “Measured repetition ran off AC power.” Both their pre-run and encode power-source readings are `battery`; their battery percentage starts and ends at 95.0. No flag was removed, normalized, or overridden.

## Identity and support limits

- Build source: `939823ead2c052572f9deb5c9f91c85435d5661d`.
- Packaged executable SHA-256: `ad01bfd36ad84e0e0d9f45730bd195c1b940a240493d093f6a875faa97a6f2c0`.
- Actual FFmpeg SHA-256: `ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2`.
- Actual/fresh-audit ffprobe SHA-256: `12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66`.
- Suite fingerprint: `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e`.
- Verified suite-pack SHA-256: `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150`.
- Bundled model `vmaf-v1-sdr-1080p`: SHA-256 `e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e`, independently extracted and hashed from the executable archive. Presence does not claim any quality analysis was run.

Actual execution was on Apple M4 Pro, ARM64, macOS 27.0 build 26A428. Both campaigns record the same persistent physical-source pseudonym; they do not create two independent machines. Frozen-runtime receipts resolve to the packaged `_MEI` extraction directory; process receipts match the locked helper and dependency hashes. The original runner explicitly removed external helper/runtime/loader overrides.

The **complete runtime requires macOS 27.0** according to its Mach-O headers (`libpcre2-8.0.dylib` and `libharfbuzz.0.dylib` set the floor). Earlier helper-only 26.5 claims do not apply. This evidence covers the observed macOS 27.0 beta build; it does not certify older macOS versions or other architectures.

The executable has an ad hoc signature and passes local `codesign --verify --strict`. The release signing sidecar says unsigned because no signing evidence was supplied; there is no Developer ID signature or notarization claim.

## Packet and reproduction

`audit-summary.json` retains all per-attempt flags, timing spreads, telemetry values, source hashes, and fresh host/signature observations. `fresh-probes/` contains the exact locked-ffprobe command and output for every media artifact. `original/` contains byte-preserving copies of the original receipt, runner, logs, runtime proof, package sidecars, campaign metadata, process/environment/submission sidecars, and protocol ledgers. `original-file-checksums.json` binds each copy to its original path, size, and SHA; the existing before-upload ledgers also match all 88 listed files across the two campaigns.

`audit.py` reproduces the read-only audit against retained local media using the existing package-build Python environment (which supplies PyInstaller for archive extraction):

```sh
/Users/ofhd/Developer/Encoding_Database/.build/release-20260919/macos-939823e/build/venv/bin/python docs/collection-readiness/mac-seven-939823e/audit.py
```

The campaigns ran with `--no-submit`. This packet proves native execution, retained artifacts, honest diagnostics, and timing-group receipts. It does not claim upload recovery, authoritative server analysis, calibration, human review, validated PL, or production readiness.
