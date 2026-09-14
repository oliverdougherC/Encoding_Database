# Final release handoff — 1.3.0-rc.1

**Verdict: BLOCKED.** The corrected collection implementation and substantial
isolated verification are available. Final native campaigns, reviewed calibration,
and production promotion remain incomplete. Neither READY FOR COLLECTION nor
READY WITH VALIDATED PL is claimed. This handoff supersedes the historical beta-only
stopping point; completed source acquisition and freeze are not reopened.

## Candidate and published baseline

This snapshot describes candidate source `90f71135b02ef2a3c90b6aef55403b8ef3281432`
(including cleanup `4348ca8f1fc0e5a8e1bde2dacc3d01c463ba4b43`). It is a development
candidate, not the final approved build/deployment SHA. Record any later integrated
SHA and rerun affected checks before promotion.

| Identity | Current state |
| --- | --- |
| Candidate | `1.3.0-rc.1`, dated 2026-09-14; unpublished |
| Candidate measurement | `client/0.3.0`, protocol `7.1`, `ffmpeg-process-v1` |
| Public download | [1.2.0](https://github.com/oliverdougherC/Encoding_Database/releases/tag/1.2.0), client/0.2.0, historical protocol 7.0 |
| Last verified production code | `b0f0bc7d12cb127c86a7c76979eb361398e293dd` |
| Suite | Frozen seven 1920×1080, 24 fps SDR BT.709 clips; animation 192 frames, others 240 |
| Suite fingerprint | `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e` |
| Pack SHA256 | `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150` |
| Model / PL formula | `vmaf-v1-sdr-1080p` / `7.0`; public calibration inactive |

The [production timing inventory](operations/evidence/production-timing-inventory-before-migration-20260914.json)
preserves four original protocol-7.0 SUSPECT runs. Their raw timings and artifacts
remain intact; they are not silently relabeled as corrected measurements. There is
no accepted corrected-protocol production epoch in this snapshot.

## Executed evidence and its limits

- **Implementation:** [integrated 4348ca8 receipts](collection-readiness/integrated-4348ca8/receipt.json)
  record 219 server tests (zero skips), 217 client tests and 56 frontend tests,
  plus frontend lint/typecheck/build. These certify the recorded source snapshot;
  later candidate changes require affected checks again. Earlier lane transcripts
  retain their own counts and provenance.
  [Backend evidence](collection-readiness/backend-20260914/README.md),
  [scoring/review regressions](collection-readiness/scoring-evidence-20260914.md),
  [corpus evidence](collection-readiness/corpus-20260914/README.md), and
  [frontend tests/screenshots](../frontend/evidence/collection-ui/README.md)
  show the scope already exercised. Tests are not hardware or perceptual approval.
- **Native Mac:** local package/model smoke and native arm64 helpers are available.
  The full helper bundle requires macOS 26.5+, is ad-hoc signed, and is not Developer
  ID signed/notarized. [Runtime and model receipt](NATIVE_RUNTIME_20260914.md).
  Final native CI and real contribution/recovery acceptance remain required.
- **Linux/Windows:** final native CI and exact downloadable-client certification
  remain pending. [P910 preparation](native-linux/20260914-discovery/README.md)
  verifies an x86_64 runtime with x264/x265/SVT-AV1 and VMAF 3.2 plus the actual
  pinned-model execution; GTX 1070 discovery does not certify NVENC native RC.
  Intel macOS, QSV and AMF are not established by these receipts.
- **Serving:** [601-second load](operations/evidence/sustained-http-summary-20260914.json)
  used 25 simulated users and completed 124,737 requests without errors.
  [Reconciliation](operations/evidence/metadata-arrivals-reconciliation-20260914.json)
  ended at 100,622 runs/artifacts/analyses/public members, with no dirty groups.
  These are synthetic metadata in isolated staging. The tested router lacked the
  health route (`healthAllOk=false`); this is not 25 concurrent uploads, encoder
  throughput, full queue drain, or final production TLS/topology certification.
- **Storage/recovery:** [full-size P910 trial](operations/evidence/p910-backup-scale/receipt.json)
  restored 10 GiB of retained synthetic objects plus a 10 GiB staging mirror:
  backup 336.35 s, restore 372.94 s, writer quiescence 73 s. Initial cleanup failure
  and the corrected rerun are both preserved.
  [Actual unattended cron proof](operations/evidence/p910-unattended-cron/verification.json)
  has cron ancestry with no SSH ancestor, successful backup/restore, healthy
  unchanged candidate containers, and preservation of unrelated cron entries.
  Its candidate corpus was empty; it proves unattended orchestration, not retained
  production acceptance. Production backup installation/off-host retention and
  authorized alert delivery remain separate gates.
- **Sources/calibration:** acquisition, provenance, frozen public-suite distribution
  and [seven longer reference preparations](collection-readiness/holdouts/source-readiness.json)
  are complete. The fresh 42-cell longer-scene run is underway; no completed
  measurement or human review is inferred. The canonical plan contains 252 recipe/
  workload cells expanded to **840 host cell/sessions**, still unexecuted as a
  complete matrix. [Matrix runbook](collection-readiness/matrix-runner.md) and
  [holdout/combined-evidence workflow](collection-readiness/holdouts/README.md).

All capacity, recovery and rehearsal fixtures remain outside production and
calibration evidence. Each linked receipt describes its actual executing source;
later candidate changes do not retroactively change that provenance.

## Remaining release gates

1. **Freeze the integrated candidate.** Complete review, full release-preflight,
   migrations, server/client/frontend checks, native builds and clean deployment
   against the exact commit. Resolve failures/skips explicitly. Preserve current
   main and the XPSNR frame-rate repair; reconcile beta only through protected,
   reviewed Git operations.
2. **Certify declared native support.** From exact candidate downloads and clean
   caches, execute the bounded seven-clip artifact campaign, native software and
   claimed hardware RC/device paths, cancellation/resume, offline/backpressure,
   non-ASCII paths, corrupt packs and obsolete-client rejection. Record executable,
   helper/model/lock hashes, architecture/minimum OS, signing, IDs and actual
   locally-complete/queued/uploaded/SUSPECT/accepted outcomes. Remove unsupported
   claims instead of treating encoder discovery or `--help` as certification.
3. **Finish calibration and review.** Execute the predeclared canonical matrix and
   longer disjoint holdouts, retain original suspect evidence, and obtain genuine
   knowledgeable judgments for Balanced, Quality, Storage and Realtime plus family
   top-result checks. Verify exact live evidence and fitted folds, prediction/rank
   results, constants, scoring behavior hash and evidence policy. The old 540p Apple
   pilot cannot calibrate this 1080p release. [Calibration contract](V7_CALIBRATION_EVIDENCE.md).
4. **Make production promotion concrete.** Present exact reviewed artifacts,
   supported matrix, migrations, capacity limits, backups and rollback to the
   authorized production approver. Existing authorization governs subsequent
   actions; this document grants none. Do all independent preparation first.
   Keep the current data volumes and protect existing unrelated services/jobs.
5. **Promote and verify under actual authority.** Use protected current-main
   integration, publish artifacts bound to that SHA, and deploy exactly that
   reviewed checkout. Run both public API and frontend smoke, packaged-client
   seven-clip E2E, recovery and scheduled backup/restore against the actual topology.
   Only accepted, retained protocol-7.1 production evidence can open the clean epoch.
6. **Activate validated PL only after empirical review passes.** Complete activation
   or reactivation with the live retained corpus, exact frozen context/policy and
   promoted artifact. Verify API, PL Fit, background rebuild, restart and historical
   stability. Sparse, unreviewed and incompatible rows remain ineligible.

PLA-90 can close only on its actual collection/operations acceptance. PLA-87 and
PLA-141 require real calibration and holdout review. **PLA-70 requires both gates**;
a usable unscored collection service alone does not complete this task. The proposed
validated scope is 1080p24 SDR BT.709; 4K/HDR/HFR and canonical decode/Playback Fit
remain outside it.

## Deployment and rollback handoff

Follow [production activation and recovery](PL_V7_PRODUCTION_ACTIVATION.md) and
[measured operations](operations/collection-operations.md). Before rollout, record
the current images, full checkout SHA, container/volume identities and coherent
backup, and prove the isolated restore. P910's existing volume names must be
selected explicitly: project `encodingdb`, database `encodingdb_db_data`, artifacts
`encodingdb_prod_artifact_data`. Never substitute empty default volumes.

From the clean, exact approved checkout, `./deploy.sh --skip-pull --prepare-only`
validates the suite and builds/prepares images without replacing services.
After applicable production approval, `./deploy.sh --skip-pull` rolls out those
reviewed changes. `--skip-pull` prevents advancing the checkout; it is not proof of
approval or cleanliness. Retain before/after SHAs and image IDs.

Rollback must use the recorded previous images and a schema-compatible recovery
plan. Validate restore into isolated storage before any production restore; retain
all originals. The final release handoff must add actual deployment/run/artifact/
analysis IDs, supported native cells, release URLs/checksums, first accepted epoch
time, and reviewed PL context/policy identity. Until then the verdict stays BLOCKED.
