# Collection readiness — 2026-09-20 (operations lane)

Checkpoint, not a release: no production deployment, no protected merge, no
public release. `READY FOR COLLECTION` is claimed nowhere; the remaining
verdict belongs to Oliver's quality review and root integration.

## Exact identities

| Item | Value |
| --- | --- |
| Application candidate | `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2` |
| Candidate Linux package | `3abd38ee72fa9f5a…` (matches plan; asserted at `pre:snapshot`) |
| Mac packaged executable | `443e293e82f0f042b2017f55d12f1d73c7d5b6944cb43d6c9d70281beef6d70c` |
| Published production client (old) | `037d2fa318027881d78af8b37dc042a93bd77d5917f203fc25e557cd3c3ead02` (client/0.2.0, protocol 7.0) |
| Production baseline | `b0f0bc7` — untouched throughout |
| Candidate | `/mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c`, project `encodingdb-candidate-730de3c`; native run root `20260920-native-b3ef24a` |
| Suite fingerprint | `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e` |

## Gates genuinely passed today (all receipts committed)

1. **Fault suite completed** (`faults/fault-results.json`): corrupt-pack exit 3 /
   zero attempts, SIGINT 130 / one retained record, SIGKILL −9 / two retained
   records, and the interrupted final recovery resumed from
   `faults/interrupt-resume/queue` — prior attempts preserved, orphans drained,
   zero task-owned media at handback.
2. **Publication gates over the real candidate**
   (`docs/operations/evidence/native-linux-b3ef24a/publication-results.json`):
   offline deferral, real pending-capacity admission **before** injected
   pressure, injected retry-after preservation, lost-response idempotent replay,
   full drain to zero pending uploads and zero PENDING analyses.
3. **Exact recorded-or-terminal membership, Linux** (38 prepared payloads): 31 DB
   runs each matching sha256, byte size, frame coverage and repetition index;
   12 terminal receipts covering every remaining attempt; zero ghosts; zero
   `DerivedResult` rows (PL inactive); every stored object sha/size-verified on
   disk. The 7 attempts without runs are real server rejections of out-of-order
   repeats (`"Measurement group completed receipt is immutable"` — replayed live
   via run-create to capture the body).
4. **Mac upload-only replay over SSH loopback TLS**
   (`docs/collection-readiness/mac-upload-b3ef24a/`): packaged 0.3.0 client, no
   overrides, certifi + public candidate CA. Software 7 uploaded / 11 terminal;
   VideoToolbox 10 uploaded / 4 terminal; sealed pre-upload ledgers unchanged
   byte-for-byte; recorded-or-terminal reconciliation exact (zero unaccounted,
   zero problems).
5. **Real old-protocol rejection** (`old-protocol-receipt.json`): candidate
   requires 7.1 / `client/0.3.0`; published 7.0 identities and the exact legacy
   `POST /submit` JSON contract are rejected with 400 + schema validation.
6. **Recovery** (`recovery-results.json`): production smoke passed against the
   trusted-TLS API and frontend origin (HTTP frontend honestly 301-redirects);
   container restart preserved run/artifact/member state byte-identically;
   paired `pg_dump` + retained-object tar restored into an isolated scratch
   database (14-table counts and payload-hash set matched, scratch dropped) and
   scratch directory (all 27 restored files sha256-matched the live volume);
   teardown restored the exact private pre-test compose (analysis concurrency 0)
  with digest assertion and stopped the fault proxy.

## Post-checkpoint repair and re-verification (same day)

After this checkpoint sealed, the Windows upload attempt exposed a real server
defect. All evidence below is in
`docs/operations/evidence/native-linux-b3ef24a/gopfix-results.json`
(phases: rollout, drain, verify, membership, restore).

1. **Defect and fix** (`3e6bb0846ec3f1b396c9c8de513a5e6b6a2ed3c8`, server):
   `validateProbeAgainstRun` bounded the maximum keyframe interval with
   `recipe.keyframeInterval ?? gopSize`, but for software recipes that column
   holds the *observed minimum* scene-cut gap — so ordinary scene-cut output
   was rejected at artifact upload (the 400s behind the Mac/Linux/Windows
   REJECTED artifacts). Injected-fault terminal entries and protocol rejections
   were separately audited as correct-by-design.
2. **Rollout**: fixed source built to `encodingdb-candidate-server:3e6bb08`
   (digest-verified private compose swap; protocol still 7.1, suite
   fingerprint unchanged). Candidate source is now `3e6bb08`, a b3ef24a-derived
   tree; the original `b3ef24a…730de3c` package/binary identities above are
   unchanged.
3. **Drain**: every UPLOADED artifact left from the defect era completed
   analysis afterwards — final states VERIFIED 61 / RETAINED 47 / REJECTED 9
   (tombstones retained), zero open.
4. **Fresh ordinary-path verification** (pre-declared seeds, packaged Linux
   binary, embedded-runtime receipts asserted against `ffmpeg-lock.json`): two
   full campaigns, 30 fresh artifacts, all VERIFIED/RETAINED with analyses
   COMPLETE/SUSPECT — real keyframe lists (e.g. animation `[0, 38, 152]`,
   athletic `[0, 39, 88, 117, 148, 178, 227]`) now accepted at upload; zero
   REJECTED among new contributions. Seven clips contributed (the campaign
   planner ignores `--v7-suite-clip` for attempt counting; both campaigns ran
   full 15-attempt plans).
5. **Exact recorded-or-terminal membership, post-rollout**: 117 DB runs, 108
   payload-proven identities (Linux software/nvenc + verify queues + Mac
   sealed payloads), 42 terminal receipts (12 Linux, 15 Mac 409-group-rejects
   newly sealed from the Mac queues, 7+7 Windows), sha/size/frame-coverage
   match on every payload-proven run, every stored object size+sha256-verified
   on disk, zero ghosts, zero unaccounted, zero open artifacts, zero
   `DerivedResult` rows. **Exception (honest gap):** the 35 Windows r3 rows are
   receipt-attested (r3 receipt: exit 0, dueUploadsAfter 0, byte-identical
   campaign dirs, per-campaign row counts 9/14/14, timestamps inside the r3
   window) but not payload-proven — the submission files live on the Windows
   host; `operations-windows-submissions-request.json` specifies the copy-only
   export that closes this mechanically.
6. **Old-protocol rejection re-probed against the fixed build**
   (`old-protocol-receipt.json`): protocol 7.1 / `client/0.3.0` required,
   legacy `POST /submit` still 400 with schema validation.
7. **Config restored** to the exact digest-asserted pre-gopfix private compose
   (image `3e6bb08` kept, analysis concurrency 0, pending max 500).
8. **REJECTED recontribution attempt** (integration demand, live client probe):
   the real packaged Mac client replayed the sealed REJECTED submissions
   through loopback TLS; the server idempotently fetched the old run, 409'd
   out-of-order repetitions, and refused mismatched bytes — final states
   byte-identical (117 runs; 61/47/9). Re-scoring those bytes would require an
   operator requeue that mutates sealed evidence; deferred to integration.
   Details and the sha-lead code audit: `rejected-recontribution-probe.json`.

## Honest observations (retained, not repaired, not hidden)

- Analysis tiers across the candidate (post-rollout): COMPLETE 48 / SUSPECT 60
  — SUSPECT is the server's own environment-telemetry verdict; Oliver decides
  usability.
- Terminal artifacts: REJECTED 9 (defect-era tombstones, retained honestly);
  RETAINED 47 keeps bytes for audit. The two Mac software attempts that
  recorded a run then hit `artifact upload rejected (400)` were downstream of
  the keyframe-interval defect fixed in `3e6bb08`; their bytes remain in each
  queue's `dead-letter/artifacts/` and the rows stay honestly incomplete —
  no re-encode was performed for them.
- First Mac driver invocation used `--resume-campaign --submit` without
  `--upload-only` (fell into the campaign-resume publication path). It uploaded
  the same ledger bytes with the same packaged binary — ledgers verified
  immutable and nothing re-encoded (artifact mtimes unchanged) — but the safe
  `--upload-only` path was then re-run idempotently and all receipts above
  reflect the corrected command.
- Out-of-order fault-resume repeats are legitimately unrecordable (receipt
  immutability). Both Linux (7) and Mac (4+11) queues show these as terminal
  receipts by design.
- `encodingdb-projection-synthetic-20260920` (capacity lane's scratch DB) is
  still running on P910; left untouched for its owning lane to reconcile.

## Remaining blockers (external, concrete)

1. **Windows submission export** (payload-level proof for the 35 Windows r3
   rows): copy-only export specified in
   `operations-windows-submissions-request.json`; membership re-runs in
   seconds once `windows-submissions-ready.json` lands. Rows are
   receipt-attested meanwhile.
2. **Oliver's review**: Mac 6 GPU-suspect groups, 2 unstable software groups,
   Linux unstable groups, and the SUSPECT analysis tier — none may be silently
   promoted to scored collection.
3. **Root integration**: candidate commits (operator harness + evidence +
   server fix `3e6bb08`) are local, unpushed; CI avoidance respected. The
   deployed candidate now runs the fixed server image `3e6bb08`; decide at
   integration whether the release cuts from it or rebases the fix.

## Actions reserved for explicit approval

- Publish candidate release artifacts (exact hashes above, plus the
  `3e6bb08` server build/image) and switch the public collection endpoint from
  the 1.2.0 assets to the 7.1 client.
- Rollback: restore legacy dump
  `20260913-release-1.2.0/legacy-final/database.dump`, redeploy
  `b0f0bc7` images (verified baseline), revert protocol ACTIVE row; retained
  candidate objects are additive and can be left in place.
- PL calibration phase (831 canonical / 28 hardware cells) stays inactive and
  provisional; not required for this collection release.
