# PL objective preparation — October 4–5, 2026

**The retained-data analysis is complete; PL remains provisional.**
The [final report](final-readiness.json) separates completed evidence work from
remaining objective coverage and genuine review requirements. Nothing was
promoted, merged or deployed by this calibration lane.

## Final evidence

- **220 qualified canonical fitting observations**, six content classes, three
  verified physical machines and two hardware families. The real reference
  builder finds a 90-VMAF frontier bracket for each covered class.
- **74 longer-scene measured observations analyzed and preserved:** 32 COMPLETE,
  42 SUSPECT. Sixteen complete groups / 32 rows qualify for holdout use. The five
  original timing-unstable cells remain excluded.
- The now-terminal original candidate was refreshed using the same protocol,
  model and three verified source IDs. Its **214 eligible original canonical
  records are unchanged**, with no newly qualified or altered evidence records.
  The combined fitting set additionally contains six qualifying new observations.
- Eleven distinct new Mac cells retained 37 attempts / 26 measured observations.
  Raw analyses were 15 ACCEPTED and 11 SUSPECT. Only three cells / six rows passed
  complete-group eligibility: x264-fast screen CRF38, x264-fast grain CRF14 and
  x265-fast talking-head CRF30. All negative results remain preserved.

The analysis completion checkpoint and the earlier interim assessment are retained
as historical evidence; they do not supersede these final counts.

## Why activation is still blocked

**Dark gradients has no qualified fitting evidence.** Its high-quality CRF14
fast/slow groups failed the unchanged 3% timing rule at 5.61% and 6.62%.
Human metric review cannot rehabilitate unstable timing. No further measurement
rounds were performed.

There are also **20 rate-coverage and eight within-preset findings** (some overlap),
no completed independently fitted holdout evaluations, no genuine golden or
family-choice judgments, and no reviewed freeze. Three global machines do not
establish independent corroboration for every recipe/environment cohort. The
[exact assessment](final-assessment.json) remains `readyForProductionFreeze=false`.
Held-out observations were never relabeled as fitting evidence to fill a gap.

## Correctness and provenance

Fitting-coverage order dependence, excessive export memory use and incomplete
validation-import protocol metadata were corrected without changing score
constants or eligibility thresholds. Original source databases and snapshots are
unchanged; new derived snapshots bind audited protocol aliases, original receipt
hashes, exact measurement identities and retained bytes. All 37 analyzed groups
were imported with their quality flags intact.

Calibration-lane source checks passed 275 server tests with zero failures and seven
conditional database skips. A separate real PostgreSQL calibration run passed
40 with one unrelated three-database snapshot skip. The new metadata-repair
regressions passed 13. The later integrated server run passed all 285 tests with real PostgreSQL bindings; see the [integrated verification](../overnight-20261004/verification-summary.json). An original/new exporter comparison matched complete JSON
and hashes for four real rows spanning two complete H264/AV1 groups.

The actual package build revision is `3e798c70be64bf87bc821cb629aebbc68cdc3819`;
`44b9e1501bc1bbdc2133317bd83ce5d847ad4103` was the logical review-head label.
Their complete Git trees are identical. The
[additive correction](package-provenance-correction.json) preserves measured records.

## Human review prepared, not invented

The local catalog retains 97 representative original videos and seven lossless
reference previews with 1,632 identical decoded-frame hashes. Three diagnostic
cases are ready for genuine expert review now, with six exact analysis bindings,
actual metric bands and blank responses. All six diagnostic players passed
actual decoding, playback and midpoint seeking; see the
[browser proof](diagnostic-browser-proof.json).

Those judgments can clear specific metric concerns. They cannot fix timing,
replace independent folds or approve the global score. Final sign-off stays
blocked. Media remain in task-owned evidence storage; no media or credentials
were added to Git, and the existing public-path redactions remain intact.

## Final integrity and shutdown

The [final integrity check](final-holdout-integrity.json) verifies all 74 exact
run/analysis/artifact bindings, 720 frames per observation, the prescribed model,
worker and timing boundary, and every encoded object's byte size and SHA256.
The 74 artifact bindings reference 37 unique encoded objects; repeated observations
remain separate records and do not count as independent machines. All 37 measurement groups were checked;
16 qualify and 21 remain ineligible because of their preserved metric flags.
Storage states remain 32 RETAINED and 42 VERIFIED; those states are not conflated.

After final reads, the [cleanup receipt](cleanup-summary.json) records zero pending
task analyses, 17 preserved task containers, no running task containers/listeners,
and no removed databases or volumes. The shared original candidate, PostgreSQL
and root preview were untouched. Review files remain available as local artifacts;
viewing helpers can be restarted explicitly if needed.
