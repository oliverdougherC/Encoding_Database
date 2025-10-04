-- Add payloadHash for idempotency and create supporting indexes
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "payloadHash" TEXT;

-- Unique index on payloadHash (Postgres allows multiple NULLs, which is desired)
CREATE UNIQUE INDEX IF NOT EXISTS "Benchmark_payloadHash_key" ON "Benchmark"("payloadHash");

-- Helpful query indexes
CREATE INDEX IF NOT EXISTS "Benchmark_createdAt_idx" ON "Benchmark"("createdAt");
CREATE INDEX IF NOT EXISTS "Benchmark_status_idx" ON "Benchmark"("status");
CREATE INDEX IF NOT EXISTS "Benchmark_codec_idx" ON "Benchmark"("codec");
CREATE INDEX IF NOT EXISTS "Benchmark_preset_idx" ON "Benchmark"("preset");
CREATE INDEX IF NOT EXISTS "Benchmark_inputHash_idx" ON "Benchmark"("inputHash");
CREATE INDEX IF NOT EXISTS "Benchmark_codec_preset_idx" ON "Benchmark"("codec", "preset");


