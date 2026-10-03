# PR #23 source correction wrap-up

F1–F4 are corrected in source; native acceptance remains open. The client is an
**unpublished client/0.3.9 / 1.3.0-rc.9 review candidate**. The PR remains draft.
No release, production deployment, merge or physical Medium run was performed.

Corrected source: `c797ef3e38c1d52e25758abf582215a2cb38bc3d`. Client Git tree: `af9a9a2da954b6cfce4e711e2f2d8956f0c473d7`.
The initial reviewed head was `73ede395c5ce7053a9c25d67c5d6371fa4a91117`;
its CI merge build was `f805c177d8eba1c98c91ac83e2fb4967ee0303e3`.
The commit containing this report adds documentation only to that corrected source.

## Corrections

- **F1:** retain the original shared publication lock until owned work finishes;
  remove the lossy lock conversion. Deterministic process handshakes cover both
  publisher finish orders and a competing collector while real socket I/O is held.
- **F2:** bounded barriers precede batch timing and each encode. Actual spool replay,
  create/auth/PUT/read/close traffic and normal CLI checkpoint continuation cannot
  overlap instrumented encode intervals; long work pauses with bytes and IDs retained.
- **F3:** owned metadata subprocesses bound DNS/connect/header/body work and observe
  Stop/Close. Compatibility fails closed; optional baseline failure permits useful
  contribution. Reconciliation reuses the same transport rather than a new thread.
- **F4:** validate local canonical identity, server run/artifact bindings and actual
  acknowledgment evidence before shortcuts or retirement. Corrupt evidence survives;
  historical markers need reconciliation. Analysis acceptance requires an ACCEPTED
  run and a COMPLETE analysis for that same run and artifact. Pending uploads and
  historical groups cannot appear as confirmed uploads.

## Executed verification

| Check | Result |
|---|---|
| Integrated client suite | 730 passed, 287.66 seconds |
| Server suite and TypeScript build | 237 passed, 6 existing environment-gated skips, 0 failures |
| Actual Linux publication regressions | reviewed source: 8 failed / 2 passed; corrected source: 10 passed |
| Additional F4 binding regressions | rejected draft: 9 failed; corrected acknowledgment suite: 51 passed |
| Final binding/progress checks | 16 passed |
| Final publication/version checks | 18 passed |
| Isolated clean-preparation import and deployment boundaries | 5 passed |
| Python 3.11 compilation / whitespace checks | passed |

The full 730-test run preceded the final version bump and the one-line historical
confirmed-group counter correction; the final focused checks cover those changes.
The Linux regressions execute complete imported production modules and real kernel
locks/loopback HTTP. Encodes and environment preparation use deterministic fixtures;
these results are **not native performance or online Medium acceptance**.

Commands:

```text
python3.11 -m pytest client/tests -q -p no:cacheprovider
cd server && npm test
python3.11 -m pytest client/tests/test_publication_quiescence.py client/tests/test_publication_transport_acceptance.py -v -p no:cacheprovider
python3.11 -m pytest client/tests/test_acknowledgment_binding.py client/tests/test_progress_review.py -q -p no:cacheprovider
python3.11 -m pytest client/tests/test_release_packaging.py client/tests/test_publication_quiescence.py client/tests/test_publication_transport_acceptance.py -q -p no:cacheprovider
```

[Machine-readable results and evidence hashes](regression-progress.json),
[client log](evidence/client-full.log), [server log](evidence/server-full.log),
[Linux before/after log](evidence/publication-linux-before-after.log),
[F4 before](evidence/receipt-before.json), [F4 after](evidence/receipt-after.json),
[binding before](evidence/binding-before.json), [binding after](evidence/binding-after.json),
[owned process traces](evidence/ownership-traces).
The additional F4 before run used the completed but rejected draft, not the initial
reviewed head. Its complete validator, fixture module, tracked-source patch and file
hash manifest are retained in `evidence/` so that provenance stays explicit.

The first final CI clean-deployment build exposed a missing acknowledgment module
in the minimal preparation container. Its COPY/context list is corrected; the
actual entry point fails with the prior declared inputs and passes with the new
ones in isolation. [Before](evidence/preparation-import-before.log),
[after](evidence/preparation-import-after.log). The complete CI rerun remains pending.

## Acceptance gaps

Final-source CI and all four exact candidate package hashes remain to be collected.
The physical Windows GUI/console, macOS app/Terminal and Linux full **ONLINE Medium**
matrix, final-package preparation/create/auth/PUT/read Stop/Close, server analysis
reconciliation and native same-ID replay with zero repeated completed encodes remain
unverified. Frozen Windows GUI metadata subprocess IPC also requires native proof.
Prior local-only runs had zero server receipts and do not close these gates.

The paired server code adds immutable acknowledgment fields. Before native online
acceptance, apply only those serializer additions to the isolated backend while
preserving its `3e6bb0846ec3f1b396c9c8de513a5e6b6a2ed3c8` keyframe correction,
existing volumes, quota, TLS and scientific settings. No backend rollout occurred.
The inherited Node dependency audit failure is not waived. Keep the PR draft until
applicable acceptance and audit blockers are resolved.

The final packaging fix additionally changes `scripts/suite-preparation.Dockerfile`,
its `.dockerignore`, and `client/tests/test_deployment_preparation.py`.

## Changed files

```text
CHANGELOG.md
README.md
client/acknowledgments.py
client/artifacts.py
client/campaign.py
client/main.py
client/recovery_projection.py
client/spool.py
client/tests/_publication_acceptance_support.py
client/tests/test_acknowledgment_binding.py
client/tests/test_acknowledgment_retirement.py
client/tests/test_artifact_cancellation.py
client/tests/test_artifacts.py
client/tests/test_campaign_durability.py
client/tests/test_measurement_budget.py
client/tests/test_progress_contract.py
client/tests/test_progress_review.py
client/tests/test_publication_quiescence.py
client/tests/test_publication_storage.py
client/tests/test_publication_transport_acceptance.py
client/tests/test_release_packaging.py
client/tests/test_reliability_recovery.py
client/tests/test_spool.py
release.json
server/src/v7/artifacts.ts
server/test/v7-artifacts.test.js
```
