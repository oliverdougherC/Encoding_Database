# EncodingDB canonical Test Suite v1

The deployment-review candidate replaces historical generated fixtures with seven reviewed references. [Source rights, preparation and limitations](../docs/canonical-suite/README.md) are part of this contract.

Launch scope: 1920×1080, 24 fps, progressive SDR BT.709 limited range, 8-bit 4:2:0 FFV1/Matroska, video only. Six clips are ten seconds; animation is eight seconds. Classes are high-motion-sports, fine-natural-detail, film-grain-noise, dark-gradients-shadows, animation-flat-fields, screen-text and talking-head. General PL requires complete equal-class coverage; PL remains unavailable until separately calibrated. Single-clip results never become General PL.

Final clip IDs and manifestVersion 2 bind actual hashes and an immutable lock, distinct from earlier v1 development fixtures. Do not mutate historical registered rows. The screen slot is an explicitly authored offline browser workflow, not a camera-recording requirement or renamed lavfi pattern. Other slots retain their third-party rights and disclosed source limitations.

## Obtain final media

Large media is retained in the external hash-pinned pack. With client dependencies and ffprobe installed, run from the repository root:

```sh
python3 scripts/materialize_final_suite.py
python3 scripts/verify_suite_assets.py client/resources/test_suite_v1
python3 scripts/test_suite_drift_check.py
```

The materializer verifies archive, metadata, notices and every reference, then installs matching client/server resources. Run it before native builds or Docker builds. Frozen references have no synthetic fallback; `build_test_suite_v1.py --rewrite-manifest` refuses a frozen suite.

Packaged clients obtain the archive beside the executable or through the manifest download URLs, with verified cache reuse and atomic extraction. Explicit overrides: `ENCODINGDB_SUITE_CACHE_DIR`, `ENCODINGDB_SUITE_PACK_PATH`, `ENCODINGDB_SUITE_PACK_URL`, and `ENCODINGDB_QUICK_CLIP_ID`.

Per-clip attributions, modification notices and license texts travel inside the pack and are hash-bound to its inventory. Third-party CC BY media is not relabeled CC0 or covered by Apache-2.0.

## Reproduce the freeze

After preparing the reviewed files with the committed tools:

```sh
python3 scripts/finalize_test_suite_v1.py \
  --review-json docs/canonical-suite/finalization-review.json \
  --source-dir .build/canonical-prepared \
  --notices-dir docs/canonical-suite/notices \
  --manifest-version 2
```

The finalizer probes/copies prepared files without transcoding, checks the review hash, rights, seven classes and expected media, and writes synchronized manifest/lock/status/pack metadata. Idempotent reruns are supported. Pin the retained candidate download URL afterward as documented in the deployment report. Human deployment approval remains separate.
