# PL v7 production activation

This runbook is the fail-closed path for promoting a retained-evidence PL v7
reference context into production. It rejects draft calibration, refuses
test-only contexts, binds the activation to the reviewed calibration hash, and
keeps database persistence idempotent.

## Inputs

- a retained-evidence reference context generated from PostgreSQL evidence;
- a `COMPLETE` PLA-87 calibration document with a valid review hash and freeze
  record;
- a production `.env` file with explicit proxy/CORS/upload-secret values;
- the production benchmark protocol ID.

Do not point this workflow at
`server/config/calibration/pla-87-apple-m4-pro-pilot-2026-08-12.draft.json`.
That file is intentionally a draft and the activation command rejects it.

## 1. Dry-run activation

Build the server dist once, then run the activation command in dry-run mode:

```bash
cd server
npm run build
cd ..
DATABASE_URL='postgresql://…' node scripts/activate-pl-v7-production.mjs \
  --benchmark-protocol-id '<immutable protocol id>' \
  --reference-context 'server/config/reference-contexts/<retained-evidence context>.json' \
  --calibration-evidence 'server/config/calibration/<complete review>.json'
```

The command performs four checks before it would write anything:

- the reference context parses and remains hash-valid;
- the calibration is `COMPLETE`, hash-valid, and production-freeze ready;
- the promotion hash in the calibration freeze record matches the context that
  would be activated;
- the current database can recompute deterministic derived-result summaries from
  the retained authoritative analyses.

Dry-run is the default. It prints the activated context hash, score-context
seed count, retained-analysis count, recomputed derived-result count, and the
exact env bindings that production must carry.

## 2. Persist the production context and env snippet

When the dry run is clean, write the promoted context and env snippet:

```bash
DATABASE_URL='postgresql://…' node scripts/activate-pl-v7-production.mjs \
  --apply \
  --benchmark-protocol-id '<immutable protocol id>' \
  --reference-context 'server/config/reference-contexts/<retained-evidence context>.json' \
  --calibration-evidence 'server/config/calibration/<complete review>.json' \
  --promoted-context-output 'server/config/reference-contexts/production-v7.json' \
  --env-output '.env.production.pl-v7'
```

`--apply` persists the score-context rows with database upserts, so rerunning
the command is idempotent. It also recomputes and transactionally upserts the
matching `DerivedResult` and `DerivedResultMember` rows from the retained
authoritative analyses, so the activated score contexts and their public V7
corpus rows move together. The output files remain create-only: if they already
exist, remove them intentionally and rerun rather than silently overwriting.

Append the emitted env keys into the deployment `.env`:

- `PL_V7_REFERENCE_CONTEXT_PATH`
- `PL_V7_REFERENCE_CONTEXT_VERSION`
- `PL_V7_REFERENCE_BITRATES_JSON`
- `ALLOW_TEST_ONLY_REFERENCE_CONTEXTS=0`

Those values are hash-bound to the promoted context. Do not hand-edit them.

## 3. Validate env + deploy

Pre-deploy validation:

```bash
node scripts/validate-production-env.mjs \
  --env-file .env \
  --reference-context server/config/reference-contexts/production-v7.json
```

The validator fails if:

- the env references a non-production or mismatched context;
- `ALLOW_TEST_ONLY_REFERENCE_CONTEXTS=1`;
- `CORS_ORIGIN=*`;
- `TRUST_PROXY`, `ARTIFACT_UPLOAD_SECRET`, `APP_URL`, or `INTERNAL_API_BASE_URL`
  are unset;
- database credentials, public URLs, or the artifact signing secret are placeholder/unsafe values;
- V7 artifact size, storage reserve/quota, rate, backlog, lease, retry, or concurrency settings are invalid;
- `INGEST_MODE=signed` is selected without `INGEST_HMAC_SECRET`.

Deploy:

```bash
./deploy.sh
```

`deploy.sh` now runs the same env validator before `docker compose up`, then
checks all of the following after startup:

- direct DB connectivity from the production server container;
- API `/health/live`, `/health/ready`, `/health/v7-evidence`;
- API `/query`, `/test-videos`, and V7 `/corpus`;
- frontend homepage content;
- frontend `/api/corpus` proxy behavior.

## 4. Backup and isolated restore rehearsal

Production compose uses explicit Docker volume names:

- `encodingdb_prod_db_data`
- `encodingdb_prod_artifact_data`

Backup dry-run:

```bash
DATABASE_URL='postgresql://…' ARTIFACT_VOLUME_NAME=encodingdb_prod_artifact_data \
  scripts/v7-backup.sh --dry-run /tmp/encodingdb-v7-backup
```

Create the backup bundle:

```bash
DATABASE_URL='postgresql://…' ARTIFACT_VOLUME_NAME=encodingdb_prod_artifact_data \
  scripts/v7-backup.sh \
  --compose-file docker-compose.prod.yml \
  /secure/backups/encodingdb-v7-$(date +%Y%m%dT%H%M%S)
```

The backup script copies the named artifact volume into a temporary host staging
directory, validates every retained object against the database inventory, then
emits:

- `database.dump`
- `artifacts.tar.gz`
- `inventory.json`
- `SHA256SUMS`

When `--compose-file docker-compose.prod.yml` is used, the script quiesces the
configured writer services before the dump/inventory/archive window and restarts
them via an EXIT trap afterward. That is intentional downtime. Generic
filesystem-root backups do not auto-stop services unless compose-quiesce mode is
requested explicitly.

Restore-drill dry-run:

```bash
scripts/v7-restore-drill.sh --dry-run /secure/backups/<bundle-dir>
```

Isolated restore rehearsal:

```bash
scripts/v7-restore-drill.sh /secure/backups/<bundle-dir>
```

The drill verifies the manifest, restores into a disposable PostgreSQL 16
container plus temporary artifact root, and confirms retained artifact hashes,
byte lengths, and derived-result membership without touching the source system.

## 5. Pre-V7 migration rehearsal

Before the first release that depends on the full V7 schema chain, rehearse the
migration path from the last pre-V7 migration boundary:

```bash
scripts/v7-migration-rehearsal.sh --dry-run
scripts/v7-migration-rehearsal.sh
```

The rehearsal starts from the schema state at
`20260811060000_invalidate_reversed_vmaf`, inserts representative legacy
`Benchmark`/`Submission` rows, applies the V7 migrations in order, seeds a
representative V7 `DerivedResultMember` row before the exact-membership
migration, then boots the current server against the rehearsed database and
asserts:

- the legacy aggregate row survives;
- `DerivedResultMember.qualityAnalysisId` backfills to the authoritative
  analysis row;
- the exact-membership unique index exists.
- `/health/ready`, `/query`, and `/corpus` succeed against the rehearsed DB.
