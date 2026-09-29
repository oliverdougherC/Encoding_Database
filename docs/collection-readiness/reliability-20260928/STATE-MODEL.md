# Durable campaign state and recovery contract

The contributor UI must project persisted evidence rather than treating the
last callback or process exit code as the source of truth. Protocol 7.1 fixes
one warmup and two required measured repetitions per recipe by clip group;
up to two adaptive repetitions are optional and run only while needed for
stability. A maximum encode estimate is a storage/time bound, not a count of
required uploads.
The Windows Overall bar declares durable warmup and measured attempts against
the frozen maximum; the Batch bar shows durable attempts in the current segment.
The producer declares these units in each event. Unused optional adaptive slots
leave the maximum only when the measurement plan settles, and a checkpoint
cannot reset already durable campaign progress. Finished recipe by clip groups
are reported separately from both bars, as are publication and analysis status.

| Stage | Durable evidence | Allowed recovery |
| --- | --- | --- |
| Frozen plan | `campaigns/<id>/manifest.json`, saved budget and exact suite/runtime/recipe identities | Resume the same plan only with compatible measurement provenance. A new plan gets a new campaign ID. |
| Source acquisition | frozen suite lock, hash-checked cache and license notices | Resume verified partial downloads; never substitute media or suppress hash checks. |
| Runtime readiness | pinned runtime lock and persistent preparation substage/heartbeat | Retry a bounded failed probe or preparation stage without touching campaign attempts. |
| Active measurement | `in-flight.json`, process checkpoint and attempt budget | An in-flight output without `attempt-*.json` is interrupted evidence; resume the same attempt, not a completed measurement. |
| Durable attempt | fsynced `attempt-*.json`, environment and exact artifact hash | Reuse every faithful completed attempt. Warmups may be released only with verified release evidence. |
| Finalized group | stability or measured-attempt cap proved from the frozen plan; immutable `submission-*.json` for eligible measured records | Publish saved complete records with zero encoding. An unfinished group remains resumable; optional unused repeats are not missing work. |
| Queued/delayed upload | spool entry, payload hash, artifact copy, original retry deadline and next due time | Replay the same logical upload after faults. A saved envelope and its spool copy count once. Rejections and expiry stay terminal. |
| Acknowledgment | queue receipt and/or faithful journal `submission-*.accepted.json`, bound to the original run and artifact hash | Reconcile a receipt before retiring only owned accepted bytes. A lost local acknowledgment must not produce a new server identity. |
| Analysis disposition | authoritative backend run, artifact and analysis rows | Show `ACCEPTED`/`RETAINED`/`COMPLETE` separately from `SUSPECT`, `INVALID`, `REJECTED` and analysis pending. An HTTP upload receipt alone is not scientific acceptance. |

Two conservation equations must hold at every supported persistence boundary:

1. Frozen groups = finished groups + unfinished started groups + unstarted groups.
2. Eligible finalized measured records = confirmed + durably queued + unstaged envelope + journal-only candidate + explicitly terminal or blocked records. An envelope and its queued copy are one record.

`scripts/campaign_conservation.py` checks these equations independently of
the client implementation. Its seeded transition test moves one identity
through journal-only, envelope, queue, queue receipt and journal marker states.
The oracle counts recorded identities; publication separately verifies that
each retained artifact still has its promised bytes and SHA-256.
The original September 28 Mac, Windows and Linux campaign JSON reports are
retained under `.test-reports/reliability-20260928/`; they all conserve at the
observed boundaries. The repaired client still requires fault-driven native
acceptance before these invariants can be certified for its new packages.
