# PL v7 calibration evidence

**Status: BLOCKED for validated PL.** Candidate `1.3.0-rc.1` uses
`client/0.3.0` and corrected measurement protocol `7.1`; the published release
remains 1.2.0. Fresh measurement, genuine knowledgeable review and approved
production activation are still required. Completing collection readiness alone
does not close PLA-70.

PLA-87 is a production-freeze gate, not a request to tune constants against any
available rows. Calibration evidence uses the versioned
`pl-v7-calibration-evidence/v1` contract implemented in
`server/src/v7/calibration.ts`.

The contract binds every observation to its immutable benchmark run, encoded
artifact hash, exact quality analysis, recipe fingerprint, environment
fingerprint, machine source, workload, and native rate-control settings. It
also keeps calibration and holdout partitions explicit and disjoint.

## Required reviews

A production-ready document must contain all of the following:

- at least one reviewed pair/triple decision for Balanced, Quality, Storage,
  and Realtime;
- a named knowledgeable reviewer, relevant expertise, timestamp, selected
  candidate, and substantive rationale for every decision;
- disjoint held-out hardware-family, encoder-family, content-class, and recipe-
  range evaluations, each comparing at least two distinct native recipe choices
  on one workload and exact environment cohort;
- an affirmative top-result review for every tested encoder and hardware
  family, bound to its scenario, complete compatible candidate set and actual
  production ranking;
- explicit review of disagreement, grain/noise, dark/gradient, and localized-
  tail cases, including every `SUSPECT` observation;
- multiple independent machine sources, multiple real hardware families, the
  required software implementations, every suite-v1 class, and enough native
  rate-control/preset points to establish each rate-quality curve;
- the final checked-in production reference-context path/hash, calibrated
  evidence-policy version, transparent constants, and rationale.

For COMPLETE evidence the review hash covers corpus, review/fold decisions,
the exact evidence policy, transform constants and scoringBehaviorHash.
The latter hashes the deployed scoring module closure (scorer, PL Fit, aggregation, reference
construction, persistence, review eligibility and calibration validation), including fixed
weights, quality-tail blend and constraints. Final context path/hash and freeze
metadata are excluded to avoid a circular digest. Historical DRAFT hashes retain
their original interpretation. The canonical evidence hash then covers
the whole document except itself. Any edit after reviewer sign-off invalidates
one or both hashes. A `DRAFT`
document is never production-ready even if its other fields are complete.
An observation retained as `SUSPECT` may contribute to rate-quality coverage
only after a knowledgeable metric-sanity review marks it `EXPECTED`; merely
recording or retaining a suspect run never makes it calibration-eligible.

## Reproducible commands

Build the server first, then generate a draft directly from retained
PostgreSQL evidence:

```bash
cd server
npm run build
cd ..
DATABASE_URL='postgresql://…' node scripts/generate-calibration-evidence.mjs \
  --benchmark-protocol-id '<immutable protocol id>' \
  --quality-model-id 'vmaf-v1-sdr-1080p' \
  --calibration-version '<version>' \
  --since '<pilot start ISO timestamp>' \
  --output '<new draft.json>'
```

Generation is create-only and fails if the output already exists. Its
`generatedAt` value is derived from the newest retained evidence timestamp, so
the same database snapshot produces the same canonical payload and hash.

Validate without permitting a freeze:

```bash
node scripts/validate-calibration-evidence.mjs '<draft.json>' --allow-draft
```

Remove `--allow-draft` for the document gate. The command exits nonzero until
the document is `COMPLETE` and its semantic/hash requirements pass. It does not
replace live DB/object verification, executed rankings, genuine reviewer judgments
or production approval.

After assigning the fitting membership explicitly, generate a provisional
reference context from those retained canonical rows:

```bash
DATABASE_URL='postgresql://…' node scripts/generate-reference-context.mjs \
  unused.json server/config/reference-contexts/candidate-v7.json \
  --benchmark-protocol-id '<immutable protocol id>' \
  --benchmark-protocol-version '7.1' \
  --source-suite-version 'encodingdb-test-suite-v1' \
  --quality-model-id 'vmaf-v1-sdr-1080p' \
  --context-version '<frozen context version>' \
  --calibration-evidence 'server/config/calibration/<partitioned draft>.json'
```

Without `--promote`, generation leaves the context `TEST_ONLY_PROVISIONAL`;
a partitioned draft does not authorize public scoring. After genuine review,
[activation](PL_V7_PRODUCTION_ACTIVATION.md) requires COMPLETE evidence and live
DB/object verification. First promotion requires a new `--promoted-context-output`
before any database writes. The freeze record must name the exact promoted context
hash, binding activation to the reviewed corpus and decisions. Reactivation repeats
those evidence checks; recomputing JSON hashes does not manufacture approval.

## Historical Apple pilot — not final-suite calibration

`server/config/calibration/pla-87-apple-m4-pro-pilot-2026-08-12.draft.json`
was generated from the retained authoritative pilot beginning
`2026-08-12T09:10:00Z`. Its evidence hash is
`c9b128b6b23a7628889e4c812000bd756e40d8f5bb09e82f36eba432cd03c489`.

This pilot used the older synthetic 540p suite and SD model. It is not evidence
that the final 1080p suite is calibrated, and its rows must never be relabeled as
final-suite measurements. It binds 96 exact analyses across seven classes, libx264,
libx265, and VideoToolbox. Eighteen observations are deliberately retained as
`SUSPECT`. The validator reports one machine source, one hardware family, no
holdout partition, no human decisions/reviews, missing SVT-AV1, incomplete
rate-quality coverage, and no freeze record. Those are release blockers, not
fields that automation may fill with guesses.

The authoritative artifacts remain in the retained `encodingdb_e2e` database
and object-storage volumes. Per-path certificates, retry recovery, and
reanalysis evidence remain under `.test-reports/pl-v7-e2e/` on the evidence
host. Do not delete those volumes or promote this draft as a production score
context.

## Corrected-protocol semantic gate (PLA-550/556/557)

The finite [canonical matrix](../server/config/calibration/final1080p-corrected-timing.matrix-v1.json)
contains 252 recipe/workload cells. Replicating software cells on both declared
physical sources and running two timing sessions expands it to **840 host
cell/sessions**: 392 on Mac and 448 on P910. The full matrix remains unexecuted;
[runner rehearsals](collection-readiness/matrix-runner.md) are orchestration tests,
not measured calibration. Multiple campaigns/sessions on one installation do not
establish another physical source.

Source acquisition and freeze of the public suite are complete. The longer-source
[readiness receipt](collection-readiness/holdouts/source-readiness.json) also confirms
seven separate 30-second references, 5,040 frames total, with exact decode/hash and
cadence checks. Their registry hash is
`023d5490161da7c22d0534b7af968630ffaa8fb263b864c7270a7cbee9c5df76`.
The fresh 42-cell longer-scene measurement run is underway at this handoff snapshot;
its executed IDs/results and human decisions must be attached before any readiness
claim. Source preparation and AI contact-sheet inspection do not establish perceptual
approval, transfer validity or calibrated PL.

Validation scope is 1920×1080, 24 fps SDR BT.709. 4K, HDR, HFR, unseen-content transfer
and canonical decode/Playback Fit are outside this release's validated scope.
Single-source hardware families remain provisional wherever the reviewed policy
requires independent corroboration.

Each fold names `fittingEvidenceIds`, `evidenceIds`, `frontierEvidenceIds`,
`fittedContextHash` and `fittedContextArtifactPath`. Hardware/encoder/content/native-RC
groups must be disjoint within the fold; four labels on one generic set cannot pass.
The independently fitted context must contain exactly the declared measurements.
Content transfer also predeclares `referenceWorkloadByEvidenceId`, selecting a
fitting-only reference for unseen workloads. A held-out scene cannot fit its own
frontier. Licensed-master source-frame ranges and scene/source groups are now recorded in
[the source-fold manifests](collection-readiness/holdouts/source-fold-manifests-v1.json).
A scene-disjoint claim excludes the declared scene; a master-disjoint claim excludes
that entire source, including its other content classes. Verify the actual fitting
IDs against those assignments. Different hashes/crops alone do not prove independence.

Reference generation requires `--calibration-evidence` and uses only its explicit
CALIBRATION analysis IDs. It produces a provisional artifact; `--promote` requests
fully validated promotion. Distinct native RC points must exist within each preset.
Empty fitting sets/reviews, wrong-family top reviews, unresolved investigations,
excluded frontier members and relabeled synthetic samples fail closed.

Freeze records embed `evidencePolicy`, `evidencePolicyHash`, `scoringBehaviorHash`.
Use `buildScoringBehaviorHash()` from compiled recommendationPolicy, calculate
reviewHash, then `calculateProductionReferenceContextHash(context, version,
reviewHash, freeze)`, then evidenceHash. Hash calculation never confers review.

Both activation and reactivation require COMPLETE evidence and live PostgreSQL/
artifact access. Verification compares actual analysis/run/artifact IDs, physical
source, native RC, model/worker identity, current review head and measurements,
then streams every retained object's size and SHA-256. Corrected scope requires
protocol 7.1 and `ffmpeg-process-v1`. Operator adjudications apply only to their
exact analysis. Latest analysis selection uses immutable creation order; reviewing
an old analysis cannot supersede a newer pending, failed, rejected or suspect one. Production PL Fit ranking must reproduce every accepted golden
choice and recorded holdout prediction using each independently fitted context.

The same embedded policy drives activation, online/background rebuilds and reload
after restart. Missing configuration remains PROVISIONAL_UNCALIBRATED; configured
mismatch fails closed. Docker already copies JSON into `/app/config` and compiled
code into `/app/dist`. Set `PL_V7_REFERENCE_CONTEXT_PATH` to its deployed path.

Canonical and validation-only observations may originate in separate isolated
databases. The [combined-evidence workflow](collection-readiness/holdouts/combined-evidence/README.md)
seals selected identities and objects, imports them into an isolated review database,
and verifies that corpus through a read-only activation binding. Its PostgreSQL
rehearsal is completed; its synthetic fixtures are not calibration observations.
Registered validation-only sources retain their own namespace/hash and may appear
only in HOLDOUT. They never become public canonical uploads or fitting references.

Bounded software cell using the implemented client interface and local staging:

```sh
python -m client --base-url http://127.0.0.1:3001 --codec libx264 --presets fast --crf 23 --v7-suite-clip athletic-action-1080p24-final --no-submit
python -m client --base-url http://127.0.0.1:3001 --resume-campaign '<completed campaign ID>' --submit
```

`--campaign full` replaces the clip selector to run the same recipe on all seven
clips. `--upload-only` retries queued bytes. Hardware VBR uses
`--target-bitrate-kbps`; implementations must be available exactly as named.
Generators cannot fill review identities, preferences, approvals or measured data.
