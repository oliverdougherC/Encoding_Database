# PL v7 calibration evidence

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
  range evaluations;
- an affirmative top-result review for every tested encoder and hardware
  family;
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

Remove `--allow-draft` for the production gate. The command exits nonzero until
the document is `COMPLETE` and every acceptance requirement passes.

Retained database evidence produces a `TEST_ONLY_PROVISIONAL` reference
context by default. Production promotion is a separate fail-closed operation:

```bash
DATABASE_URL='postgresql://…' node scripts/generate-reference-context.mjs \
  unused.json server/config/reference-contexts/production-v7.json \
  --benchmark-protocol-id '<immutable protocol id>' \
  --benchmark-protocol-version '7.0' \
  --source-suite-version 'encodingdb-test-suite-v1' \
  --quality-model-id 'vmaf-v1-sdr-1080p' \
  --context-version '<frozen context version>' \
  --calibration-evidence 'server/config/calibration/<complete review>.json'
```

The command rejects draft, hash-mismatched, incomplete, or context-incompatible
calibration evidence. The freeze record must name the exact promoted context
hash, binding production activation to the reviewed corpus and decisions.

## Current retained Apple pilot

`server/config/calibration/pla-87-apple-m4-pro-pilot-2026-08-12.draft.json`
was generated from the retained authoritative pilot beginning
`2026-08-12T09:10:00Z`. Its evidence hash is
`c9b128b6b23a7628889e4c812000bd756e40d8f5bb09e82f36eba432cd03c489`.

It binds 96 exact analyses across all seven canonical classes, libx264,
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

The first finite matrix is `server/config/calibration/final1080p-corrected-timing.matrix-v1.json`.
Its 252 recipe/workload cells are PREDECLARED_UNEXECUTED, not measured calibration.
Candidate hosts are Mac and P910; physical IDs remain null until real corrected
runs identify them. Two sessions assess repeatability; only persistent physical
source pseudonyms establish machine corroboration. Single-source hardware families
remain provisional wherever the reviewed policy requires more sources.
4K/HDR/HFR transfer is outside this proposed validated scope.

Each fold names `fittingEvidenceIds`, `evidenceIds`, `frontierEvidenceIds`,
`fittedContextHash` and `fittedContextArtifactPath`. Hardware/encoder/content/native-RC
groups must be disjoint within the fold; four labels on one generic set cannot pass.
The independently fitted context must contain exactly the declared measurements.
Content transfer also predeclares `referenceWorkloadByEvidenceId`, selecting a
fitting-only reference for unseen workloads. A held-out scene cannot fit its own
frontier. Licensed-master source-frame ranges still require assignment and visual
inspection before longer-scene collection; different hashes/crops do not prove
scene independence.

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
exact analysis. Production PL Fit ranking must reproduce every accepted golden
choice and recorded holdout prediction using each independently fitted context.

The same embedded policy drives activation, online/background rebuilds and reload
after restart. Missing configuration remains PROVISIONAL_UNCALIBRATED; configured
mismatch fails closed. Docker already copies JSON into `/app/config` and compiled
code into `/app/dist`. Set `PL_V7_REFERENCE_CONTEXT_PATH` to its deployed path.

Bounded software cell using the implemented client interface:

```sh
python -m client --codec libx264 --presets fast --crf 23 --v7-suite-clip athletic-action-1080p24-final --no-submit
python -m client --resume-campaign '<completed campaign ID>' --submit
```

`--campaign full` replaces the clip selector to run the same recipe on all seven
clips. `--upload-only` retries queued bytes. Hardware VBR uses
`--target-bitrate-kbps`; implementations must be available exactly as named.
Generators cannot fill review identities, preferences, approvals or measured data.
