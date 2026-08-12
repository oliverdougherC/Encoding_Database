# Final Release Handoff

1. Supply exactly seven canonical videos and complete `client/resources/test_suite_v1/finalization-review.template.json` with truthful, reviewed provenance and license metadata.
2. Run:

   ```bash
   python3 scripts/finalize_test_suite_v1.py \
     --source-dir /absolute/path/to/final/videos \
     --review-json client/resources/test_suite_v1/finalization-review.template.json
   ```

3. Assign the official project version and release date in `release.json`, move the changelog entry out of `Unreleased`, and run `bash scripts/release_preflight.sh` until every gate passes.
4. Build native clients with the reviewed, lock-matched FFmpeg runtime bundles; sign/notarize when credentials are available; verify each release manifest and SHA256 checksum file.
5. Run `bash scripts/v7-backup.sh`, deploy, and run `scripts/production_smoke.sh` against the production API and frontend.
6. Run one real end-to-end V7 benchmark and confirm its immutable `BenchmarkRun`, retained `Artifact`, completed server `QualityAnalysis`, and public `/corpus` visibility.
7. Only then merge, tag the official version, create the GitHub release, and upload clients plus checksum/release manifests.

PL-v7 calibration is a later data activation operation documented separately in `docs/PL_V7_PRODUCTION_ACTIVATION.md`; it requires no application-code change.
