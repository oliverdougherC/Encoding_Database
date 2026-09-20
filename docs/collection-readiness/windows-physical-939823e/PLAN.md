# Physical Windows acceptance plan

Status: inventory complete; native execution is pending the exact reviewed CI artifact. This document is a plan, not an acceptance claim.

The user authorized `DESKTOP-4ELVRAT` and installed the Mac SSH public key for `ofhd`. Read-only SSH inventory on 2026-09-19 found Windows 11 Pro build 26200 x64, Ryzen 9 7950X (16 cores / 32 logical processors), approximately 63 GiB RAM, an RTX 5090 at NVIDIA index 0 with driver 616.92 and 32,607 MiB VRAM, plus AMD integrated graphics. Existing Python is 3.12.10. The user has active console session 1. No EncodingDB or FFmpeg process was observed. No user application was stopped.

The create-only remote directory is `C:\Users\ofhd\EncodingDB-validation-20260919-939823e`; its inventory receipt is `inventory.json`. All native runs must use its one persistent `host-state/physical-source-id`. The operator lock serializes this validation allocation; client queue locks remain independent. Background load can invalidate observations and is never corrected after the fact.

## Artifact provenance

Reviewed branch source is `939823ead2c052572f9deb5c9f91c85435d5661d`. GitHub CI may build a PR merge commit. Record the actual manifest revision, verify merge parents and tree equality against the reviewed branch, and do not relabel the binary. Download the candidate artifact directly on Windows using a short-lived redirect without logging/persisting GitHub credentials. Verify the GitHub archive digest and independently recorded file pins before execution.

The operator requires a pins JSON containing `actualBuildRevision`, `suiteFingerprint` and `files` (relative path to SHA-256 mapping). At minimum pin the console EXE, its release manifest, its runtime lock and the canonical suite pack. Include GitHub run/artifact IDs, archive digest, branch revision and verified tree identity as additional receipt fields. The expected suite fingerprint is `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e`; canonical pack SHA-256 is `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150`.

## Execution order and acceptance

1. Verify binary/sidecar/pack/model/runtime pins and native architecture. Run embedded-only help/provenance checks without helper overrides.
2. Run seven clips with x264 fast CRF 23, then NVENC p4 CQ 24, then NVENC p4 VBR 6000 kbps. These three campaigns are platform acceptance, not calibration fitting data. Retain every warmup, adaptive attempt, stable/unstable group and suspect observation. Require actual `-gpu 0`, matching observed RTX 5090/NVML identity and native rate-control arguments for hardware claims.
3. Audit exact retained bytes, frame coverage, timing version, CPU window marker, runtime/model/suite identities, group receipts, device binding and native process architecture. `EXECUTED_PENDING_INDEPENDENT_REVIEW` in the operator receipt is deliberately not PASS.
4. Exercise bounded corruption, offline collection/upload replay, interruption/resume and API backpressure against an explicitly coordinated isolated candidate. Preserve prior immutable journals/artifacts. No production upload or fitting-data import is authorized by this plan.
5. Run existing GUI acceptance only in the user's actual interactive console session through a temporary owned scheduled task, if supported. An SSH service session cannot certify GUI behavior. Preserve screenshot evidence for Codex inspection, record physical scope separately from the hosted-CI harness's hardcoded scope, and remove only the owned task after completion. Coordinate any harness edits with the Windows CI owner.

`scripts/windows-physical-acceptance.py` provides plan-only default and explicit `--execute`, create-only output paths including non-ASCII characters, a single persistent installation state, reviewed pin checks, embedded-helper receipt checks, retained artifact hashing, bounded local-only campaigns and owned-process timeout cleanup. Acquisition plus measurement is bounded at 40 minutes per campaign; the client measurement budget is 20 minutes. A deadline or forced cleanup fails the phase; failed phases are never silently retried or overwritten.

Operator verification after the Mac quiet window: seven focused fixture tests passed on the actual Windows host (including real `msvcrt` exclusion/release); six passed on macOS with the Windows lock test skipped. The tests cover independent pinned-byte rejection, source mismatch/missing pins, path escape, non-mutating dry plans, preservation of suspect records, retained-artifact tampering, external helper rejection and incomplete campaigns. All three actual Windows CLI dry plans also passed and created no campaign/output directory. Logs are retained beside this plan. Fixture checks are not native-client acceptance evidence.

Remaining verification: exact CI binary availability, all native phases, physical GUI screenshots, and independent review. No physical Windows native acceptance has yet been claimed.

## Interactive session plumbing receipt

A bounded identity-only probe passed at `2026-09-20T02:01:01Z`. The temporary task `EncodingDB-Interactive-Probe-20260920T020058Z-1e777430` used the existing `DESKTOP-4ELVRAT\ofhd` interactive token with **Limited** run level. Its own process reported session **1**, equal to the active console session, `userInteractive=true`, and `administratorRole=false`; task result was **0**. The exact owned task was removed, and its absence was verified. Creation, result and cleanup are recorded in `interactive-session-receipt.json`, with the original process result in `interactive-session-result.json`.

This establishes a non-elevated path for later GUI acceptance. It does not certify the GUI. The probe captured no screenshots, enumerated no windows, interacted with no user application, ran no benchmark, installed nothing, changed no global policy and contacted no P910 service. The reusable bounded probe is `scripts/windows-interactive-session-probe.ps1`; its script-file transport avoids the Windows command-line length limit encountered by the initial encoded-command invocation before any probe was created.

## Separate physical native candidate

Hosted CI lost runner communication and published no Windows binary. The separately labeled physical candidate was built from exact clean source `939823ead2c052572f9deb5c9f91c85435d5661d`, tree `532898f45d3e71fd0138d4911889dd7ff1a2ccdc`, using existing Python **3.12.10** and only project-declared dependencies in local venvs. It is not the unavailable CI binary.

The unmodified reviewed PowerShell build stopped when Windows PowerShell 5.1 converted PyInstaller's first normal stderr INFO message into a terminating error. No child remained, and tracked source stayed clean. The retained PS5 receipt records that preparation failure. A separate Python operator then executed the reviewed script's exact PyInstaller/finalizer arguments with direct subprocess stream redirection, preserved all resources/windowed flags, recorded command exits, and held the physical allocation lock. No source edit, new dependency or global install was needed.

Both binaries are native PE x86_64 and unsigned. Independent rehashing and reviewed source/tree/model/pack checks produced `build/physical-candidate-pins.json`:

- Console SHA-256: `66538edcf81cd04216bac51e7bf9051e8b862cde5629e6ad56cfeb146e0aa0fc`.
- GUI SHA-256: `0a955f1ea649833f443e482e02b369a4be427738c4a694842ae1d8288383f446`.

The console's actual embedded-only help and no-submit smoke exited 0, with no forced cleanup or surviving owned child. No-submit smoke took 104.469 seconds, including 86.485 seconds preparation. The `_MEI` receipt verifies the reviewed embedded helper hashes. The GUI sidecar explicitly marks smoke as not run; interactive GUI acceptance remains pending. Detailed build, model/runtime/suite identities and smoke receipts are in `build/`. The three authorized seven-clip acceptance campaigns follow independently; no fitting-data or release-readiness claim follows from the build smoke.

## Physical seven-clip acceptance and NVENC blocker

The independently pinned console ran all seven clips with x264 fast CRF 23 and exited **0** in **359.75 seconds**. Campaign `campaign-c51ac555622c3656` retained seven warmups and fourteen measured attempts; all 21 records are VALID. All seven measured pairs meet the unchanged 3% stability threshold (maximum observed relative spread **1.953%**). The operator rehashed every retained artifact; the independent journal audit verified **4,896 frames**, native timer arithmetic, requested/effective recipe, and complete group receipts. Twelve measured environment snapshots use `cpu_psutil_thread_window_v1`; two use the valid `cpu_psutil_blocking_window_v1` fallback. Observed background CPU was 0–7.7%. Original records, including missing telemetry, are preserved. `acceptance/audit-x264.py` reproduces the audit from the retained export. This is platform execution/retention proof, not fitting data or authoritative quality analysis.

The shared physical installation identifier is `installation-9e7cd0a8c6158d19d179f0acf79249c6c790b988b8a48f6563952c1c00acca29`. No submissions were made.

NVENC CQ 24 stopped before any campaign/measurement with client exit **4**. Source939's 128×128 usability probe fails on the RTX 5090 with `Frame Dimension less than the minimum supported value`. Repeating that exact native probe with only the dimensions changed to 1920×1080 succeeds; an additional explicit device0/p4/CQ24 diagnostic also succeeds. All argv/stderr/results are retained in `acceptance/nvenc-probe-diagnostic.json` and `acceptance/size-only-receipt.json`. These synthetic eight-frame probes establish the preflight false negative, not performance or calibration evidence. The VBR campaign was not blindly retried through the same failing gate. No gate was bypassed or source939 package changed. A newly identified candidate with the reviewed narrow fix is required for remaining hardware acceptance.

At the idle boundary after x264, Windows PowerShell's parser accepted the 23-line pre-GUI resource-snapshot block from workflow commit `bde6d4d` with zero syntax errors. The block was not executed; its parse receipt is retained separately. This does not certify hosted CI.
