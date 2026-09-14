# Complete measurement-group qualification

The canonical 7.1 client now supplies an optional final receipt on each measured run:

```json
{
  "measurementGroup": {
    "schemaVersion": "encodingdb-measurement-group/v1",
    "campaignId": "same-as-run",
    "repetitionGroupId": "same-as-run",
    "completed": true,
    "countedAttempts": [
      { "repetitionIndex": 1, "encodeWallTimeMs": 1990.073417 },
      { "repetitionIndex": 2, "encodeWallTimeMs": 1991.125 }
    ]
  }
}
```

Entries must be sorted and unique, contain 2–4 counted measured attempts, and preserve the exact floating-point milliseconds of the corresponding runs. The receipt contains no client-chosen threshold or stable boolean. Intake stores it under the existing `preRunEnvironmentCheck.measurementGroup` JSON field, checks the exact current member, and prevents an existing completed group plan or repetition identity from being changed. Missing old receipts remain unscored; old raw requests are not rewritten.

`measurementGroup.ts` is the shared eligibility gate. It loads the full persisted group by physical source, campaign and group ID, independently of any page/filter/export/frontier subset, taking at most five records to detect excess members. It verifies identical complete receipts, exact membership and elapsed values, canonical source/timing tuples, experiment identities, current model/worker/build and effective retained review state. The canonical protocol supplies minimum two observations, maximum four, and `(max elapsed - min elapsed) / mean elapsed <= 0.03`. A selected frontier point can use one run while the gate still verifies all its underlying repetitions. Live calibration verification additionally hashes every sibling's retained object, including siblings outside the exported corpus.

Every 7.1 member also needs a current CPU observation: `preRunEnvironmentCheck.snapshot.telemetry_sources` must contain the exact comma-separated marker `cpu_psutil_thread_window_v1` or `cpu_psutil_blocking_window_v1`, and `snapshot.background_cpu_pct` must be a finite number. Measured idle zero qualifies; missing values and the old `cpu_psutil` marker do not. This prevents old development measurements made with the incorrect per-thread sampler baseline from silently qualifying. The gate does not reinterpret old raw flags.

Individual measurement and pixel dispositions are preserved. An unstable group can contain valid, accepted measurements; those measurements stay visible but cannot supply PL, calibrated confidence, reference frontiers or recommendations. New 7.1 aggregate membership contains only qualified runs. Historical persisted contexts are not rewritten.

Public projection preserves raw accepted/suspect totals. Attached score values and core centers use the qualified stable-group subset and report `status.centerBasis = "eligible-stable-groups"`. Unscored data retains its accepted/suspect diagnostic basis. SQL checks the current accepted-universe fingerprint and a full underlying group-state certificate, including non-selected siblings, before attaching a derived result. Both certificates are computed during the same locked, revalidated derived write. This uses the shared eligibility proof rather than duplicating the stability algorithm in SQL. The `DerivedResultGroupDependency` read-model table makes source mutations invalidate their affected qualified projections before sorting and pagination. This includes nonaccepted extra siblings, analysis/artifact/review changes, source/protocol changes, and the complete pre-run observation JSON. Group advisory locks serialize certificate publication with dependency invalidation. These markers do not alter historical score values or member rows; a restarted dispatcher refreshes only the explicitly active context. Cheap indexed dependency matching occurs before sorting/pagination; expensive live certificate checks remain page-bounded. Unexpected certificate mismatches still trigger bounded reselection as a secondary defense.

Regression coverage includes the reproduced `[1000, 1030.507, 1000, 1000]` ms case: three independent unstable groups previously produced HIGH confidence with zero confidence-interval width. They now retain 12 raw accepted observations but have null PL, PROVISIONAL evidence and no recommendation eligibility. Tests also cover missing/partial/mixed receipts, exact float mismatch, model/build mismatch, sibling investigation/revocation, missing sibling bytes, complete-group qualification independent of exported subset, qualified versus diagnostic projection in mixed cohorts, corrected/old/missing/nonfinite CPU observations, and an off-page fallback crossing: A sorts below B using its stable center, then a nonaccepted extra sibling invalidates A so its faster diagnostic center correctly sorts first even with `take: 1`. A separate database regression proves dirty dependencies are discovered after restart with no quality-analysis retry flag. Bookkeeping writes leave qualification intact; unrelated groups and original historical score rows remain unchanged.

The integrated local server suite passed 222 tests with zero skips using separate migrated PostgreSQL databases for backend, group, corpus and namespace tests. This proof does not substitute for a fresh 100,000-row / 25-browser staging projection check after the query change. The parent integration lane owns that performance check and the final packaged-client deployment rehearsal.

The additive migration `20260914015000_group_projection_dependencies` was deployed to six isolated test databases; its final form also passed all 29 migrations from an empty seventh database and the three complete-group tests on that fresh schema. The final full suite and focused restart/off-page receipts are retained alongside this document. No production database or retained measurement was changed by these tests.
