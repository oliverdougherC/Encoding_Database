# EncodingDB beta deployment review

Status: candidate under repair review; protected beta integration is pending. PR #12 remains open and beta remains `830e30375ec13d02ea00289c531e0e05e0d91b72` at the recorded link check. No integrated beta SHA or post-integration attestation exists yet. The earlier `beta-integration-handoff.json` link was premature and returned HTTP 404; it has been removed. After authorized beta integration actually occurs, record its real integrated SHA and successful checks in a retrievable attestation. Production deployment remains outside this assignment; the tested application and artifact source SHAs below identify historical candidate evidence.

## Review boundary

Starting beta: `830e30375ec13d02ea00289c531e0e05e0d91b72`. Integration PR: [#12](https://github.com/oliverdougherC/Encoding_Database/pull/12), targeting beta. Production deployment, final publication, beta-to-main merge and opening the production evidence epoch are not performed by this assignment. PL calibration (PLA-87) and longer-content holdouts (PLA-141) remain post-release; PLA-90/PLA-70 retain production acceptance.

## Canonical references

All seven files are progressive 1920×1080, 24/1 fps, 8-bit 4:2:0 BT.709 limited SDR, FFV1/Matroska, video-only. Six are 10 seconds; animation is 8 seconds. Manifest version 2 uses new clip identities under v1, preserving historical fixture identities rather than changing registered rows in place.

| Class | Clip ID | Frames | Bytes | SHA-256 |
| --- | --- | ---: | ---: | --- |
| high-motion-sports | athletic-action-1080p24-final | 240 | 139815565 | `1e06fe0315d0cb90247a3dae2258327989e657496247ca8974ddd8c2431755de` |
| fine-natural-detail | natural-detail-1080p24-final | 240 | 283872120 | `cfcc51d48372138f6f66b3286fec5a533a808650098e40f119011060d8e51225` |
| film-grain-noise | film-grain-1080p24-final | 240 | 336898554 | `67d3d2f5a4f8c617f223077e7071aaee625f014950126e0e93a16b27e578d603` |
| dark-gradients-shadows | dark-gradients-1080p24-final | 240 | 317829621 | `3377e6927fdd256633961520ace19f6b5b1494f689841ed3a29831e48e0d27c3` |
| animation-flat-fields | animation-1080p24-final | 192 | 173819800 | `d70c4d9e85e88c4369b6391a21f0388a4a3a7b72e1b89f545e5897b4d5d820ea` |
| screen-text | screen-text-1080p24-final | 240 | 35313873 | `3c024a4aceb4ad09f8fa8cf51b6a4aba9be68460acb3f6a24a223e287bc05c8c` |
| talking-head | talking-head-1080p24-final | 240 | 219125475 | `ac85d1350e5e668d5c0798b25fd7de16f8da05e831f396680a8f0f0ab05bcaf3` |

Suite lock: `41ae332c8e4ac7ae49c2a44917729c65d7a062710e4b44961b8125ffe7fb2660`. Pack: `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150`, 1,506,890,018 bytes; suite inventory fingerprint `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e`.

[Source selection, exact ranges, rights and preparation](canonical-suite/README.md), [original input inventory](canonical-sources/selected-source-inventory.json), [per-asset notices](canonical-suite/notices/), and [executed media evidence](canonical-suite/evidence/) are committed. Source hashes identify actual downloaded ranges/frames or retained excerpts, never an undownloaded whole master. Original upstream references are independently staged; exact URLs,hashes,size and access checks are in [staged-source-artifacts.json](canonical-sources/staged-source-artifacts.json).

The action slot is an explicitly disclosed live-action/VFX athletic-action proxy, not a sporting event. Natural detail uses a documented P3/PQ→linear→Hable→BT.709 conversion and spatial reduction. ToS references retain letterboxing. Animation emphasizes smooth face shading and fine cel/hair lines. Grain is producer-added; grain/dark ranges do not overlap. These limits constrain extrapolation and must remain visible in deployment review.

## Executed media and acquisition validation

- Full decode, complete frame counts/rational timing, timestamps, dimensions/aspect,color/depth/chroma/HDR inventory, hashes and sizes for all seven.
- Actual temporal contact-sheet/full-resolution frame review by Codex; no fabricated human sign-off or claimed continuous human playback review.
- 56 real encoder/rate cases: per-clip x264 CRF20/28/36,x265 CRF28,SVT-AV1 CRF32,AOM-AV1 CRF32,VP9 CRF32,and VideoToolbox2500kbit/s. VMAF full frame distributions and XPSNR executed; packet-size bitrate and elapsed throughput retained. SVT used a separately recorded Homebrew runtime, not a claimed Evermeet capability.
- The pinned model SHA is `e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e`. An identical-reference action anchor scored 100 throughout. A real client/server differential exposed incorrect time-base and pixel-format alignment: the same encoded action bytes scored 64.872349 in the old client and 97.552275 authoritatively. The client and native model verifier now use the canonical frame/time-base and 10-bit VMAF graph. All 56 retained encodes were re-scored; invalid old metrics are quarantined in the validation archive. Frame-count/rate mismatches and missing or partial metric distributions fail closed. No PL constants or acceptance bands were changed.
- Existing finalizer executed and actual repeat produced identical client/server metadata; [idempotence evidence](canonical-suite/evidence/finalizer-idempotence.json). URL routing was pinned after freeze and is outside the archive's content identity.
- [Public clean-checkout acquisition](canonical-suite/evidence/clean-checkout-acquisition.json) downloaded from the manifest URL with empty cache and no pack override, then verified 14 client/server files.
- [Actual interruption/corruption recovery](canonical-suite/evidence/acquisition-recovery.json) covers 4 MiB interrupted download,resume,archive corruption,atomic extraction,cache reuse and repair. Cached verification improved 57.477s→0.662s while preserving every file hash and full initial/repair/requested-use media checks.

## Runtime and engineering checks

The old macOS runtime advertised libvmaf but failed the actual model's CAMBI feature. Its replacement was signature-verified and executed the unchanged model successfully. Locked Linux/Windows identities came from native CI, using immutable upstream archives. Windows model bytes are protected from CRLF checkout conversion. Native packaging verifies actual model execution as well as runtime identity.

The full local release preflight passed all 11 gates. Native CI executed 166 server tests, 155 client tests and 37 frontend tests successfully, plus migration, stack smoke and all three native builds. The [native and application CI run 34430919675](https://github.com/oliverdougherC/Encoding_Database/actions/runs/34430919675) passed on feature head `192f81fe171bad6d172abe4d943814d3a2094402` / PR merge `2d3ed7d4d1670962cb248589942204a1341120e9`. [Dependency audits](https://github.com/oliverdougherC/Encoding_Database/actions/runs/34430919644) and [full release preflight](https://github.com/oliverdougherC/Encoding_Database/actions/runs/34430919705) passed. [Executed CI identities and jobs](canonical-suite/evidence/candidate-ci.json) are committed. These historical runs do not attest to beta integration or to the deployment repair. Beta integration and its resulting checks remain pending; the repair must carry its own executed checks and exact tested SHA. A prior diagnostic run's audit/fixture failures are retained as failures, not counted as acceptance. Current high-severity audit gates pass; two moderate Vitest development-tool findings remain and require a major upgrade. [Dependency evidence](canonical-suite/evidence/dependency-verification.json).

## Candidate artifact access

[Nonproduction artifact staging](https://github.com/oliverdougherC/Encoding_Database/releases/tag/encodingdb-beta-review-assets-20260909) is a prerelease staging container, not a final application publication. Source excerpts and exact pack are publicly accessible without login. Do not delete while referenced; retain until an approved release/recovery bundle supersedes them. GitHub Actions native build artifacts have 90-day retention and require GitHub access. The following selected artifacts have matching GitHub release metadata SHA-256/size and anonymous HEAD access. The [report link check](canonical-suite/evidence/report-artifact-links.json) records the PR/beta metadata, all direct report links, and the removed missing attestation. Each of the seven selected archive URLs returned HTTP 200 after redirects; existing local links were tracked and also returned HTTP 200 at the immutable PR head. This access check did not download or rehash full archives and does not replace the earlier executed byte-integrity evidence. [Machine-readable delivery evidence](canonical-suite/evidence/candidate-delivery.json) and [Linux/Windows build evidence](canonical-suite/evidence/native-candidate-artifacts.json) bind executable checksums, source SHAs, sidecars and native smoke results. Older generic macOS and `735c7c8` assets are superseded diagnostics.


| Selected artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| [beta-retained-certificate-d554d04.tar.gz](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/beta-retained-certificate-d554d04.tar.gz) | 579129021 | `815ee1ea795b7986b12aad75d5394d02c246a92117a5cef443be4d894265d5e7` |
| [canonical-validation-d554d04.tar.gz](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/canonical-validation-d554d04.tar.gz) | 1274938615 | `31bc3dc9a7af41d170e50eda58f1cc5be87e14f16cd839194e27b05781055ece` |
| [encodingdb-macos-d554d04.tar.gz](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/encodingdb-macos-d554d04.tar.gz) | 68073674 | `1317f23400e2f602c20a0f101722026af8fedca823d88d572c72985b365f51d4` |
| [Frozen suite pack](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/encodingdb-test-suite-v1.tar.gz) | 1506890018 | `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150` |
| [beta-engineering-evidence-192f81f.tar.gz](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/beta-engineering-evidence-192f81f.tar.gz) | 114715 | `d3ea0f5b00b17f360230b0f21e3e31ad351613bbd1aa745103eba3891d2035a3` |
| [encodingdb-linux-candidate-ci34430919675-2d3ed7d4d167.tar.gz](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/encodingdb-linux-candidate-ci34430919675-2d3ed7d4d167.tar.gz) | 169129799 | `cb2712b94b705cf447eb4b550e8f3b2be1bfcc6120db1f361a6534234bfb325c` |
| [encodingdb-windows-candidate-ci34430919675-2d3ed7d4d167.zip](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/encodingdb-windows-candidate-ci34430919675-2d3ed7d4d167.zip) | 294384846 | `9e00b681397044ced552ec9539d10af42c731fe5a8b583eb9efb72de917fbe05` |

## Packaged-client certification

**Passed on the actual downloaded macOS executable:** 16 accepted runs, 16 retained artifacts, 17 completed authoritative analyses (including reanalysis), and seven visible frontend corpus rows. Every PL total/component is null with calibration explicitly absent and test-only PL disabled. No synthetic fixture populated this corpus. The [committed certificate summary](canonical-suite/evidence/packaged-client-summary.json) contains every run, artifact, hash and analysis ID; the public certificate archive above contains raw logs, UI evidence and paired database/artifact backups.

The tested executable was built from `d554d045ca141ab7c0a282649f5ebef4d674d7bf`; certification used checkout `a307fef77b06b1a13e273ca105d98f113a83b681`, which adds lossless BIGINT report serialization without changing the client application. Later `192f81f` aligns the native model verifier; it does not change the packaged application's source. The macOS binary SHA-256 is `d90fd7ca6ba72509b4a456171bf24780b155a9ba085503ab455b407805503560` (68,565,024 bytes). Native Linux/Windows artifacts have their own exact CI source mapping.

The accepted run used x264 CRF 12 after a predeclared six-case CRF 12/8 rate check on the three difficult classes. Existing CRF 24 attempts remain retained as diagnostic evidence: eight of sixteen were SUSPECT under unchanged metric bands and are excluded from acceptance. No status override or manual approval was applied. See [rate-sanity evidence](CERTIFICATION_RATE_SANITY.md). CRF 12 demonstrates collection, not a proposed universal default or PL calibration setting.

- Execution: 2026-09-10 02:04:43–02:29:12 UTC, approximately 24 minutes 29 seconds, including empty-cache verification, warmups, repetitions, uploads and authoritative analysis/reanalysis. The public initial pack download was separately executed in the clean-checkout test.
- Seven unique encoded objects total 537,543,021 bytes. The injected failed upload accounts for another 32,489,227-byte attempt. This substantial cost is disclosed.
- One actual injected HTTP 503 recovered the original run through the existing content-addressed upload/deduplication path. The same artifact/run was subsequently retained and analyzed; no synthetic success record replaced it.
- Reanalysis returned HTTP 202 and reused analysis `cmtuwrv10002jpr0or4c6z5kd` for run `cmtuw0snc0005pr0orqi48emx` on repetition.
- The historical 960×540 clip was rejected with HTTP 404 and the canonical-resolution error; zero legacy accepted runs or payload rows were created.
- All sixteen client VMAF means match authoritative means within 0.000001. Client interpolated P5 and server nearest-rank P5 remain explicitly distinct; server analysis is authoritative.
- Actual frontend inspection showed all seven rows and “PL unavailable”; screenshots and accessibility text are in the certificate archive. Raw API evidence confirms seven rows and null PL.
- Paired backup and isolated restore drill passed for all sixteen artifact records, with zero derived members. Original CRF 24 review records were backed up separately. All original certificate checksums were verified before removing duplicate install/cache copies; the portable evidence maps them to the separately retained exact suite/client artifacts.

The first helper attempt was a failed dry run with zero server artifacts and is excluded from acceptance. The helper now explicitly submits, isolates subprocess stdin, distinguishes queued payloads from audit records, and reports timing/counts truthfully. Original failures remain in the certificate archive.

## Executed command and evidence matrix

Commands below name the actual entry points; environment-specific input paths and full commands are retained in the linked evidence, without production secrets. Every acceptance row exited successfully; failed diagnostic runs are explicitly excluded above.

| Entry point | Executed result | Durable evidence |
| --- | --- | --- |
| `scripts/acquire_canonical_sources.py`, `capture_canonical_screen.mjs`, `prepare_canonical_references.py` | Actual selected inputs, cache reuse, seven prepared references | `canonical-sources/acquisition-validation.json`, per-clip preparation JSON, staged sources |
| `scripts/validate_canonical_media.py`, `rescore_canonical_media.py` | 56 real encodes and corrected complete-frame metrics; six additional rate checks | Public canonical-validation archive and committed per-clip results |
| `scripts/finalize_test_suite_v1.py` repeated | Same frozen metadata on repeat | `canonical-suite/evidence/finalizer-idempotence.json` |
| `scripts/materialize_final_suite.py` from clean checkout | Public pack downloaded, 14 matching client/server files | `canonical-suite/evidence/clean-checkout-acquisition.json` |
| `scripts/certify_suite_acquisition.py` | Actual interruption, corruption, atomic extraction and cache repair pass | `canonical-suite/evidence/acquisition-recovery.json` |
| `bash scripts/release_preflight.sh` | All 11 gates pass, exit 0 | Public engineering-evidence archive, full individual local logs; linked CI preflight |
| Native CI and application test jobs | 166 server, 155 client, 37 frontend tests; Linux/macOS/Windows locked builds and smoke pass | `candidate-ci.json`, native delivery JSON and public sidecar bundles |
| `scripts/certify-beta-corpus.sh --software-crf 12` with staged client/pack and isolated server/frontend | Accepted authority chain, exit 0 | Public retained-certificate archive, committed packaged-client summary and frontend screenshot |
| `scripts/v7-backup.sh`, `scripts/v7-restore-drill.sh` against isolated candidate database/store | Backup hash checks and isolated restore pass; 16 artifacts | Public retained-certificate backup and engineering-evidence logs |

## Remaining review limits

The seven-reference preparation, frozen distribution, standalone clean acquisition and executed macOS collection/retention evidence above remain intact. PR #12 review identified a separate clean-checkout production preparation gap; historical standalone acquisition and CI success do not prove the supported deployment path. The repair must be reviewed with fresh-checkout, empty-cache production-like execution, resulting image hashes, failure-before-rollout evidence and affected release checks. Beta integration remains pending. Production deployment remains a separate approval and production-environment exercise. This candidate is unsigned/not notarized; macOS arm64 uses the verified Intel FFmpeg helper through Rosetta. Windows native CLI/model/build checks ran, but interactive Windows GUI behavior and additional GPU hardware combinations were not exercised here. Source proxy, letterboxing, added grain and HDR conversion limits above remain relevant. Two moderate development-only audit findings remain; high/critical gates pass. Human release approval, production credentials/configuration and production smoke are not represented as completed. PL calibration and longer-content holdouts stay post-release.

## Production operator sequence

Follow [FINAL_RELEASE_HANDOFF.md](FINAL_RELEASE_HANDOFF.md): review this candidate → protected beta-to-main integration → bind final artifacts to reviewed main → paired database/artifact backup → deploy the exact reviewed SHA → production smoke and real packaged-client retention/analysis/corpus verification → declare the clean evidence epoch. Do not activate PL until its separate calibrated-context gate passes. Use the documented isolated migration/restore rehearsal and paired-volume rollback; no production credentials,databases or volumes were changed here.
