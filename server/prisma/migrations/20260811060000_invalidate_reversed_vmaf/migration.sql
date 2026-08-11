-- VMAF collected before client/0.1.1 used the reference and distorted
-- streams in reverse order. Encoded artifacts are not retained, so those
-- measurements cannot be recomputed safely. Invalidate both raw values and
-- aggregate state before accepting corrected client submissions.
UPDATE "Submission"
SET "vmaf" = NULL;

UPDATE "Benchmark"
SET
  "vmaf" = NULL,
  "vmafSamples" = 0,
  "vmafSum" = 0;
