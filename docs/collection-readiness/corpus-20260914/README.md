# Corpus capacity and recovery evidence — 2026-09-14 UTC

The isolated metadata corpus met the predeclared **1,000 ms p95** target with 25 concurrent readers. This is PLA-558 read-path evidence; it does not certify production, native clients, encoded media, authoritative worker throughput, perceptual review or PL calibration.

## Accepted results

| Check | Source / result | Receipt |
| --- | --- | --- |
| Full server checks | `879de7143cad7689f0282fb705513481ec359733`; exit 0; 170 passed, 0 failed, 2 skipped | [server-tests.log](server-tests.log) |
| Explicit PostgreSQL corpus checks | Same SHA; exit 0; 2 passed, 0 skipped; 180 filter/sort pairs, exact medians/counts, review/revoke, immutable latest-analysis selection, concurrent snapshot and restart recovery | [postgres-tests.log](postgres-tests.log) |
| Grown corpus capacity | Same SHA, clean tracked source; exit 0; **100,622 runs / 7,004 groups; 25 readers; 100/100 requests; p95 138.01 ms; max 138.26 ms; peak Node RSS 182,140,928 bytes** | [report](grown-load/report.json), [actual PostgreSQL query plan](grown-load/query-plan.json) |
| Concurrent arrivals | Exit 0; **600 new atomic run/artifact/analysis chains in 600.69 s**; write p95 18.26 ms; accepted members in the target group 6 → 606; independent physical sources 3 → 3 | [report](arrivals/report.json), [exact 600 identity triples](arrivals/arrivals.jsonl) |
| Final reconciliation | Exit 0; **100,622 runs = 100,622 artifacts = 100,622 analyses = 100,622 public members**; 80,614 accepted + 20,008 suspect; no pending groups | [reconciliation](arrivals/reconciliation.json) |

The two normal-suite skips are the opt-in corpus PostgreSQL test and the parent-owned review PostgreSQL test. The corpus test was separately executed against a migrated PostgreSQL 16 database, as shown above. This bundle does not claim to execute the parent-owned review integration test.

Operations separately executed a **601-second two-surface probe** against this corpus service and the frontend proxy: 25 browsers, 124,737 requests, zero errors, corpus p95 32.28 ms and frontend proxy p95 38.00 ms, from 01:09:20 to 01:19:21 UTC. The arrivals ran approximately 01:10:24–01:20:25 UTC, overlapping most of that probe. The operations evidence bundle owns the raw HTTP receipt and host resource samples; this bundle owns the exact arrival and final membership records. They are distinct executed tests.

## Provenance correction

The sustained arrival driver started from `36f9442b7c9b9b3dc267d3e414a4d34b23598ec9`, using the already imported corpus implementation from `5bae5016da74f485e3018df23778238dbe49ecc5`, which also served the sustained HTTP probe. Its original report queried Git HEAD only at completion and therefore printed `f607d53915aca102c78aab11cc7cc9e26967156e` after this worktree advanced. **That printed SHA is not the execution-start SHA.** The driver file itself did not change during the run. The original report is preserved together with [execution-provenance.json](arrivals/execution-provenance.json). Commit `879de71` fixes future drivers to capture the source SHA before execution.

The later `c609a84` change makes a newer authoritative analysis shadow older reviewed evidence and preserves existing ILIKE filter semantics. It was verified with real PostgreSQL negative regressions. The sustained fixture has one analysis per run and no cross-worker review transitions, so it does not prove that semantic repair. The grown-corpus test and both archived test logs execute the final `879de71` source, including that repair.

## Executed commands and environment

Working directory: `/Users/ofhd/Developer/EncodingDB-worktrees/corpus`. PostgreSQL 16 ran in the isolated `encodingdb-release-pg` container on loopback port 55439. Databases `encodingdb_corpus` and `encodingdb_corpus_tests` were separate from the parent integration database. The application test process used a 30-connection Prisma pool. Connection passwords are excluded from this archive; `CORPUS_TEST_DATABASE_URL` and `DATABASE_URL` below refer to those explicitly isolated targets.

Commands all exited 0 unless listed under diagnostics:

```sh
npm --prefix server test
CORPUS_TEST_DATABASE_URL="$CORPUS_TEST_DATABASE_URL" node --test server/test/corpus-postgres.test.js

# Initial seed: 100,000 bulk metadata triples plus 20 small reference fixture triples.
CORPUS_TEST_DATABASE_URL="$CORPUS_TEST_DATABASE_URL" node server/scripts/corpus-scale.mjs .test-reports/corpus-scale

# Accepted initial durable backfill and bounded reader experiment.
CORPUS_SCALE_PREFIX=corpus-scale-1789346954183 CORPUS_TEST_DATABASE_URL="$CORPUS_TEST_DATABASE_URL" node server/scripts/corpus-scale.mjs .test-reports/corpus-scale-materialized

# Two preliminary arrivals, followed by the actual overlapping 600-second run.
CORPUS_SCALE_PREFIX=corpus-scale-1789346954183 CORPUS_TEST_DATABASE_URL="$CORPUS_TEST_DATABASE_URL" node server/scripts/corpus-arrivals.mjs 2 .test-reports/corpus-arrivals-smoke
CORPUS_SCALE_PREFIX=corpus-scale-1789346954183 CORPUS_TEST_DATABASE_URL="$CORPUS_TEST_DATABASE_URL" node server/scripts/corpus-arrivals.mjs 600 .test-reports/corpus-arrivals-sustained

# Exact final-source short load against all 100,622 rows.
CORPUS_SCALE_PREFIX=corpus-scale-1789346954183 CORPUS_TEST_DATABASE_URL="$CORPUS_TEST_DATABASE_URL" node server/scripts/corpus-scale.mjs .test-reports/corpus-scale-grown-final

# Executed full re-enqueue/backfill: ready, 2,612 ms; cooperating refresh processes also drained work.
DATABASE_URL="$DATABASE_URL" node server/scripts/rebuild-corpus.mjs --enqueue-all
```

The final reconciliation counted the target protocol's BenchmarkRun, Artifact and QualityAnalysis records, compared them with `sum(accepted + suspect)` in PublicCorpusGroup, and required an empty PublicCorpusDirtyGroup queue. The arrival driver additionally checks each inserted immutable identity triple and the exact before/after public group/source counts. It never writes production or claims synthetic objects are retained encoded pixels.

## Rejected approaches and limits

- [Per-request direct aggregation](diagnostics/direct-aggregation-timeouts.json) returned 98/100 successes, with two 15-second statement timeouts and p95 13.58 s.
- [Parallel query optimization](diagnostics/parallel-shared-memory-exhaustion.json) exhausted the isolated container's shared-memory allocation. Only four requests succeeded; this is a failure receipt.
- [Resource-bounded direct aggregation](diagnostics/direct-aggregation-slo-failure.json) returned 100/100 successes but p95 7.34 s, failing the unchanged one-second target.
- [Initial durable model/backfill](diagnostics/initial-durable-backfill.json) rebuilt 7,012 identities in 2.39 s and reached p95 178 ms. These development diagnostics report their base SHA with `sourceDirty: true`; they do not establish an exact clean executing commit. Final acceptance uses the clean final-source receipt above.

The final path stores rebuildable SQL summaries and transactionally queues changed identities. Requests refresh bounded dirty batches and hydrate at most 100 representative run/artifact/analysis records. Medians and membership hashes are computed inside PostgreSQL. Dirty backlog fails closed with recoverable 503/Retry-After; immutable evidence is not deleted. Queries use consistent snapshots, and the deployed background loop drains work independently of browser requests.

Deployment requires migration `20260914012000_corpus_groups`, a completed `server/scripts/rebuild-corpus.mjs --enqueue-all`, the `startPublicCorpusRefreshLoop` lifecycle hook, and `publicCorpusReadiness` in readiness checks. Run one reviewed read-model implementation version across deployed refreshers and perform backfill when its selection semantics change. The integrator owns final container/startup/production verification.

No 100,000-row fixture dump or synthetic media is included. The small arrival journal contains identity receipts only. All synthetic fixture protocols and artifacts remain isolated and are ineligible as production/calibration evidence. Hashes in `SHA256SUMS` cover this committed evidence bundle.
