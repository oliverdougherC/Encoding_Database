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

Builders normally refuse binaries that do not match the checked-in platform lock. For the one intentional registration build on a clean checkout, set `ENCODINGDB_REGISTER_RUNTIME=1`; the builder probes capabilities, writes that platform's exact identity into the lock, and then packages the filtered entry. Review and commit the lock change before release. Subsequent builds omit the flag and must match it exactly.

CI and native build validation can point the builders at a temporary lock path with `ENCODINGDB_RUNTIME_LOCK_PATH=<path>`. That keeps cross-platform registration/build tests deterministic without mutating the checked-in manifest.

Each builder creates an isolated virtual environment from the directly pinned `client/requirements-build.txt`, so a global or ambient PyInstaller version cannot change the release artifact.

Supported builder overrides:

- `ENCODINGDB_RUNTIME_BUNDLE_DIR`
- `ENCODINGDB_FFMPEG_PATH`
- `ENCODINGDB_FFPROBE_PATH`
- `ENCODINGDB_RUNTIME_LOCK_PATH`
- `ENCODINGDB_REGISTER_RUNTIME=1` (intentional first registration only)

## CI provisioning

Runtime-lock-sensitive CI does not rely on ambient `apt`, `brew`, or `choco` FFmpeg packages, because those runner packages do not consistently expose the required `xpsnr` filter.

- Linux and Windows CI use pinned BtbN FFmpeg 8.1 GPL archives with published SHA-256 verification before extraction.
- macOS CI downloads the current Evermeet snapshot, verifies the detached GPG signatures with Evermeet's published signing key, and then uses that verified runtime for temporary-lock registration/build validation.

Those CI jobs validate the build path with a controlled operator-supplied fixture. They do not rewrite the checked-in runtime lock unless a maintainer intentionally runs registration and commits the resulting lock change.

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

Native build validation is exercised in CI on Linux, macOS, and Windows by provisioning a verified FFmpeg bundle on the runner, registering that runtime into a temporary lock, and running the platform build script end-to-end.
