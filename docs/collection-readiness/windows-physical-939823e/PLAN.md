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
