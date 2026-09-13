ALTER TABLE "Submission"
  ADD COLUMN "vmafP5" DOUBLE PRECISION,
  ADD COLUMN "videoBitrateBps" DOUBLE PRECISION,
  ADD COLUMN "sourceFps" DOUBLE PRECISION,
  ADD COLUMN "sourceDurationSeconds" DOUBLE PRECISION,
  ADD COLUMN "scoreFormulaVersion" TEXT,
  ADD COLUMN "benchmarkProtocolVersion" TEXT,
  ADD COLUMN "sourceSuiteVersion" TEXT,
  ADD COLUMN "workloadId" TEXT,
  ADD COLUMN "metricModelId" TEXT;

ALTER TABLE "Benchmark"
  ADD COLUMN "vmafP5" DOUBLE PRECISION,
  ADD COLUMN "videoBitrateBps" DOUBLE PRECISION,
  ADD COLUMN "sourceFps" DOUBLE PRECISION,
  ADD COLUMN "sourceDurationSeconds" DOUBLE PRECISION,
  ADD COLUMN "scoreFormulaVersion" TEXT,
  ADD COLUMN "benchmarkProtocolVersion" TEXT,
  ADD COLUMN "sourceSuiteVersion" TEXT,
  ADD COLUMN "workloadId" TEXT,
  ADD COLUMN "metricModelId" TEXT,
  ADD COLUMN "vmafP5Samples" INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN "vmafP5Sum" DOUBLE PRECISION NOT NULL DEFAULT 0,
  ADD COLUMN "videoBitrateSamples" INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN "videoBitrateSum" DOUBLE PRECISION NOT NULL DEFAULT 0,
  ADD COLUMN "sourceFpsSamples" INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN "sourceFpsSum" DOUBLE PRECISION NOT NULL DEFAULT 0;

CREATE INDEX "Submission_workloadId_idx" ON "Submission"("workloadId");
CREATE INDEX "Benchmark_workloadId_idx" ON "Benchmark"("workloadId");

ALTER TABLE "Benchmark"
  DROP CONSTRAINT IF EXISTS "Benchmark_cpuModel_gpuModel_ramGB_os_codec_preset_crf_conte_key";
ALTER TABLE "Benchmark"
  ADD CONSTRAINT "Benchmark_v7_aggregate_key"
  UNIQUE ("cpuModel", "gpuModel", "ramGB", "os", "codec", "preset", "crf", "contentClass", "resolution", "passes", "workloadId");
