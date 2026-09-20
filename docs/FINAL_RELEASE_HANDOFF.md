# Final release handoff — 1.3.0-rc.1

**Verdict: BLOCKED.** Native and operational evidence has advanced, but final
GUI/native acceptance, empirical calibration, human review and protected promotion
remain open. Neither READY FOR COLLECTION nor READY WITH VALIDATED PL is claimed.
This is a checkpoint while the remaining acceptance work runs; in-progress work is
not counted as passed.

## Candidate and published baseline

The application candidate is `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2`.
Operator/harness and evidence changes carry their own commits; they do not relabel
older binaries or observations. This is not an approved production deployment SHA.

| Identity | Current state |
| --- | --- |
| Candidate | `1.3.0-rc.1`, unpublished |
| Candidate measurement | `client/0.3.0`, protocol `7.1`, `ffmpeg-process-v1` |
| Public download | [1.2.0](https://github.com/oliverdougherC/Encoding_Database/releases/tag/1.2.0), client/0.2.0, historical protocol 7.0 |
| Preserved main / last verified production code | `b0f0bc7d12cb127c86a7c76979eb361398e293dd` |
| Suite | Frozen seven 1920×1080, 24 fps SDR BT.709 clips; animation 192 frames, others 240 |
| Suite fingerprint | `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e` |
| Pack SHA256 | `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150` |
| Model / PL formula | `vmaf-v1-sdr-1080p` / `7.0`; public calibration inactive |

The [production inventory](operations/evidence/production-timing-inventory-before-migration-20260914.json)
preserves four original protocol-7.0 SUSPECT runs and their artifacts. No corrected
production epoch, 1.3 download URL or production approval is implied by this packet.

## Executed evidence and current limits

- **Physical Windows:** the [b3 acceptance packet](collection-readiness/windows-physical-b3ef24a/README.md)
  records three complete seven-clip campaigns: x264 CRF23, NVENC CQ24 and native
  NVENC VBR6000. One installation retained **63 VALID attempts, 42 measured runs
  and 21 stable groups**. Four controlled cases passed: offline upload,
  backpressure, corrupt pack and storage-budget exhaustion. Original evidence is
  retained; a queue budget is not physical disk-full, and loopback backpressure is
  not candidate/production ingestion. Final GUI acceptance remains pending the
  corrected SendInput harness; three campaigns do not establish three independent
  machines.
- **Hosted Windows:** [b3 console acceptance](collection-readiness/windows-native-b3ef24a/README.md)
  passed all seven clips with seven warmups and fourteen measured artifacts, whose
  hashes were independently audited. The first three GUI phases passed; the prior
  Close phase remains blocked and preserved. A corrected harness must demonstrate
  acceptance before that gate closes. Hosted software execution does not substitute
  for physical GPU evidence.
- **Mac:** the [b3 package/embedded smoke](collection-readiness/mac-build-b3ef24a/README.md)
  passed. It is native ARM64, has a complete-runtime **macOS 27.0** minimum, and is
  ad-hoc signed without Developer ID signing/notarization. The coordinator reports
  current AC power and valid fresh software/VideoToolbox preflights; fresh b3
  seven-clip acceptance is **in progress**, with no outcome assumed. The separate
  [939 software/VideoToolbox packet](collection-readiness/mac-seven-939823e/README.md)
  verifies 42 retained artifacts and fourteen stable groups; **five VideoToolbox
  measured attempts remain SUSPECT**. Their GPU/battery flags are unchanged.
  [Native fault evidence](collection-readiness/mac-faults-939823e/README.md) retains
  its own package identity. Intel macOS and older macOS versions remain unproven.
- **Linux candidate:** [b3 isolated preparation](operations/native-candidate-b3ef24a.md)
  passed the native build, exact 29-migration verification, trusted API/frontend
  TLS checks and paired backup/isolated restore. The existing volumes and
  production services were preserved. The restore corpus was empty, and this
  preparation was not native campaign acceptance. The final b3 Linux native run
  is now running after capacity handback; it has no accepted result in this checkpoint.
- **P910 serving:** the [b3 repeated capacity trial](collection-readiness/projection-p910-b3ef24a/README.md)
  **passed** its unchanged 25-reader/600-second contract: **25,106 requests,
  p95 985.57 ms, zero errors/OOM, all five writer cycles and exactly 80,020
  qualified members**. The margin below the 1,000 ms limit is only **14.43 ms
  (1.44%)**. Limits remained 16 GiB API, 1 GiB DB, 256 MiB shared memory and 30
  connections. This is isolated synthetic metadata HTTP load; it proves neither
  media-worker capacity nor browser/proxy performance or spare production headroom.
  [Earlier failed trials](collection-readiness/projection-p910-20260920/README.md)
  and their original results remain retained.
- **Recovery:** the [full-size backup trial](operations/evidence/p910-backup-scale/receipt.json)
  restored 10 GiB of retained synthetic objects plus a 10 GiB staging mirror.
  [Unattended cron proof](operations/evidence/p910-unattended-cron/verification.json)
  records actual successful backup/restore orchestration. Production installation,
  off-host retention and an authorized alert recipient/delivery test remain open.
- **Holdouts/calibration:** the [corrected 42-cell software holdouts](collection-readiness/holdouts/corrected-cpu-software-complete/README.md)
  are complete and audited: 37 stable cells and five unstable/ineligible cells,
  all 136 retained attempts preserved. Their authoritative quality/ranking and
  human review are still pending. The [28 hardware holdouts](collection-readiness/holdouts/hardware-execution-939823e/README.md)
  and [840 canonical cell/sessions](collection-readiness/canonical-execution-b3ef24a/README.md)
  have **not run**. Their manifests/dry plans are not execution evidence or host
  allocations. Approximately 16 GiB free on Mac is not a full-matrix retention
  capacity proof.

Each receipt binds its actual source, binary and scope. Earlier test receipts and
failed/suspect observations stay historical; passing later checks does not rewrite
them. Synthetic capacity/recovery fixtures remain outside calibration and production.

## Remaining release gates

1. **Finish exact-candidate acceptance.** Close the corrected Windows GUI gate and
   ongoing Mac/Linux native campaigns, then complete retained-artifact publication
   and recovery against the actual candidate topology. Bind support claims to
   executable/helper/model hashes, architecture, OS floor, signing and observed
   outcomes. Reconcile full preflight, migrations and affected checks with the final
   integrated application/operator revisions; a successful console or build does
   not close every native gate. QSV/AMF support remains unproven.
2. **Execute calibration without changing the experiment.** Allocate quiet hosts
   and sufficient retained storage, run the frozen 840 canonical cells/sessions
   and 28 hardware holdouts, and preserve failures, instability and all attempts.
   Finish all timing before bulk publication/analysis. Run actual authoritative
   quality analysis, fitted content/recipe/family holdouts and production ranking
   verification with exact cohorts and retained evidence. No rerun, dropped cell or
   lower threshold may be used to manufacture acceptance.
3. **Obtain genuine review and operational completion.** Knowledgeable human review,
   including the original suspect evidence and Balanced/Quality/Storage/Realtime
   decisions, remains open. So do the alert recipient/test and final production
   backup/retention arrangements. Freeze contexts and policies only after the
   [calibration contract](V7_CALIBRATION_EVIDENCE.md) passes; no human judgment is
   inferred from automated checks.
4. **Prepare and perform protected promotion under actual authority.** Present the
   exact artifacts, support matrix, migration/capacity limits, coherent backup and
   rollback to the authorized approver after independent preparation is complete.
   Preserve current main/data and use protected reviewed integration. Publish real
   SHA-bound artifacts and deploy the approved checkout, then verify public API,
   frontend, packaged contribution/recovery and scheduled backup/restore. Current
   links remain release 1.2 until an authorized publication actually exists.
5. **Open the corrected epoch and activate PL only when eligible.** Accepted retained
   protocol-7.1 production evidence, completed empirical review and the exact frozen
   context/policy are prerequisites. Verify rebuild/restart and historical stability;
   sparse, incompatible, unreviewed and suspect evidence stays ineligible.

PLA-90 requires actual collection/operations acceptance; PLA-87 and PLA-141 require
real calibration/holdout review. **PLA-70 requires both gates.** A usable unscored
collection service alone does not complete this task. Scope remains 1080p24 SDR
BT.709; 4K/HDR/HFR and canonical decode/Playback Fit are outside this validation.

## Deployment and rollback handoff

Follow [production activation/recovery](PL_V7_PRODUCTION_ACTIVATION.md) and
[measured operations](operations/collection-operations.md). Record current images,
checkout SHA, containers, volumes and a coherent backup before rollout. Existing
P910 volumes must be selected explicitly: project `encodingdb`, database
`encodingdb_db_data`, artifacts `encodingdb_prod_artifact_data`; never substitute
empty defaults or disturb unrelated services/jobs.

From the exact approved checkout, `./deploy.sh --skip-pull --prepare-only` prepares
without replacing services. Only applicable production authority permits
`./deploy.sh --skip-pull`; that flag prevents advancing the checkout and does not
itself prove approval or cleanliness. Rollback uses recorded prior images and a
schema-compatible plan, with isolated restore verification and originals retained.
The final handoff must add actual deployment/run/artifact/analysis IDs, published
URLs/checksums, accepted epoch time and reviewed PL context/policy. Until those
gates close, the verdict remains BLOCKED.
