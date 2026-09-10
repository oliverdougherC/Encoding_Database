# Client Build Runtime Contract

EncodingDB client packaging now treats FFmpeg and ffprobe as a locked runtime, not an ambient host dependency.

## Runtime lock

- Checked-in lock: [client/resources/runtime/ffmpeg-lock.json](../client/resources/runtime/ffmpeg-lock.json)
- Scope: pinned `ffmpeg` and `ffprobe` path identity, SHA-256, byte size, version line, build fingerprint, and required capabilities
- Required capabilities:
  - `ffprobe`
  - FFmpeg filters `libvmaf` and `xpsnr`
  - Software smoke/runtime encoders `libx264`, `libx265`, `libaom-av1`, and `libvpx-vp9`
- Optional supported encoders are recorded separately per platform. Hardware/device-specific encoders such as VideoToolbox, NVENC, QSV, and AMF are never treated as universal requirements.

Platform builders package that lock resource and emit a release-specific runtime-lock sidecar for the exact bundled binaries they shipped.

## Operator workflow

Tracked runtime metadata is updated intentionally with [scripts/register_ffmpeg_runtime.py](../scripts/register_ffmpeg_runtime.py).

- Validate a bundle against the tracked lock:
  - `python3 scripts/register_ffmpeg_runtime.py --platform mac --ffmpeg-path client/bin/mac/ffmpeg --ffprobe-path client/bin/mac/ffprobe`
- Update one platform entry deliberately:
  - `python3 scripts/register_ffmpeg_runtime.py --update --platform <linux|mac|win> --ffmpeg-path <path> --ffprobe-path <path>`

Builders refuse binaries that do not match the checked-in platform lock. Candidate
builds reject `ENCODINGDB_REGISTER_RUNTIME=1`; registration is permitted only with
explicit development `ENCODINGDB_BUILD_ONLY=1`. The CI `runtime_lock_evidence`
dispatch mode probes proposed locks and retains them separately, without building
or certifying a candidate. Review and commit proposed entries before running
normal locked candidate builds.

Each builder creates an isolated virtual environment from the directly pinned `client/requirements-build.txt`, so a global or ambient PyInstaller version cannot change the release artifact.

Supported builder overrides:

- `ENCODINGDB_RUNTIME_BUNDLE_DIR`
- `ENCODINGDB_FFMPEG_PATH`
- `ENCODINGDB_FFPROBE_PATH`
- `ENCODINGDB_RUNTIME_LOCK_PATH`
- `ENCODINGDB_REGISTER_RUNTIME=1` (intentional development registration with build-only mode)
- `ENCODINGDB_BUILD_ONLY=1` (native CI validation before a project version is assigned; skips final release sidecars only)

## CI provisioning

Runtime-lock-sensitive CI does not rely on ambient `apt`, `brew`, or `choco` FFmpeg packages, because those runner packages do not consistently expose the required `xpsnr` filter.

- Linux and Windows use the immutable BtbN `autobuild-2026-09-09-14-51`
  FFmpeg `n8.1.2-51-g7ba069f4f1` GPL archives, checked against pinned upstream
  SHA256 digests. Platform identities were generated on native runners in
  [CI run 34419226010](https://github.com/oliverdougherC/Encoding_Database/actions/runs/34419226010),
  then reviewed into the committed lock. A proposed lock is not a packaged build.
- macOS uses Evermeet `126386-gc27482a18d7`, containing libvmaf `3.2.0-13`.
  Original ZIP signatures were verified against the provider's HTTPS-published
  signing key (`20F6EA3E0CFD6B4C53447A73476C4B611A660874`). The exact binaries,
  original signed ZIPs, GPL text, provenance, and actual model-execution evidence
  are retained in the [candidate runtime archive](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/encodingdb-macos-runtime-c27482a18d7.tar.gz),
  SHA256 `0b7534979f2f073d9eddae6f92def32fb6063c50bb4aced75f7e88ecf0611687`.
  This is a nonproduction staging prerelease, not final application publication.

Normal native CI materializes the frozen suite, verifies the committed runtime
lock, builds the assigned candidate version, and retains binaries, suite pack,
notices, and full sidecars for 90 days. The separate manual proposal mode cannot
substitute for those candidate gates.

A compiled `libvmaf` filter does not prove compatibility with the pinned model.
The previous macOS `121420-gce9d181444` runtime failed to initialize the model's
CAMBI feature extractor. The replacement executed the unchanged model
`vmaf_v1.0.16_3d0h.json` against the actual 240-frame screen reference and its
libx264 CRF20 encode: exit 0, all frames analyzed, VMAF mean 86.904001. The archive
contains the exact command, JSON metrics and signature logs. This verifies that
specific model/runtime execution; final seven-reference validation and packaged
client/server acceptance remain separately required.

## Release sidecars

Each packaged client artifact now emits sibling sidecars:

- `encodingdb-test-suite-v1.tar.gz`
- `<artifact>.runtime-lock.json`
- `<artifact>.release-manifest.json`
- `<artifact>.signing.json`
- `<artifact>.smoke.json`
- `<artifact>.SHA256SUMS`

PyInstaller bundles `manifest.json`, `finalization-status.json`, optional `suite-lock.json`, and `suite-pack.json`, but it does not embed `canonical/` media. The external suite pack is hashed in the release manifest and in `SHA256SUMS`, and smoke runs point the packaged client at that exact archive.

The release manifest is deterministic and records:

- project version
- benchmark protocol version
- canonical minimum client version
- suite version and frozen/unfrozen status
- VMAF model identity
- runtime lock fingerprint
- artifact hash and size
- honest signing status

## Smoke coverage

The release helper runs:

1. `<artifact> --help`
2. `<artifact> --codec <locked encoder> --presets fast --crf 24 --no-submit`

Smoke evidence is intentionally no-submit and uses isolated queue/cache directories plus a dead-end backend URL.

Windows GUI builds are packaged and hashed, but smoke coverage is honestly marked as skipped; the Windows console build is the smoke-tested executable.

Native candidate validation runs on Linux, macOS, and Windows using the verified archive and committed runtime lock. Proposed runtime registration and candidate build evidence are retained separately.
