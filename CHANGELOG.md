# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this repository uses date-stamped
release notes until a stricter semver/tagging policy is formalized.

## [1.3.0-rc.10] - 2026-10-05

Release candidate for the targeted PR #23 recovery correction (F8). Publish
saved now isolates missing or damaged artifacts to their recipe group, allowing
independent complete groups to reconstruct and upload in the same pass. Unresolved
evidence remains preserved and visible, and the campaign still reports failure.
Repeated recovery preserves payload identities and does not re-encode accepted work.

The package release advances while the measurement identity remains client/0.3.9,
so compatible saved campaigns remain recoverable. Protocol 7.1, the frozen suite,
and scientific validation are unchanged; PL recommendations remain provisional.
The deployment storage guard also recognizes the production bind-mount topology
without replacing retained data or weakening mount validation.

## [1.3.0-rc.9] - 2026-10-02

Unpublished client 0.3.9 review candidate. Physical online acceptance remains open.

PR #23 reliability corrections F1/F2 (review PLA-547). Publication holds no
longer attempt a POSIX SH→EX escalation when a deferred releaser outlives
the call: on Linux a failed nonblocking conversion can drop the descriptor's
shared lock, letting a collector take the exclusive host phase while an
owned transport worker still performs upload/response-read/close I/O. The
original shared lock is now retained until quiescence (shared already
excludes measurement), and publication coexistence is preserved. Collector
batches gained an explicit bounded publication-to-measurement quiescence
barrier before timed work and before every encode, so a replay or checkpoint
worker abandoned by its deadline (without user cancellation) can never
overlap a timed encode; past the barrier window the campaign pauses safely
with the durable queue and journal retained instead of waiting unbounded.
Response-body close watchers now remain owned until connection close finishes,
including after their bounded join returns. Protocol 7.1, the frozen suite
and scientific checks are unchanged.

Online compatibility and optional baseline metadata now run in owned,
size-bounded subprocesses with absolute deadlines and Stop/Close handling.
A metadata child is reaped before timing starts; exceptional retained work
keeps host exclusion until its death is confirmed. Failed optional baseline
lookups allow contribution to continue, and compatibility still fails closed.
F4 receipt/acknowledgment retirement (review PLA-547). A malformed, empty,
truncated or wrong-identity durable receipt - and any HTTP 200 body that does
not prove the binding between the immutable runCreate payloadHash and the
server's run/artifact identities - can no longer retire the pending queue
entry, the managed staged artifact or journal evidence. A new centralized
validator (client/acknowledgments.py) classifies every upload response,
durable receipt and journal accepted marker; fresh successes, the
uploadRequired=false shortcut, crash recovery, drain, replay and counters all
route through it, so only an acknowledgment bound to THIS payload's run and
artifact authorizes retirement. Unverified receipts are reported as actionable
reconciliation state (unverifiedReceipts, reconcile_receipts) while entries
keep stable IDs and retry deadlines and replay idempotently without
re-encoding; corrupt receipt evidence is preserved inside the superseding
verified receipt instead of being deleted. Journal accepted markers gained a
schemaVersion 2 that additionally binds payloadHash, the server artifact id
and an explicit uploadConfirmed flag; schemaVersion 1 markers stay readable
historical provenance ("historical") but never authorize a fresh verified
claim - publish-saved skips, ledger uploaded counts and recovery acceptance
gate on full v2 proof, and historical or awaiting-reconciliation markers are
surfaced as reconciliation work (awaitingReconciliation) instead of silently
verified. Releasing the ONLY local copy of an artifact now requires verified
durable receipt evidence naming the same run and artifact. Historical
campaigns whose bytes were already retired reconcile through a bounded,
metadata-only analysis-status lookup that upgrades a v1 marker to v2 only
when the server proves it still retains this exact payloadHash/artifact -
bytes are never demanded again and no acknowledgment is fabricated. Upload
confirmation is kept distinct from analysis acceptance (an ACCEPTED run and
a COMPLETE analysis bound to the same run and artifact are required). The transport binds the run AND artifact ids from the
create response through authorization and upload, rejecting any later phase
that names a different identity. The server's bundle responses carry the
minimum immutable evidence this validation needs
(benchmarkRun.payloadHash, artifact.benchmarkRunId), and the
analysis-status route now also returns payloadHash, artifactSha256 and
artifactByteSize for trustworthy metadata-only reconciliation; protocol
semantics, hashes and scientific checks are unchanged.

## [1.3.0-rc.8] - 2026-09-29

Unpublished review candidate. Client 0.3.8 builds console onefile launchers
without forwarding process-group signals twice. The exact rc.7 Mac DMG exited
130 when its child alone received SIGINT during a held upload response, but a
terminal-style group SIGINT left the child waiting; the saved queue survived.
This packaging correction leaves Windows GUI Stop/Close on its own owned
cancellation event. Protocol 7.1 and the frozen suite remain unchanged.

## [1.3.0-rc.7] - 2026-09-29

Unpublished review candidate. Client 0.3.7 gives terminal Publish/Retry a
scoped interrupt signal that cancels and reaps owned network work before it
returns exit 130. A held-response native fault exposed an unhandled interrupt
in rc.6; its queue remained durable, but the exit and traceback were wrong.
The measurement protocol, frozen suite and scientific checks are unchanged.
No public asset is promoted by this note.

## [1.3.0-rc.6] - 2026-09-28

Unpublished review candidate for the September 28 client reliability work.
Client 0.3.6 bounds runtime preparation, carries cancellation and deadlines
through normal uploads, reconciles saved campaign evidence and queue receipts,
and gives Windows Overall and Batch progress durable attempt units that move
as warmups and measurements are recorded, including across checkpoints.
It keeps the guided menu reachable with local queue settings and makes console
output safe under Windows code pages that cannot print every Unicode symbol.
Protocol 7.1, the frozen suite bytes and scientific admission checks are
unchanged. Source and focused tests do not certify the native Medium, fault,
recovery or four-asset release gates; no public asset is promoted by this note.

## [1.3.0-rc.5] - 2026-09-22

Published macOS resume and storage repair from source `b0607f0`. The Windows
GUI and console assets carried the rc.4 binaries; Linux carried an rc.2-era
binary. This release did not contain the later draft PR #22 client work, and
the four assets did not share one updated client source.

## [1.3.0-rc.4] - 2026-09-22

Windows-focused repair with automatic recovery. A suite-cache extraction folder
that the normal user cannot read or replace (for example one left by an
administrator-privileged run) no longer requires manual deletion: after full
archive/manifest/clip verification the client installs a verified copy at a
deterministic writable location beside the blocked folder, announces the
recovery in the preparation event log, and reuses it byte-for-byte on later
runs. The blocked folder is never deleted, taken over or trusted. If neither
location is writable the failure names the actual permission error and the
cache path. The macOS and Linux binaries are byte-identical to the accepted
rc.2 builds. Client 0.3.3; protocol 7.1, admission minimum, suite bytes,
frozen fingerprints and scientific settings unchanged.

## [1.3.0-rc.3] - 2026-09-22

Windows-only repair. The packaged GUI now names every pre-encode failure's
cause in its event log and status line instead of a bare
`Run failed (exit code 3)`, and a suite-cache folder owned by another account
or an administrator-privileged run is detected before re-extraction, with an
exact path and recovery instruction, instead of failing a swap that can never
land. Client 0.3.2; protocol 7.1, admission minimum, suite bytes and
scientific settings unchanged. macOS and Linux binaries are byte-identical
to the accepted rc.2 builds.

## [1.3.0-rc.2] - 2026-09-21

Restore guided Small, Medium, Large and Full encoder sweeps with automatic
publication after consent, visible budgets, checkpoints and upload recovery.
Package macOS as a disk image with an application launcher and Linux as an
executable-preserving archive. Repair responsive downloads, table alignment,
hardware labels and the contribution flow. Client 0.3.1 retains protocol 7.1
and its existing admission minimum; PL remains unavailable pending calibration.

## [1.3.0-rc.1] - 2026-09-14

Unpublished corrected-collection candidate. Protocol 7.1 separates process-only
encode timing and physical source identity from historical 7.0 measurements.
Client 0.3.0 adds authoritative quick/full contributions, durable attempts and
upload-only recovery. Server changes enforce complete media, bounded admission,
fenced analysis, append-only reviews and bounded corpus/health queries.

PL activation remains gated on genuine final-suite calibration and human
holdout review. Native builds and staging tests do not certify a production epoch.

## [1.2.0] - 2026-09-13

Approved promotion of the reviewed canonical-suite candidate. Public artifacts
are built from the resulting main commit and bound to tag `1.2.0` at publication.

### Added

- Seven frozen, hash-verified canonical references and compatible `client/0.2.0`
  packages for Linux, macOS and Windows.
- Retained V7 artifact upload, authoritative analysis and browsable corpus data
  while PL remains unavailable pending separate calibration.

### Fixed

- Verified suite and image preparation now completes before deployment rollout.
- Production readiness and homepage checks match the shipped stack.
- Existing frame-alignment, runtime and packaged-client submission repairs from
  the reviewed beta candidate are included without changing metric bands or CRF defaults.

### Release limitations

- Clients remain unsigned; macOS is not notarized and its Intel FFmpeg helper
  requires Rosetta on arm64. Windows GUI/GPU combinations remain untested.
- Athletic-action proxy, letterboxing and added-grain source limitations remain
  documented. PL calibration and longer-content holdouts remain post-release.

## [1.2.0-beta.1] - 2026-09-09

Candidate preparation for deployment review; not a production release.

### Added

- Canonical EncodingDB Test Suite v1 manifests, generated suite assets, and
  VMAF model provenance required for PL Score v7 retained-artifact workflows.
- Authoritative artifact ingest, retained analysis, reference-context,
  calibration, and operational-health support for the v7 pipeline.
- Expanded frontend methodology, leaderboards, encoder workflows, and release
  support documentation.
- Release preflight and production smoke automation for CI and operator use.

### Changed

- Promoted repository licensing to Apache-2.0 with explicit NOTICE and suite
  provenance handling.
- Standardized release hygiene by ignoring generated `.omx` runtime files,
  generated development certificates, and legacy `sample.mp4` debris.
- Updated release metadata to match the shipped frontend stack and documented
  beta-to-main release posture.

### Removed

- Legacy tracked development runtime artifacts under `.omx/`.
- Tracked self-signed nginx certificate material from version control.
- The obsolete root-level `sample.mp4` artifact that is no longer part of any
  canonical suite or compatibility contract.
