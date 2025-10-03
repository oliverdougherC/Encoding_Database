-- Alter Benchmark table to include submission metadata and status
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "status" TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegVersion" TEXT;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "encoderName" TEXT;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "clientVersion" TEXT;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "inputHash" TEXT;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "runMs" INTEGER;

