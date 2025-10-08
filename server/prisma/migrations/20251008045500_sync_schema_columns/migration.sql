-- Sync DB with Prisma schema: add missing columns used by the API

-- Add updatedAt column required by Prisma's @updatedAt
ALTER TABLE "Benchmark" 
  ADD COLUMN IF NOT EXISTS "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- Add aggregation counters present in schema
ALTER TABLE "Benchmark"
  ADD COLUMN IF NOT EXISTS "samples" INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS "vmafSamples" INTEGER NOT NULL DEFAULT 0;

-- Note: Composite unique constraint is defined in schema, but we avoid forcing it here
-- to prevent migration failures if legacy duplicate rows exist. It can be added later
-- after de-duplicating existing data:
-- CREATE UNIQUE INDEX IF NOT EXISTS "Benchmark_cpuModel_gpuModel_ramGB_os_codec_preset_crf_key"
--   ON "Benchmark"("cpuModel","gpuModel","ramGB","os","codec","preset","crf");


