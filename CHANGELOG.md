# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this repository uses date-stamped
release notes until a stricter semver/tagging policy is formalized.

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
