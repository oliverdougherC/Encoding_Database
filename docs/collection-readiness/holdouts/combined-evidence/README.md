# Combined calibration evidence rehearsal

Canonical collection and validation-only observations may originate in separate
staging databases. `scripts/calibration-evidence-snapshot.mjs` seals explicitly
selected run IDs and their protocol, source, recipe, environment, encoded objects,
analyses and reviewer history from a read-only PostgreSQL snapshot.

Import is restricted to a separate `encodingdb_calibration_*` database. It preserves
benchmark-run, artifact and quality-analysis IDs, measurement values, hashes,
statuses and review IDs. Semantically identical dimension rows may share their
fingerprint identity in the combined database; every foreign-key alias is recorded.
No fingerprint is rewritten. Conflicting contents or altered object bytes fail.
The source databases and original objects are unchanged. This is a selected
calibration-corpus transfer, not a replacement for a full production backup.

```sh
CALIBRATION_SOURCE_DATABASE_URL='<canonical staging URL>' node scripts/calibration-evidence-snapshot.mjs export --run-ids '<canonical run IDs.json>' --source-root '<canonical artifact root>' --output '<new snapshot-a>'
CALIBRATION_SOURCE_DATABASE_URL='<validation DB URL>' node scripts/calibration-evidence-snapshot.mjs export --run-ids '<holdout run IDs.json>' --source-root '<validation artifact root>' --output '<new snapshot-b>'
CALIBRATION_COMBINED_DATABASE_URL='<isolated encodingdb_calibration_* URL>' node scripts/calibration-evidence-snapshot.mjs import --snapshot '<snapshot-a>' --storage-root '<combined artifact root>'
CALIBRATION_COMBINED_DATABASE_URL='<same combined URL>' node scripts/calibration-evidence-snapshot.mjs import --snapshot '<snapshot-b>' --storage-root '<combined artifact root>'
DATABASE_URL='<same combined URL>' node scripts/generate-calibration-evidence.mjs --benchmark-protocol-ids '<combined protocol IDs.json>' --quality-model-id vmaf-v1-sdr-1080p --calibration-version '<version>' --output '<new draft.json>'
```

Exports default to 10 GiB of encoded objects; larger finite transfers require an
explicit `--max-bytes`. Protocol IDs for the combined generation come from the
import alias receipts. HOLDOUT sourceSuiteVersion/source SHA/registration hash
remain intact. Generated evidence is DRAFT and has no invented review decisions.
The combined database is the review/freeze workspace after transfer; synchronize
source snapshots before review, rather than silently editing a sealed snapshot.

## Read-only activation binding

After genuine COMPLETE calibration, activation can use the combined corpus while
writing only score contexts and derived results to its normal target database:

```sh
CALIBRATION_EVIDENCE_DATABASE_URL='<combined encodingdb_calibration_* URL>' \
CALIBRATION_EVIDENCE_STORAGE_ROOT='<combined artifact root>' \
VALIDATION_SOURCE_REGISTRY_PATH='<immutable source registry.json>' \
DATABASE_URL='<activation target URL>' \
node scripts/activate-pl-v7-production.mjs --benchmark-protocol-id '<target canonical protocol ID>' --reference-context '<candidate.json>' --calibration-evidence '<complete review.json>'
```

This is a dry run unless `--apply` is explicitly supplied. The evidence connection
uses a read-only repeatable-read transaction and holds the review coordination
lock through verification and the target transaction. Evidence and target database
names must differ in this mode; same-database activation uses the original unified
path. Only canonical target-protocol rows are recomputed; held-out observations
never become target recommendation rows or reference-fitting members. These
operator credentials do not belong in contribution clients.

## Executed rehearsal

A real three-database PostgreSQL 16 rehearsal exported two isolated fixture
namespaces, imported them into `encodingdb_calibration_rehearsal`, replayed the
import idempotently, generated a combined DRAFT, and checked exact run/artifact/
analysis IDs, hashes, fractional metrics, BigInt memory, SUSPECT state and an
INVESTIGATE review. Equivalent recipe/environment aliases were audited. Corrupt
snapshot objects and a write attempted inside the evidence read-only transaction
were rejected; original source rows remained unchanged.

The fixtures explicitly say TEST ONLY and are not video/calibration measurements
or human reviews. One integration test and 10 activation regressions passed without
skips. TAP receipts are alongside this document. No production data was copied,
modified, activated or promoted by this rehearsal.
