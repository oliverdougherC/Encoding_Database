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

Individual measurement and pixel dispositions are preserved. An unstable group can contain valid, accepted measurements; those measurements stay visible but cannot supply PL, calibrated confidence, reference frontiers or recommendations. New 7.1 aggregate membership contains only qualified runs. Historical persisted contexts are not rewritten.

Public projection preserves raw accepted/suspect totals. Attached score values and core centers use the qualified stable-group subset and report `status.centerBasis = "eligible-stable-groups"`. Unscored data retains its accepted/suspect diagnostic basis. SQL checks the current accepted-universe fingerprint and a full underlying group-state certificate, including non-selected siblings, before attaching a derived result. Both certificates are computed during the same locked, revalidated derived write. This uses the shared eligibility proof rather than duplicating the stability algorithm in SQL. Cheap candidate matching occurs before sorting/pagination; expensive live certificate checks remain page-bounded. A stale candidate is invalidated, queued for recomputation and selection retries at most three times.

Regression coverage includes the reproduced `[1000, 1030.507, 1000, 1000]` ms case: three independent unstable groups previously produced HIGH confidence with zero confidence-interval width. They now retain 12 raw accepted observations but have null PL, PROVISIONAL evidence and no recommendation eligibility. Tests also cover missing/partial/mixed receipts, exact float mismatch, model/build mismatch, sibling investigation/revocation, missing sibling bytes, complete-group qualification independent of exported subset, and qualified versus diagnostic projection in mixed cohorts.

The integrated local server suite passed 222 tests with zero skips using separate migrated PostgreSQL databases for backend, group, corpus and namespace tests. This proof does not substitute for a fresh 100,000-row / 25-browser staging projection check after the query change. The parent integration lane owns that performance check and the final packaged-client deployment rehearsal.
