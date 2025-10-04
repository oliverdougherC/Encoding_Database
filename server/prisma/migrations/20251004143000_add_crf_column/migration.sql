-- AlterTable: add optional crf column to Benchmark
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "crf" INTEGER;

-- Optional: index if querying by crf later (commented for now)
-- CREATE INDEX IF NOT EXISTS "Benchmark_crf_idx" ON "Benchmark"("crf");

