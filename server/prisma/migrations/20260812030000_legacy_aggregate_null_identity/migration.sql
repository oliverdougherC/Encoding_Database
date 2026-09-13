-- The legacy aggregate is isolated from canonical v7 evidence, but it must still
-- have one identity row while the compatibility endpoint remains available.
-- PostgreSQL 15+ NULLS NOT DISTINCT closes the workloadId=NULL uniqueness hole.
CREATE UNIQUE INDEX "Benchmark_legacy_identity_nulls_not_distinct_key"
  ON "Benchmark" (
    "cpuModel", "gpuModel", "ramGB", "os", "codec", "preset", "crf",
    "contentClass", "resolution", "passes", "workloadId"
  ) NULLS NOT DISTINCT;
