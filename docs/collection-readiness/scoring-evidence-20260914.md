# Scoring implementation evidence — 2026-09-14

Implemented PLA-550/556/557 gates; this is not a validated PL activation receipt.

- `cd server && npx prisma generate && npm run build`: exit 0.
- Fresh isolated PostgreSQL 16 database `encodingdb_scoring`, local test container:
  `npx prisma migrate deploy`: all 25 migrations applied, exit 0.
- `CALIBRATION_TEST_DATABASE_URL=<isolated DB> REVIEW_TEST_DATABASE_URL=<isolated DB> node --test test/*.test.js`
  from server: 180 tests passed, zero failures/skips, exit 0. Full TAP retained beside
  this document. Real DB tests used synthetic test-only metadata/object bytes;
  they are never calibration evidence or production records.
- The DB/object negative test verifies a real retained object, then rejects altered
  VMAF, physical source, artifact identity, native RC and corrupt bytes.
- Canonical-media tests use existing hash-pinned resources via local ignored
  symlinks to the main workspace; no media changes were made.

The new finite matrix contains 252 explicit recipe/workload cells. It remains
PREDECLARED_UNEXECUTED. Corrected native experiments, independently fitted contexts,
longer disjoint source-frame assignments, actual knowledgeable reviews and approved
production activation remain required. Parent integrator owns hardware execution,
original talking-head playable packet and release/deployment evidence.

Missing configuration remains uncalibrated. Runtime calibrated JSON is embedded in
the hash-bound context and copied through the existing Docker `/app/config` path;
this lane did not build/deploy a final integrated container or invent a calibrated
policy. Physical IDs are pseudonyms, not Sybil-proof hardware attestation.
