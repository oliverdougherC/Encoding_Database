-- Data Integrity Sprint 1: B-D01, B-S01 schema, B-C08
-- Backfill NULLs, alter columns to NOT NULL with defaults, add sum columns

-- 1. Backfill NULL gpuModel and crf in Benchmark
UPDATE "Benchmark" SET "gpuModel" = '' WHERE "gpuModel" IS NULL;
UPDATE "Benchmark" SET "crf" = 24 WHERE "crf" IS NULL;

-- 2. Backfill NULL gpuModel and crf in Submission
UPDATE "Submission" SET "gpuModel" = '' WHERE "gpuModel" IS NULL;
UPDATE "Submission" SET "crf" = 24 WHERE "crf" IS NULL;

-- 3. De-duplicate Benchmark rows that now collide on the compound unique key
-- Keep the row with the highest samples count for each compound key
DELETE FROM "Benchmark" b
USING "Benchmark" b2
WHERE b."cpuModel" = b2."cpuModel"
  AND b."gpuModel" = b2."gpuModel"
  AND b."ramGB" = b2."ramGB"
  AND b."os" = b2."os"
  AND b."codec" = b2."codec"
  AND b."preset" = b2."preset"
  AND b."crf" = b2."crf"
  AND (b."samples" < b2."samples" OR (b."samples" = b2."samples" AND b."id" < b2."id"));

-- 4. Alter Benchmark columns to NOT NULL with defaults
ALTER TABLE "Benchmark" ALTER COLUMN "gpuModel" SET NOT NULL;
ALTER TABLE "Benchmark" ALTER COLUMN "gpuModel" SET DEFAULT '';
ALTER TABLE "Benchmark" ALTER COLUMN "crf" SET NOT NULL;
ALTER TABLE "Benchmark" ALTER COLUMN "crf" SET DEFAULT 24;

-- 5. Alter Submission columns to NOT NULL with defaults
ALTER TABLE "Submission" ALTER COLUMN "gpuModel" SET NOT NULL;
ALTER TABLE "Submission" ALTER COLUMN "gpuModel" SET DEFAULT '';
ALTER TABLE "Submission" ALTER COLUMN "crf" SET NOT NULL;
ALTER TABLE "Submission" ALTER COLUMN "crf" SET DEFAULT 24;

-- 6. Add sum columns to Benchmark
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "fpsSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "fileSizeSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "vmafSum" DOUBLE PRECISION NOT NULL DEFAULT 0;

-- 7. Backfill sum columns from existing averages: sum = avg * samples
UPDATE "Benchmark"
SET "fpsSum" = "fps" * GREATEST("samples", 1),
    "fileSizeSum" = "fileSizeBytes" * GREATEST("samples", 1),
    "vmafSum" = COALESCE("vmaf", 0) * GREATEST("vmafSamples", 0)
WHERE "samples" > 0 OR "vmafSamples" > 0;
