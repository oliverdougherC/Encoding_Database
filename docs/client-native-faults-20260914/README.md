# Packaged client fault evidence — 2026-09-14

These checks are diagnostic under concurrent build/preflight load, not calibration or GUI certification. No production submissions are made.

## Confirmed packaging failure

The Mac executable built from source `84d4086` passed help but failed its local contribution smoke before encoding with `runtime dependency SHA-256, membership or size mismatch`.

The retained CArchive audit in `packaging/failed-84d4086-archive-audit.json` compares the actual executable with the reviewed lock. Both helpers and all 100 dependency files changed despite matching membership and byte sizes. PyInstaller 6.19 reclassified the supplied Mach-O DATA entries as BINARY, then changed their load commands/signatures during PKG assembly.

The correction preserves only the reviewed `bin/mac` helpers/dependencies as DATA after Analysis. PyInstaller 6.19 preserves executable mode for executable DATA without performing its binary transformation. Other Python runtime binaries still undergo normal packaging. Archive verification must match every original helper/dependency hash, the embedded reviewed lock, membership and executable flags before smoke can pass.

The prior native CI environment exposed provisioned external helpers through `FFMPEG_EXE`/`FFPROBE_EXE`. Smoke now removes helper, lock and loader overrides, preserves explicit suite/cache/installation state, and requires a fresh runtime-verification receipt from within the packaged extraction directory. A help-only or external-helper success is not embedded-runtime certification.

Original failing executable remains at `.build/release-20260914/macos-final/encodingdb-client-macos` in the integration checkout. Its original SHA is recorded in the audit. Fault campaigns were postponed until this integrity gate is repaired; no failed package was used for calibration.
