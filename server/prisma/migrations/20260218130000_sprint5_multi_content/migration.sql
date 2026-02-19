-- Sprint 5: Multi-Content and Resolution Testing

-- Add multi-content and resolution fields to Benchmark
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "contentClass" TEXT NOT NULL DEFAULT 'mixed';
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "resolution" TEXT NOT NULL DEFAULT '1080p';
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "passes" INTEGER NOT NULL DEFAULT 1;

-- Add multi-content and resolution fields to Submission
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "contentClass" TEXT NOT NULL DEFAULT 'mixed';
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "resolution" TEXT NOT NULL DEFAULT '1080p';
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "passes" INTEGER NOT NULL DEFAULT 1;

-- Drop old unique constraint and create new one including the new dimensions
ALTER TABLE "Benchmark" DROP CONSTRAINT IF EXISTS "Benchmark_cpuModel_gpuModel_ramGB_os_codec_preset_crf_key";
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'Benchmark_cpuModel_gpuModel_ramGB_os_codec_preset_crf_conte_key'
      AND conrelid = '"Benchmark"'::regclass
  ) THEN
    ALTER TABLE "Benchmark" ADD CONSTRAINT "Benchmark_cpuModel_gpuModel_ramGB_os_codec_preset_crf_conte_key"
      UNIQUE ("cpuModel", "gpuModel", "ramGB", "os", "codec", "preset", "crf", "contentClass", "resolution", "passes");
  END IF;
END
$$;

-- Update Submission compound index to include new dimensions
DROP INDEX IF EXISTS "Submission_cpuModel_gpuModel_ramGB_os_codec_preset_crf_idx";
CREATE INDEX IF NOT EXISTS "Submission_cpuModel_gpuModel_ramGB_os_codec_preset_crf_conte_idx"
  ON "Submission"("cpuModel", "gpuModel", "ramGB", "os", "codec", "preset", "crf", "contentClass", "resolution", "passes");

-- New indexes for filtering by content/resolution
CREATE INDEX IF NOT EXISTS "Benchmark_contentClass_idx" ON "Benchmark"("contentClass");
CREATE INDEX IF NOT EXISTS "Benchmark_resolution_idx" ON "Benchmark"("resolution");
CREATE INDEX IF NOT EXISTS "Benchmark_contentClass_resolution_idx" ON "Benchmark"("contentClass", "resolution");
CREATE INDEX IF NOT EXISTS "Submission_contentClass_idx" ON "Submission"("contentClass");
CREATE INDEX IF NOT EXISTS "Submission_resolution_idx" ON "Submission"("resolution");

-- TestVideo catalog table
CREATE TABLE IF NOT EXISTS "TestVideo" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "contentClass" TEXT NOT NULL,
    "resolution" TEXT NOT NULL,
    "duration" DOUBLE PRECISION NOT NULL,
    "sha256" TEXT NOT NULL,
    "downloadUrl" TEXT NOT NULL,
    "sizeBytes" INTEGER NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "TestVideo_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX IF NOT EXISTS "TestVideo_sha256_key" ON "TestVideo"("sha256");
CREATE INDEX IF NOT EXISTS "TestVideo_contentClass_idx" ON "TestVideo"("contentClass");
CREATE INDEX IF NOT EXISTS "TestVideo_contentClass_resolution_idx" ON "TestVideo"("contentClass", "resolution");
