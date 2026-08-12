# EncodingDB Test Suite v1

EncodingDB Test Suite v1 is the canonical seven-class source suite for PL Score v7 benchmark work. It replaces the old assumption that one `sample.mp4` file could stand in for General PL coverage.

## Coverage

The suite declares one required clip for each normative content class:

- `high-motion-sports`
- `fine-natural-detail`
- `film-grain-noise`
- `dark-gradients-shadows`
- `animation-flat-fields`
- `screen-text`
- `talking-head`

General PL v7 requires complete declared coverage with equal-class weighting. A single-clip quick test remains available for local checks, but it is content-specific only and must never be labeled General PL.

## Provenance and license

Suite v1 is fully project-generated. No third-party source media is redistributed.

- Provenance: deterministic FFmpeg `lavfi` graphs checked into [client/resources/test_suite_v1/manifest.json](/Users/ofhd/Developer/Encoding_Database/client/resources/test_suite_v1/manifest.json)
- Redistribution decision: generated masters are owned by the project and avoid external asset-license ambiguity
- License for generated suite sources: `CC0-1.0`

## Manifest contract

Each clip entry carries:

- suite version and clip ID
- canonical content class and current payload compatibility class
- SHA-256 and byte size
- provenance and license
- exact frame count and duration rational
- frame-rate rational
- width and height
- pixel format, bit depth, and chroma subsampling
- color primaries, transfer, matrix, and range
- progressive/interlace state
- HDR metadata expectation

Client verification checks both hash and ffprobe-derived media properties before benchmark execution.

## Acquisition and cache

Packaged clients ship the manifest, not prebuilt media. The client materializes suite clips deterministically into a local cache using the bundled or configured FFmpeg binary, then verifies the resulting files against the manifest.

- Cache root: `~/.cache/encodingdb/suite/encodingdb-test-suite-v1` by default
- Override: `ENCODINGDB_SUITE_CACHE_DIR`
- Quick clip override: `ENCODINGDB_QUICK_CLIP_ID`

## Build and verification

Use the helper script to regenerate or verify the materialized suite from the checked-in manifest:

```bash
python3 scripts/build_test_suite_v1.py --output-dir /tmp/encodingdb-suite-v1
```

This writes or reuses the declared clip filenames, then fails if any hash or ffprobe contract diverges from the manifest.
