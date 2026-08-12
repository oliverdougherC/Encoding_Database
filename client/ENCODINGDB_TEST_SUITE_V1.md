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

Current repository status is explicit:

- Development status file: [client/resources/test_suite_v1/finalization-status.json](/Users/ofhd/Developer/Encoding_Database/client/resources/test_suite_v1/finalization-status.json)
- Current state: `development-only`, `isFrozen: false`
- There is intentionally no checked-in final `suite-lock.json` yet

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

The packaging verifier uses the same strict contract, not just byte hashes.

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

## Future final freeze

The final seven real source clips must be frozen with reviewed metadata, not by editing the current synthetic manifest by hand.

- Review template: [client/resources/test_suite_v1/finalization-review.template.json](/Users/ofhd/Developer/Encoding_Database/client/resources/test_suite_v1/finalization-review.template.json)
- Freezer script: [scripts/finalize_test_suite_v1.py](/Users/ofhd/Developer/Encoding_Database/scripts/finalize_test_suite_v1.py)
- Drift checker: [scripts/test_suite_drift_check.py](/Users/ofhd/Developer/Encoding_Database/scripts/test_suite_drift_check.py)

Operator path:

```bash
python3 scripts/finalize_test_suite_v1.py \
  --review-json /path/to/finalization-review.json \
  --source-dir /path/to/reviewed-suite-files
```

That invocation defaults client/server manifest, lock, and status outputs to the repository resource locations. The explicit output flags remain available for tests and nonstandard staging flows.

The finalizer:

- requires exactly seven reviewed logical classes
- accepts truthful provenance and license metadata, including operator-owned or `CC0-1.0` clips
- requires an explicit reviewed `distributionLicense`
- resolves the seven reviewed files from `--source-dir` plus each clip `fileName`; `localPath` is optional and only overrides when explicitly set
- probes hashes, size, frame count, frame rate, color, progressive/interlace state, and HDR metadata with `ffprobe`
- copies canonical source assets into synchronized client/server `canonical/` destinations without mutating the reviewed originals
- stages and validates all outputs as a unit, then atomically replaces manifest/status/lock outputs
- allows idempotent reruns
- does not transcode or modify the reviewed source files
