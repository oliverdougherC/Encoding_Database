# Release handoff — 1.3.0-rc.10

**The collection clients and updated website are published and deployed. PL remains provisional; unattended backup and failure-alert integration remain open.**

Download the [published rc.10 release](https://github.com/oliverdougherC/Encoding_Database/releases/tag/1.3.0-rc.10) or use the [live download page](https://encodingdb.platinumlabs.dev/run). The release is marked **prerelease**. All four client downloads were anonymously downloaded again over verified HTTPS and matched their accepted SHA-256 identities. The release contains 30 assets, including native receipts, checksums, installation guidance and notices.

This replaces the active handoff, not historical evidence. The [previous handoff at the client/server release commit](https://github.com/oliverdougherC/Encoding_Database/blob/daa3e8e99e17e4cf99fb9440a90f96cbc25bdb2f/docs/FINAL_RELEASE_HANDOFF.md) and [earlier rc.9 acceptance packet](collection-readiness/overnight-20261004/README.md) remain available with their original limits.

## Published identities

| Item | Identity |
| --- | --- |
| Project release | `1.3.0-rc.10`, published October 5, 2026 |
| All four client artifacts and deployed server source | `daa3e8e99e17e4cf99fb9440a90f96cbc25bdb2f` |
| Deployed website source | `6ca1b4285d85a3d70b24f91023548b0e9b85de40` |
| Integration | [PR #23](https://github.com/oliverdougherC/Encoding_Database/pull/23) and [PR #24](https://github.com/oliverdougherC/Encoding_Database/pull/24) merged |
| Client measurement/journal identity | `client/0.3.9` |
| Protocol / encode timer | `7.1` / `ffmpeg-process-v1` |
| Suite / quality model / formula | `encodingdb-test-suite-v1` / `vmaf-v1-sdr-1080p` / `7.0` |
| PL activation | Inactive; no recommendation-ready claim |

The project release version and client measurement identity are separate. The F8 recovery correction preserves `client/0.3.9`, protocol and runtime identity so original compatible journals can be recovered without rewriting their provenance. Exact source and executable/package hashes distinguish this release from earlier rc.9 packages. The website's later commit stamps the published links and hashes; client/build inputs remain unchanged from the release source.

The frozen suite fingerprint is `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e`. Scope remains 1920×1080, 24 fps SDR BT.709. Source media, model and runtime identities were not loosened to obtain acceptance.

| Download | Supported scope |
| --- | --- |
| macOS DMG | Apple Silicon, macOS 27 or later; guided Terminal app; ad-hoc signed, not notarized |
| Windows GUI and console | Windows 11 x86-64; unsigned, so SmartScreen may warn |
| Linux archive | Ubuntu 24.04 x86-64; other distributions unverified |

Use the public [SHA256SUMS](https://github.com/oliverdougherC/Encoding_Database/releases/download/1.3.0-rc.10/SHA256SUMS) and [shared release manifest](https://github.com/oliverdougherC/Encoding_Database/releases/download/1.3.0-rc.10/client-release-manifest.json). A compact copy of the four verified download identities is in [publication evidence](collection-readiness/release-20261005/publication.json).

## Executed acceptance

- **F8 recovery on the new packages:** 16 controlled cases across macOS, Linux, Windows console and Windows GUI; 32 publication/retry invocations and zero new encodes. Cases cover missing or hash-mismatched retained artifacts in first and later positions, while healthy siblings remain publishable. These used authentic copied journals against explicit controlled retention fixtures. They are distinct from the earlier rc.9 conservation/fault evidence, not a relabeling of those binaries.
- **Actual production contributions:** six genuine, previously absent payload identities from three original physical hosts became six ACCEPTED runs, RETAINED artifacts and COMPLETE authoritative analyses. Ordinary upload-only execution used default TLS trust. Original source IDs, runCreate objects, payload hashes and measured provenance were preserved; no new encode or synthetic production benchmark was introduced. Object deduplication meant two observed artifact PUTs, not six independent byte transfers.
- **Windows GUI replay:** the real Retry control returned the same two Windows production bindings, with no new rows, PUTs or attempt records; pending count was zero and exit was clean without forced cleanup.
- **Public UI:** the deployed `/run` page shows rc.10 and four actual download links. 1280-pixel desktop and 390-pixel mobile checks passed without horizontal overflow. Mobile navigation reached six real hardware groups; Browse showed the three newly accepted groups. Directory pages use real accepted/suspect corpus observations and do not imply calibrated recommendations.
- **Public smoke:** the [non-mutating production workflow](https://github.com/oliverdougherC/Encoding_Database/actions/runs/37361212102) passed against the deployed API and frontend.
- **CI:** all 13 checks passed for the client/server release source. At the [website CI snapshot](collection-readiness/release-20261005/ci.json), frontend, stack-smoke, preflight and the other completed checks passed; its redundant Windows native build was still running. This packet does not claim all website-revision checks had completed at that snapshot.

See the [release acceptance packet](collection-readiness/release-20261005/README.md) for the redacted receipts and hashes of retained raw proofs. Acceptance covers the stated builds, supported platforms and executed cases.

## Deployment and recovery

The new server was deployed before publishing rc.10, while the old rc.5 frontend remained available. This established the strict acknowledgment contract before users could download the new clients. After publication and independent download verification, the website alone was replaced. Existing database/storage bindings, ingress and contribution identities were preserved. Recorded counts moved from 507 original run/artifact/analysis bindings to 513 after the six genuine production contributions.

A coherent paired production backup and isolated restore passed for 507 artifacts and all 18 inventoried tables / 1,904 rows. The artifact archive was approximately 1.98 GB; writer quiescence lasted 59 seconds. File hashes and restored table inventories matched. A private off-host copy was also verified. This is evidence for the actual snapshot, not a test of the full configured storage quota.

**Scheduled production backup/restore and failure alerts are not installed.** The user selected an existing monitoring/webhook service, but its service/configuration reference is still required before integration and a delivery test. The one-time off-host copy does not establish ongoing retention. The project is not yet certified for unattended operation. See [operations evidence](collection-readiness/release-20261005/operations.json).

## Remaining PL work

The [PL evidence packet](collection-readiness/pl-20261004/README.md) contains 220 qualified fitting observations and 32 qualified holdout observations. Dark gradients still lacks qualified fitting evidence; 20 rate-coverage and eight within-preset findings remain, with overlap. Independently fitted holdout evaluations, genuine golden/family-choice judgments and a reviewed freeze are incomplete.

The release does not change score constants, lower eligibility thresholds, relabel suspect evidence or activate PL. Upload correctness and collection publication do not establish scientific recommendation validity. Those gates and the operational automation above remain explicit follow-up work.
