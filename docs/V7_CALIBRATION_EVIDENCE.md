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

The review hash covers the retained corpus and all review/holdout decisions but
not the final freeze record, so a candidate production context can bind that
review hash without a circular digest. The canonical evidence hash then covers
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
  --quality-model-id 'vmaf-v1-sdr-sd' \
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
  --quality-model-id 'vmaf-v1-sdr-sd' \
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
