# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this repository uses date-stamped
release notes until a stricter semver/tagging policy is formalized.

## [Unreleased]

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
