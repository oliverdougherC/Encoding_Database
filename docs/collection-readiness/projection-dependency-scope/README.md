# Bounded dependency-scope optimization

Production patch `e28a75f` changes only the reader's source of group keys: `DerivedResultGroupDependency` already contains the exact distinct physical-source/campaign/repetition-group triples written atomically with the published members. The reader uses those keys directly instead of reconstructing them through a `DerivedResultMember → BenchmarkRun` join on each request. It still hashes **every sibling row**, retains certificate **v3**, checks the same qualified membership and stored hash, and keeps the dependency invalidation fence before metric sorting and pagination. No gate, resource limit, score formula, migration or dependency changes.

The preserved earlier plan showed group-state certificates consuming about 131 of 153 ms, with 3,530 counted-run primary-key probes on one 25-row page. Candidate enrichment before LIMIT was about 10 ms. Delaying enrichment until after LIMIT for createdAt/hardware/sample sorts remains a reasonable separate opportunity, but cannot address this trial's fps/vmaf/detail workload by itself and is not included here.

Local actual-query diagnostics on the retained 100k fixture showed:

| Route | Original plan ms | Dependency-scope plan ms |
|---|---:|---:|
| fps descending | 154.641 | 131.220 |
| vmaf ascending, offset 100 | 96.717 | 79.026 |
| fps ascending, offset 500 | 88.409 | 75.801 |
| filtered fps | 135.226 | 112.122 |
| hot detail | 62.666 | 51.403 |
| createdAt descending, supplemental | 145.195 | 125.577 |
| CPU ascending, supplemental | 145.793 | 124.893 |

These are individual `EXPLAIN ANALYZE` observations on the ARM64 Mac, not a sustained capacity pass or P910 latency claim. The original P910 p95 failure remains unchanged. Both diagnostic receipts recorded baseline HEAD `35b8fae`; the after run applied exactly the production diff later committed as `e28a75f`, included in the proof archive. Existing modules were rebuilt before each relevant phase. Four old/new row-set comparisons covered 1,610 hot-cohort rows, 90 normal-cohort rows and two distant 80-row cohorts; every selected ID and complete v3 hash matched. Both serial/concurrent diagnostic rounds had zero errors.

Ten focused tests passed against actual isolated local PostgreSQL databases, with zero skips. They cover current corpus filters and sort behavior, transaction snapshot consistency, native/lease/admission faults, v2-to-v3 active-context upgrade with exact members, historical preservation, and complete-group eligibility. Added adversarial cases use two qualified groups: deleting one dependency or all dependencies withdraws PL; adding a dependency that selects cross-recipe sibling rows also withdraws PL. Certificate mismatch follows the existing invalidation/recompute path, preserving numeric scores, v3 evidence and historical members. An extra dependency with no matching run selects no extra bytes and leaves the hash unchanged; a later arrival under that key conservatively withdraws eligibility. This case is explicit rather than claiming all empty metadata can be detected by a row-state hash.

`local-proof.tar.gz` preserves all before/after plans, per-route timings, four exact coverage/hash comparisons, focused test output and the production diff. Its hash and numerical summary are in `summary.json`. Production/candidate P910 services were not queried or profiled during their native timing allocation.

## Bounded P910 diagnosis after explicit quiet allocation

The new `scripts/projection-scale/diagnose-readonly.mjs` prepares a four-minute diagnostic budget, not another pass/fail trial. It uses only the retained synthetic database and wrapper; it never calls `/mutate`, reseeds, changes limits or rewrites fixtures. SQL runs in explicitly read-only transactions with production JIT/parallel-query settings and a 15-second statement deadline. The script verifies the existing 100,020 runs / 80,020 members / zero dirty groups and the server source identity first.

It records 10 serial HTTP samples per route, three fixed rounds of 25 concurrent requests across the five original routes, seven actual query plans (five original plus two supplemental nonmetric sorts), and original/proposed certificate plans with exact row-set/hash comparisons for four representative cohorts. Every error remains in its diagnostic receipt. The original member-based scope is written explicitly in the probe, so running it against an optimized image still compares independent old/new SQL.

After the root allocates P910, restart only the retained task-owned synthetic wrapper from the reviewed image, mount the diagnostic script readonly, and run inside that image:

```sh
PROJECTION_SCALE_SERVER_ROOT=/app \
PROJECTION_SCALE_SOURCE_SHA="$VERIFIED_IMAGE_SOURCE_SHA" \
PROJECTION_SCALE_DATABASE_URL='postgresql://projection_synthetic:synthetic-isolated-only@127.0.0.1:55441/encodingdb_projection_synthetic?connection_limit=30' \
PROJECTION_SCALE_PORT=55442 \
PROJECTION_DIAGNOSTIC_OUTPUT=/evidence/new-unique-diagnostic-directory \
node /projection/diagnose-readonly.mjs
```

Use the same Linux host-network and 16 GiB disposable wrapper-container limits documented in `scripts/projection-scale/README.md`. The output directory must not already exist. Hold the common timing lock and stop only the synthetic wrapper after completion. Review actual plan rows/loops, buffer hits/reads, temporary I/O and old/new hash equivalence before deployment. After independent patch review and an updated image, the actual acceptance step remains a **fresh unchanged 100k/25-reader/600-second/1-GiB/five-writer-cycle trial** with the ≤1,000 ms p95 gate and full reconciliation. No P910 diagnostic or repeat is claimed by these prepared commands.
