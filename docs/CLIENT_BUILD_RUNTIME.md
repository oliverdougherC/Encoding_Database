# Client Build Runtime Contract

EncodingDB client packaging now treats FFmpeg and ffprobe as a locked runtime, not an ambient host dependency.

## Runtime lock

- Checked-in lock: [client/resources/runtime/ffmpeg-lock.json](/Users/ofhd/Developer/Encoding_Database/client/resources/runtime/ffmpeg-lock.json)
- Scope: pinned `ffmpeg` and `ffprobe` path identity, SHA-256, byte size, version line, build fingerprint, and required capabilities
- Required capabilities:
  - `ffprobe`
  - FFmpeg filters `libvmaf` and `xpsnr`
  - Required encoder surface for supported client flows

Platform builders package that lock resource and emit a release-specific runtime-lock sidecar for the exact bundled binaries they shipped.

## Operator workflow

Tracked runtime metadata is updated intentionally with [scripts/register_ffmpeg_runtime.py](/Users/ofhd/Developer/Encoding_Database/scripts/register_ffmpeg_runtime.py).

- Validate a bundle against the tracked lock:
  - `python3 scripts/register_ffmpeg_runtime.py --platform mac --ffmpeg-path client/bin/mac/ffmpeg --ffprobe-path client/bin/mac/ffprobe`
- Update one platform entry deliberately:
  - `python3 scripts/register_ffmpeg_runtime.py --update --platform <linux|mac|win> --ffmpeg-path <path> --ffprobe-path <path>`

Builders normally refuse binaries that do not match the checked-in platform lock. For the one intentional registration build on a clean checkout, set `ENCODINGDB_REGISTER_RUNTIME=1`; the builder probes capabilities, writes that platform's exact identity into the lock, and then packages the filtered entry. Review and commit the lock change before release. Subsequent builds omit the flag and must match it exactly.

Each builder creates an isolated virtual environment from the directly pinned `client/requirements-build.txt`, so a global or ambient PyInstaller version cannot change the release artifact.

Supported builder overrides:

- `ENCODINGDB_RUNTIME_BUNDLE_DIR`
- `ENCODINGDB_FFMPEG_PATH`
- `ENCODINGDB_FFPROBE_PATH`
- `ENCODINGDB_REGISTER_RUNTIME=1` (intentional first registration only)

## Release sidecars

Each packaged client artifact now emits sibling sidecars:

- `<artifact>.runtime-lock.json`
- `<artifact>.release-manifest.json`
- `<artifact>.signing.json`
- `<artifact>.smoke.json`
- `<artifact>.SHA256SUMS`

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
