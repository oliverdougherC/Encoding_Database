# EncodingDB Test Suite v1

EncodingDB Test Suite v1 is the canonical seven-class suite identity for PL Score v7 benchmark work. Today the repository ships a synthetic development suite under that identity so the client, server, and release tooling can be exercised before the reviewed final media exists.

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

## Current development suite

The checked-in suite assets are development-only fixtures generated from deterministic FFmpeg graphs. They exist to validate the V7 benchmark, ingest, and release pipeline without pretending the final reviewed source media has already been chosen.

## Current development provenance and license

The current development suite is fully project-generated. No third-party source media is redistributed in the checked-in development assets.

- Provenance: deterministic FFmpeg `lavfi` graphs checked into [client/resources/test_suite_v1/manifest.json](resources/test_suite_v1/manifest.json)
- Redistribution decision: generated masters are owned by the project and avoid external asset-license ambiguity
- License for the current generated development sources: `CC0-1.0`

Current repository status is explicit:

- Development status file: [client/resources/test_suite_v1/finalization-status.json](resources/test_suite_v1/finalization-status.json)
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

Packaged clients ship manifest/status metadata plus `suite-pack.json`. The canonical media travels as a separate SHA-locked `encodingdb-test-suite-v1.tar.gz` suite pack that lives beside the release executable, at `ENCODINGDB_SUITE_PACK_PATH`, or behind an explicit `ENCODINGDB_SUITE_PACK_URL`.

The client never benchmarks whatever bytes happen to be present. It verifies the suite-pack archive, extracts it atomically into the local cache, and then verifies each clip against the manifest before use.

- Cache root: `~/.cache/encodingdb/suite/encodingdb-test-suite-v1` by default
- Override: `ENCODINGDB_SUITE_CACHE_DIR`
- Suite pack override: `ENCODINGDB_SUITE_PACK_PATH`
- Suite pack download override: `ENCODINGDB_SUITE_PACK_URL`
- Quick clip override: `ENCODINGDB_QUICK_CLIP_ID`

## Build and verification

Use the helper script to regenerate or verify the materialized suite from the checked-in manifest:

```bash
python3 scripts/build_test_suite_v1.py --output-dir /tmp/encodingdb-suite-v1
```

This writes or reuses the declared clip filenames, then fails if any hash or ffprobe contract diverges from the manifest.

## Future final freeze

The final reviewed suite is a separate future state. It will replace the current synthetic development media only after seven real source clips are selected, reviewed, and frozen with approved metadata. Until then, do not describe the final suite as project-generated.

- Review template: [client/resources/test_suite_v1/finalization-review.template.json](resources/test_suite_v1/finalization-review.template.json)
- Freezer script: [scripts/finalize_test_suite_v1.py](../scripts/finalize_test_suite_v1.py)
- Drift checker: [scripts/test_suite_drift_check.py](../scripts/test_suite_drift_check.py)

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
- requires reviewed `expectedMedia` bounds/expectations for each clip and rejects sources that do not match them
- requires `reviewHash` to equal the deterministic SHA-256 of the canonical reviewed metadata payload
- resolves the seven reviewed files from `--source-dir` plus each clip `fileName`; `localPath` is optional and only overrides when explicitly set
- probes hashes, size, frame count, frame rate, color, progressive/interlace state, and HDR metadata with `ffprobe`
- copies canonical source assets into synchronized client/server `canonical/` destinations without mutating the reviewed originals
- regenerates synchronized `suite-pack.json` metadata bound to the canonical suite pack archive contract
- stages and validates all outputs as a unit, then atomically replaces manifest/status/lock outputs
- allows idempotent reruns
- does not transcode or modify the reviewed source files
