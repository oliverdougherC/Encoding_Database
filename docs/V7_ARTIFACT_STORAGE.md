# PL-v7 artifact storage and retention contract

PL-v7 public evidence is derived only from server-retained encoded artifacts. Client-computed quality values are diagnostic and cannot become canonical `QualityAnalysis` or `DerivedResult` evidence.

## Object lifecycle

1. `POST /v7/artifacts/initiate` reserves an immutable object identity from the run, artifact kind, byte length, and SHA-256 digest.
2. Upload bytes are written to a staging file on the configured artifact filesystem. The service hashes and sizes the completed staging object before an atomic rename into the durable object path. A process crash can leave an unreferenced staging file, but never a partially published object.
3. `POST /v7/artifacts/:id/complete` accepts only bytes matching the reservation and transitions the database record to retained evidence. Duplicate completion is idempotent; conflicting bytes are rejected.
4. Authoritative analysis reads the retained object and server-owned reference source, persists an immutable `QualityAnalysis`, and recomputes exact `DerivedResultMember` membership.
5. Reanalysis appends a new immutable analysis identity when the worker or metric context changes. It never overwrites the analysis used by an existing derivation.

## Retention policy

The clean-slate v7 epoch is retain-all by default. Encoded artifacts, their hashes, authoritative analyses, run validity evidence, and derivation membership are retained indefinitely while they support a public or provisional result. No automated deletion job is enabled.

An operator may delete only an unreferenced abandoned staging object after confirming that it has no `Artifact` row and no active upload job. Canonical objects referenced by an accepted, suspect, rejected, or invalid run must not be deleted. A future deletion policy must first add an explicit tombstone with actor, reason, timestamp, object hash, and affected derivations, then withdraw and recompute every dependent public result.

## Deployment and recovery

- Production uses the `artifact-data` Docker volume mounted at the configured storage root. The application must not use an ephemeral container layer for canonical objects.
- Database and artifact-volume backups are one recovery unit. Restore validation must confirm every retained `Artifact.sha256` and byte length before analytics are published.
- Create that unit with `DATABASE_URL=... ARTIFACT_STORAGE_ROOT=... scripts/v7-backup.sh OUTPUT_DIR`. The command exports a custom-format PostgreSQL dump, the complete artifact tree, an exact retained-Artifact/DerivedResultMember inventory, and a non-self-referential SHA-256 manifest.
- Validate recovery with `scripts/v7-restore-drill.sh OUTPUT_DIR`. The drill verifies the bundle hashes, restores into an isolated disposable PostgreSQL 16 container and temporary artifact root, then checks the restored database inventory and every retained object's byte length and SHA-256. It never drops or writes to the source database.
- The upload secret is required in production. Object keys are server-generated; client paths are never trusted.
- Operators should alert on queued uploads older than the normal client retry window, failed checksum validation, analysis failures, orphan staging files, missing retained objects, and a `DerivedResultMember` whose selected analysis or artifact cannot be resolved.
- `GET /health/v7-evidence` implements that alert surface. It returns HTTP 503 with stable reason codes for stale pending uploads/analyses, failed analyses, stale staging entries, missing retained objects, or unresolved selected-analysis membership. It also reports artifact/analysis state counts and server-analysis latency p50/p95. Alert thresholds are configurable with `V7_PENDING_UPLOAD_ALERT_SECONDS`, `V7_PENDING_ANALYSIS_ALERT_SECONDS`, and `V7_ORPHAN_STAGING_ALERT_SECONDS`.

## Reproducibility guarantee

The database stores the artifact digest, container and elementary-video byte counts, measurement duration and method, authoritative worker/model context, exact selected analysis IDs, recipe/environment fingerprints, and score context. Given the retained object plus frozen server resources, recomputation must reproduce the selected evidence set and score inputs without accepting client quality calculations.
