# Final Release Handoff

This procedure separates a tested beta candidate from the later approved public
release. Steps 1–4 prepare deployment review; steps 5–9 require separate human
approval and production authority. The beta-readiness assignment stops after
step 4. A procedure or passing beta check is not evidence of production completion.

1. Acquire exactly seven actual canonical references, verify each asset's
   redistribution license and provenance, and retain the reproducible preparation
   recipe plus executed technical and visual validation. Complete
   `client/resources/test_suite_v1/finalization-review.template.json` truthfully,
   then freeze the matching client/server suite:

   ```bash
   python3 scripts/finalize_test_suite_v1.py \
     --source-dir /absolute/path/to/final/videos \
     --review-json client/resources/test_suite_v1/finalization-review.template.json
   ```

2. Assign the candidate's intended version and date in `release.json` and the
   matching changelog entry. These metadata values describe a staged candidate;
   they do not declare that a final public release has happened. Run
   `bash scripts/release_preflight.sh` with every gate, including `final-suite`,
   and retain its output. The normal CI pre-freeze sentinel alone is insufficient:
   it permits the intentional `FINAL_TEST_SUITE_NOT_FROZEN` failure.
3. Build native candidate clients with reviewed, lock-matched FFmpeg runtimes and
   the matching `encodingdb-test-suite-v1.tar.gz`; verify release manifests and
   SHA256 files. Record actual signing/notarization status and any remaining
   platform blockers. Stage binaries, the suite pack, checksums, licenses, and
   evidence at accessible durable locations. Execute clean-install acquisition
   and a real packaged-client seven-clip benchmark against an isolated stack.
   Confirm immutable `BenchmarkRun` records, retained `Artifact` bytes, completed
   authoritative server `QualityAnalysis`, database persistence, `/corpus`, and
   visible frontend results with PL explicitly unavailable/null. Retain actual
   commands, logs, run IDs, artifact identities, and visual evidence; synthetic
   fixtures or source-level tests cannot substitute for this acceptance run.
4. Integrate through the permitted PR/CI path into `beta`. Commit the deployment
   review report with the exact beta SHA, review PR, suite/protocol identities,
   candidate artifact locations and checksums, executed results, and specific
   unresolved blockers. Obtain human deployment-review approval. **Stop here for
   this assignment:** do not merge `beta` into `main`, publish a final production
   release, deploy production, or declare the evidence epoch.
5. After separate approval, merge the reviewed beta candidate into `main` through
   protected PR checks and required approvals. Record the resulting full main
   commit SHA and its relationship to the reviewed beta SHA. If the merge changes
   candidate content, repeat affected validation and obtain renewed review before
   proceeding. Never bypass protection or deploy an older main checkout.
6. Bind the final release artifacts to that reviewed main commit using the
   existing native build/release-manifest process. Rebuild and verify from the
   exact commit where necessary; never relabel beta artifacts as main builds.
   Verify suite identity, runtime locks, signing status, manifests, and SHA256
   checksums, then tag that exact main commit and publish the intended final
   GitHub release assets under the separately approved release process. Record
   the public tag, commit, URLs, and checksums. Candidate staging/version/date
   from steps 2–3 is distinct from this final publication.
7. Before deployment, create and verify the required database/artifact backup
   with `scripts/v7-backup.sh`, supplying `DATABASE_URL`, the actual artifact
   volume or storage root, and a new durable output directory as documented in
   `docs/PL_V7_PRODUCTION_ACTIVATION.md`. Retain backup identity and restore-drill
   evidence. On the production checkout, fetch `main`, verify that the approved
   full main SHA belongs to it, and check out that exact SHA with a clean worktree.
   Run `./deploy.sh --skip-pull` from that verified checkout and retain the full
   SHA before and after deployment. The default `./deploy.sh` pulls the latest
   `main`; it must not silently advance beyond the reviewed commit. `--skip-pull`
   only prevents that pull; it does not itself verify cleanliness or approval.
   The supported command provisions the isolated acquisition runtime, verifies
   and materializes the pinned final suite, builds application images and pulls
   service images before rollout. The host requires Git, Node.js 20+, Docker with
   Compose v2, registry/suite access and sufficient cache/staging/image space;
   it does not require a host Python/client or media runtime. To complete those
   preparation checks without changing services first, use
   `./deploy.sh --skip-pull --prepare-only`. See the README for verified offline
   pack/mirror and cache controls. Preparation failure must be resolved before
   rollout; never bypass the suite or Docker source/model checks.
8. Run `scripts/production_smoke.sh` against the actual production API/frontend,
   then complete a real packaged-client V7 benchmark using the published client
   and suite pack. Verify retained upload bytes, authoritative analysis,
   database persistence, `/corpus`, and frontend visibility. Record the deployed
   full SHA, release artifact checksum, run/artifact/analysis IDs, logs, and
   screenshots. Beta isolated-stack evidence does not replace this check;
   `scripts/certify-v7-e2e.sh` is beta-only and must not be reported as having
   certified production. Confirm incompatible clients cannot enter the canonical
   corpus and public PL remains explicitly unavailable/null.
9. Only after production acceptance, declare the clean V7 evidence epoch with
   the official release, exact deployed commit, protocol/suite identities, and
   first accepted V7 evidence timestamp. Only then may PLA-90 / PLA-70 be closed.

PL calibration/reference-context activation (PLA-87) and longer natural-content
holdouts (PLA-141) remain post-release. Neither blocks collecting valid unscored
V7 evidence, and neither is completed by canonical-source sanity checks. Follow
`docs/PL_V7_PRODUCTION_ACTIVATION.md` for later calibration activation; test-only
or synthetic score contexts must never become public PL evidence.
