# F8 recovery correction and publication preparation — October 5, 2026

A missing or damaged artifact in one completed group could prevent unrelated intact groups from acquiring submission envelopes. The reverse ordering could create healthy envelopes but return before uploading them. Repeated Publish saved made no progress in the first ordering.

Reconstruction now validates and buffers new envelopes by complete recipe group. Per-record integrity/probe errors suppress the affected group and remain explicit; other valid groups continue. Publication drains newly reconstructed healthy envelopes before returning an honest non-success for unresolved evidence. Global manifest, client, runtime and protocol incompatibility still prevents reconstruction. No validation, measurement identity or receipt contract was relaxed.

## Executed source verification

- All eight primary regressions failed before the fix: missing/hash-mismatched artifact × group ordering × damaged member position.
- All 13 new regressions pass, including global-identity rejection, cancellation and envelope-write failure. An independent reviewer reran all 13 with separate test-lock storage.
- 66 affected recovery/integrity/locking tests pass, preserving F1–F7 coverage.
- The full client suite passes **761 tests**. An earlier concurrent run encountered the intended host exclusion while another reviewer tested; the isolated rerun passed without a product change.
- Imported production publication is invoked three times per primary case. Healthy work publishes exactly once in the first invocation, with original live-path payload hashes and run identities. Damaged evidence remains unchanged and visible, later replay is idempotent, and no encoding or source acquisition occurs.

Command: `ENCODINGDB_HOST_PHASE_DIR=<unique-test-directory> python -m pytest -q client/tests`.

The [verification receipt](source-verification.json) binds the tested files. These are source regressions, not execution of newly packaged binaries. Fresh rc.10 package verification and public publication are separate steps; earlier rc.9 native evidence is not relabeled.

## Release identity and deployment preservation

The new package/project version is **1.3.0-rc.10**. The unchanged measurement/runtime/protocol keeps **client/0.3.9** as its saved-journal identity, so existing journals remain reconstructable. New source revisions and exact executable hashes identify the recovery patch. No saved identity is rewritten to make it compatible.

Production uses existing bind-mounted database and artifact directories. The deployment guard now permits only preservation of the exact existing mount type, target and canonical source; named-volume protections remain. Six focused regressions and an independent security review pass, including refusal of empty, missing, changed or ambiguous storage. The new guard also passed read-only validation against the actual production topology. This does not by itself constitute a production rollout.

PL remains provisional under its existing scientific requirements. Publishing reliable collection software does not manufacture calibration evidence or expert approval.
